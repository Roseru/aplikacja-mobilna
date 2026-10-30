"""Bounded read-only PostgreSQL observations for the single-Meal E4 replay trial."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

TABLES = (
    "meals",
    "meal_items",
    "diary_days",
    "sync_receipts",
    "sync_changes",
    "sync_counters",
)
FIELDS = {
    "trial_id",
    "owner_id",
    "operation_id",
    "entity_id",
    "sync_epoch",
    "local_date",
    "operation_sha256",
    "item_count",
    "expected_schema",
    "expected_api_image",
    "envelope_sha256",
    "expected_meal",
}
MAX_DRIVER_PREPARED_BYTES = 5_000_000
MAX_DRIVER_REQUEST_BYTES = 65_536


def meal_content(payload):
    """Normalize storage representations only, preserving nulls, text and item order."""
    result = deepcopy(payload)
    instant = datetime.fromisoformat(result["occurred_at"])
    if instant.tzinfo is None:
        raise ValueError("Meal time requires an offset")
    result["occurred_at"] = instant.astimezone(UTC).isoformat(timespec="microseconds")

    def decimal(value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            raise ValueError("Expected a finite decimal string")
        number = Decimal(value)
        return format(number, "f").rstrip("0").rstrip(".") if "." in value else value

    for item in result["items"]:
        item["quantity"]["amount"] = decimal(item["quantity"]["amount"])
        item["density_g_per_ml"] = decimal(item["density_g_per_ml"])
        for field in ("energy_kcal", "protein_g", "fat_g", "carbs_g"):
            item["nutrition_per_100"][field] = decimal(item["nutrition_per_100"][field])
    return result


def prepare_plan(context, raw_request):
    """Offline preparation in the matching backend runtime; never call API or DB."""
    # Reuse the normative parser/preflight; capture/compare remain stdlib-only.
    from calorie_app.modules.catalog.validation import parse_json
    from calorie_app.modules.sync.errors import SyncFailure
    from calorie_app.modules.sync.schemas import preflight_structure
    from calorie_app.modules.sync.service import fingerprint

    if set(context) != {"trial_id", "owner_id", "expected_schema", "expected_api_image"}:
        raise ValueError("Invalid preparation context")
    request = parse_json(raw_request)
    try:
        preflight_structure(request)
    except SyncFailure:
        raise ValueError("Invalid frozen envelope") from None
    if len(request["operations"]) != 1:
        raise ValueError("Require exactly one Meal/create")
    operation = request["operations"][0]
    if (
        operation["entity_type"] != "meal"
        or operation["action"] != "upsert"
        or operation["base_revision"] is not None
        or operation["sync_epoch"] != request["sync_epoch"]
    ):
        raise ValueError("Require exactly one Meal/create in the envelope epoch")
    plan = {
        **context,
        **{key: operation[key] for key in ("operation_id", "entity_id", "sync_epoch")},
        "local_date": operation["payload"]["local_date"],
        "item_count": len(operation["payload"]["items"]),
        "operation_sha256": fingerprint(operation),
        "envelope_sha256": hashlib.sha256(raw_request).hexdigest(),
        "expected_meal": operation["payload"],
    }
    validate_plan(plan)
    return plan


def prepare_driver_plan(context, raw_prepared: bytes):
    """Bind the driver's exact request bytes to a PG plan, without accepting the trial."""
    if (
        not isinstance(raw_prepared, bytes)
        or not 1 <= len(raw_prepared) <= MAX_DRIVER_PREPARED_BYTES
    ):
        raise ValueError("Invalid driver preparation size")

    from calorie_app.modules.catalog.validation import parse_json

    prepared = parse_json(raw_prepared)
    if (
        type(prepared.get("driver_guard_version")) is not int
        or prepared["driver_guard_version"] != 2
        or type(prepared.get("room")) is not int
        or prepared["room"] != 23
        or any(
            not isinstance(prepared.get(key), str)
            for key in ("trial", "meal", "operation", "request", "hash", "context")
        )
        or re.fullmatch(r"[0-9a-f]{64}", prepared["hash"]) is None
    ):
        raise ValueError("Invalid driver preparation metadata")
    raw_request = prepared["request"].encode("utf-8")
    if (
        not 1 <= len(raw_request) <= MAX_DRIVER_REQUEST_BYTES
        or hashlib.sha256(raw_request).hexdigest() != prepared["hash"]
    ):
        raise ValueError("Driver request size or digest mismatch")

    wire_context = parse_json(prepared["context"].encode("utf-8"))
    plan = prepare_plan(context, raw_request)
    if (
        prepared["trial"] != plan["trial_id"]
        or prepared["meal"] != plan["entity_id"]
        or prepared["operation"] != plan["operation_id"]
        or wire_context.get("account_id") != plan["owner_id"]
        or wire_context.get("sync_epoch") != plan["sync_epoch"]
    ):
        raise ValueError("Driver metadata differs from the observation context or frozen request")
    return plan


def validate_plan(plan):
    if set(plan) != FIELDS:
        raise ValueError("Invalid observation plan fields")
    for key in ("trial_id", "owner_id", "operation_id", "entity_id", "sync_epoch"):
        if not isinstance(plan[key], str) or str(UUID(plan[key])) != plan[key]:
            raise ValueError("Plan requires canonical UUIDs")
    if date.fromisoformat(plan["local_date"]).isoformat() != plan["local_date"]:
        raise ValueError("Plan requires an ISO date")
    for key, pattern in (
        ("operation_sha256", r"[0-9a-f]{64}"),
        ("envelope_sha256", r"[0-9a-f]{64}"),
        ("expected_api_image", r"sha256:[0-9a-f]{64}"),
        ("expected_schema", r"[a-z0-9_]{1,64}"),
    ):
        if not isinstance(plan[key], str) or not re.fullmatch(pattern, plan[key]):
            raise ValueError("Invalid expected identity or hash")
    if type(plan["item_count"]) is not int or not 1 <= plan["item_count"] <= 100:
        raise ValueError("Plan requires 1..100 meal items")
    expected = meal_content(plan["expected_meal"])
    if expected["local_date"] != plan["local_date"] or len(expected["items"]) != plan["item_count"]:
        raise ValueError("Expected Meal differs from plan metadata")
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def observation_sql(plan, phase):
    plan_hash = validate_plan(plan)
    return _observation_sql(plan, phase, plan_hash)


def _observation_sql(plan, phase, plan_hash):
    """Internal SQL renderer; callers must qualify their own plan and runtime first."""
    if phase not in {"C0", "C1", "C2"}:
        raise ValueError("Invalid observation phase")
    owner, meal, operation = (plan[k] for k in ("owner_id", "entity_id", "operation_id"))
    aggregates = []
    for table in TABLES:
        # Fixed table names, UUID/date inputs validated above; no caller-supplied SQL.
        aggregates.append(
            f"'{table}', (SELECT jsonb_build_object('count', count(*), 'sha256', "
            "encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(t) "
            "ORDER BY to_jsonb(t)::text), '[]'::jsonb)::text, 'UTF8')), 'hex')) "
            f"FROM app.{table} t WHERE owner_id='{owner}'::uuid)"
        )
    return f"""
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '1s';
SET LOCAL timezone = 'UTC';
SELECT jsonb_build_object(
 'format', 2, 'phase', '{phase}', 'plan_sha256', '{plan_hash}',
 'observed_at', clock_timestamp(), 'backend_pid', pg_backend_pid(),
 'read_only', current_setting('transaction_read_only'),
 'schema', (SELECT jsonb_agg(version_num ORDER BY version_num) FROM app.alembic_version),
 'epoch', (SELECT sync_epoch FROM app.installation_state WHERE id=1),
 'account', (SELECT jsonb_build_object('id', id, 'generation', generation, 'state', state)
             FROM app.user_accounts WHERE id='{owner}'::uuid),
 'meal', (SELECT jsonb_build_object('id', id, 'revision', revision,
           'local_date', local_date, 'deleted', deleted_at IS NOT NULL)
          FROM app.meals WHERE owner_id='{owner}'::uuid AND id='{meal}'::uuid),
 'items', (SELECT count(*) FROM app.meal_items
           WHERE owner_id='{owner}'::uuid AND meal_id='{meal}'::uuid),
 'meal_content', (SELECT jsonb_build_object(
           'title', m.title, 'occurred_at', m.occurred_at, 'time_zone', m.time_zone,
           'local_date', m.local_date, 'meal_type', m.meal_type, 'goal_id', m.goal_id,
           'ration', m.ration, 'items', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
             'item_id', i.item_id, 'name', i.name,
             'product', CASE WHEN i.product_id IS NULL THEN NULL ELSE
               jsonb_build_object('product_id', i.product_id, 'revision', i.product_revision) END,
             'quantity', jsonb_build_object('amount', i.quantity_amount::text,
                                            'unit', i.quantity_unit),
             'basis_unit', i.basis_unit, 'nutrition_per_100', jsonb_build_object(
               'energy_kcal', i.energy_kcal::text, 'protein_g', i.protein_g::text,
               'fat_g', i.fat_g::text, 'carbs_g', i.carbs_g::text),
             'density_g_per_ml', i.density_g_per_ml::text, 'density_source', i.density_source,
             'nutrition_origin', i.nutrition_origin, 'formula_version', i.formula_version,
             'ration_component_position', i.ration_component_position
           ) ORDER BY i.position), '[]'::jsonb) FROM app.meal_items i
           WHERE i.owner_id=m.owner_id AND i.meal_id=m.id))
          FROM app.meals m WHERE m.owner_id='{owner}'::uuid AND m.id='{meal}'::uuid),
 'day', (SELECT jsonb_build_object('id', id, 'revision', revision,
           'deleted', deleted_at IS NOT NULL) FROM app.diary_days
          WHERE owner_id='{owner}'::uuid AND local_date='{plan["local_date"]}'::date),
 'receipt', (SELECT jsonb_build_object('operation_id', operation_id, 'entity_id', entity_id,
           'entity_type', entity_type, 'action', action, 'status', status, 'code', code,
           'revision', revision, 'request_hash', request_hash, 'source_epoch', source_epoch,
           'recovery_epoch', recovery_epoch, 'recovery_entity_id', recovery_entity_id)
          FROM app.sync_receipts
          WHERE owner_id='{owner}'::uuid AND operation_id='{operation}'::uuid),
 'position', (SELECT position FROM app.sync_counters WHERE owner_id='{owner}'::uuid),
 'tables', jsonb_build_object({", ".join(aggregates)})
);
ROLLBACK;
"""


def compare(plan, snapshots):
    """Server-only verdict. HTTP, Room, barrier and real restart need separate evidence."""
    plan_hash = validate_plan(plan)
    if [s["phase"] for s in snapshots] != ["C0", "C1", "C2"]:
        raise ValueError("Require C0, C1 and C2 in order")
    c0, c1, c2 = snapshots
    times = [datetime.fromisoformat(s["observed_at"]) for s in snapshots]
    if any(t.tzinfo is None for t in times) or not times[0] < times[1] < times[2]:
        raise ValueError("Observation timestamps must increase")
    for snapshot in snapshots:
        if (
            snapshot["format"] != 2
            or snapshot["plan_sha256"] != plan_hash
            or snapshot["read_only"] != "on"
            or snapshot["schema"] != [plan["expected_schema"]]
            or snapshot["epoch"] != plan["sync_epoch"]
            or snapshot["api_image"] != plan["expected_api_image"]
            or snapshot["postgres_container"] != c0["postgres_container"]
            or snapshot["account"] != c0["account"]
        ):
            raise ValueError("Observation identity, context or read-only invariant failed")
    if (
        not c0["account"]
        or c0["account"]["id"] != plan["owner_id"]
        or c0["account"]["state"] != "active"
        or c0["meal"] is not None
        or c0["receipt"] is not None
        or c0["items"] != 0
    ):
        raise ValueError("C0 is not an active account with an absent target and receipt")
    expected = {
        "id": plan["entity_id"],
        "revision": 1,
        "local_date": plan["local_date"],
        "deleted": False,
    }
    receipt = {
        "operation_id": plan["operation_id"],
        "entity_id": plan["entity_id"],
        "entity_type": "meal",
        "action": "upsert",
        "status": "accepted",
        "code": None,
        "revision": 1,
        "request_hash": plan["operation_sha256"],
        "source_epoch": plan["sync_epoch"],
        "recovery_epoch": None,
        "recovery_entity_id": None,
    }
    if c1["meal"] != expected or c1["receipt"] != receipt or c1["items"] != plan["item_count"]:
        raise ValueError("C1 does not contain the expected committed Meal and receipt")
    if meal_content(c1["meal_content"]) != meal_content(plan["expected_meal"]):
        raise ValueError("C1 Meal content differs from the frozen expected operation")
    if c1["day"] is None or c1["day"]["deleted"]:
        raise ValueError("C1 requires a live DiaryDay")
    if c0["day"] is not None and c0["day"] != c1["day"]:
        raise ValueError("Existing DiaryDay changed")
    new_day = int(c0["day"] is None)
    deltas = {
        "meals": 1,
        "meal_items": plan["item_count"],
        "diary_days": new_day,
        "sync_receipts": 1,
        "sync_changes": 1 + new_day,
        "sync_counters": int(c0["position"] is None),
    }
    for table, delta in deltas.items():
        if c1["tables"][table]["count"] - c0["tables"][table]["count"] != delta:
            raise ValueError("Unexpected C0 to C1 row counts")
    if c1["position"] - (c0["position"] or 0) != 1 + new_day:
        raise ValueError("Unexpected C0 to C1 counter delta")
    for key in ("meal", "items", "meal_content", "day", "receipt", "position", "tables"):
        if c2[key] != c1[key]:
            raise ValueError("Replay changed committed server state")
    return {
        "server_observations": "PASS",
        "trial_id": plan["trial_id"],
        "overall_apk_api_trial": "REQUIRES_SEPARATE_O1_HTTP_ROOM_RESTART_EVIDENCE",
    }


def docker_command(docker, *arguments, input_text=None):
    result = subprocess.run(
        [str(docker), *arguments],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=15,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    if result.returncode:
        raise RuntimeError("Observation command failed; raw database output withheld")
    return result.stdout


def capture(settings, plan, phase):
    sql = observation_sql(plan, phase)
    state = Path(settings["state"]).resolve(strict=True)
    config = json.loads((state / "config.json").read_text(encoding="utf-8-sig"))
    project = config["project"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", project):
        raise ValueError("Invalid installation project")
    identities = {}
    for service in ("postgres", "api"):
        info = json.loads(docker_command(settings["docker"], "inspect", f"{project}-{service}-1"))[
            0
        ]
        labels = info["Config"]["Labels"]
        if (
            labels.get("com.docker.compose.project") != project
            or labels.get("com.docker.compose.service") != service
            or not info["State"]["Running"]
        ):
            raise ValueError("Container identity or running state mismatch")
        identities[service] = info
    if identities["api"]["Image"] != plan["expected_api_image"]:
        raise ValueError("API image differs from the observation plan")
    raw = docker_command(
        settings["docker"],
        "exec",
        "-i",
        identities["postgres"]["Id"],
        "psql",
        "-X",
        "-qAt",
        "-U",
        "postgres",
        "-d",
        "calorie_app",
        "-v",
        "ON_ERROR_STOP=1",
        input_text=sql,
    )
    snapshot = json.loads(raw)
    if snapshot["schema"] != [plan["expected_schema"]] or snapshot["epoch"] != plan["sync_epoch"]:
        raise ValueError("Actual schema or epoch differs from the observation plan")
    snapshot.update(
        api_image=identities["api"]["Image"],
        postgres_container=identities["postgres"]["Id"],
    )
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare", help="Use matching backend runtime before C0")
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path)
    source.add_argument("--driver-prepared", type=Path)
    prepare.add_argument("--output", type=Path, required=True)
    save = sub.add_parser("capture")
    save.add_argument("--settings", type=Path, required=True)
    save.add_argument("--phase", choices=("C0", "C1", "C2"), required=True)
    save.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("compare")
    check.add_argument("snapshots", type=Path, nargs=3)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        if args.action == "prepare":
            if args.driver_prepared is not None:
                with args.driver_prepared.open("rb") as source:
                    raw_prepared = source.read(MAX_DRIVER_PREPARED_BYTES + 1)
                plan = prepare_driver_plan(plan, raw_prepared)
            else:
                plan = prepare_plan(plan, args.request.read_bytes())
            with args.output.open("x", encoding="utf-8") as output:
                os.chmod(args.output, 0o600)
                json.dump(plan, output, indent=2)
            print(json.dumps({"private_plan": "SAVED", "overall_apk_api_trial": "NOT_ASSESSED"}))
        elif args.action == "capture":
            settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))
            snapshot = capture(settings, plan, args.phase)
            # Exclusive creation preserves earlier evidence; caller uses an ACL-private directory.
            with args.output.open("x", encoding="utf-8") as output:
                os.chmod(args.output, 0o600)
                json.dump(snapshot, output, indent=2)
            print(
                json.dumps(
                    {
                        "phase": args.phase,
                        "server_snapshot": "SAVED",
                        "overall_apk_api_trial": "NOT_ASSESSED",
                    }
                )
            )
        else:
            snapshots = [json.loads(p.read_text(encoding="utf-8")) for p in args.snapshots]
            print(json.dumps(compare(plan, snapshots)))
    except (
        ValueError,
        InvalidOperation,
        ImportError,
        KeyError,
        TypeError,
        RuntimeError,
        OSError,
        subprocess.SubprocessError,
    ):
        print(
            json.dumps(
                {
                    "server_observations": "UNQUALIFIED",
                    "reason": "Invalid input, unavailable observation or failed invariant",
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
