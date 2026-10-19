"""Bounded read-only PostgreSQL observations for the single-Meal E4 replay trial."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import date, datetime
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
}


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
        ("expected_api_image", r"sha256:[0-9a-f]{64}"),
        ("expected_schema", r"[a-z0-9_]{1,64}"),
    ):
        if not isinstance(plan[key], str) or not re.fullmatch(pattern, plan[key]):
            raise ValueError("Invalid expected identity or hash")
    if type(plan["item_count"]) is not int or not 1 <= plan["item_count"] <= 100:
        raise ValueError("Plan requires 1..100 meal items")
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def observation_sql(plan, phase):
    plan_hash = validate_plan(plan)
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
 'format', 1, 'phase', '{phase}', 'plan_sha256', '{plan_hash}',
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
            snapshot["format"] != 1
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
    for key in ("meal", "items", "day", "receipt", "position", "tables"):
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
    save = sub.add_parser("capture")
    save.add_argument("--settings", type=Path, required=True)
    save.add_argument("--phase", choices=("C0", "C1", "C2"), required=True)
    save.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("compare")
    check.add_argument("snapshots", type=Path, nargs=3)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        if args.action == "capture":
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
