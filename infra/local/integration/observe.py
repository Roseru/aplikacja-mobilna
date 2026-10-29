"""Read-only server witnesses for a new Room27 single-Meal replay trial.

No APK/barrier/kill/PULL verdict, token access, request replay or lifecycle control.
Outputs must be new files inside the operator's ACL-private native state.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from infra.integration import e4_observer as legacy
from infra.local.integration import native

PLAN_FORMAT = "calorie-native-meal-plan/v1"
CAPTURE_FORMAT = "calorie-native-meal-capture/v1"
SCHEMA = "0026_ledger_review"
HELPER = "infra/integration/e4_observer.py"
UNCHANGED = (
    "weights",
    "user_profiles",
    "goal_versions",
    "goal_timelines",
    "user_consents",
    "product_drafts",
)
PROTECTED = (
    "products",
    "meals",
    "meal_items",
    "goals",
    "outbox",
    "rations",
    "ration_components",
    "profiles",
    "weights",
    "diary_days",
    "catalog_generations",
    "catalog_records",
    "catalog_members",
    "catalog_active",
    "meal_photo_drafts",
    "photo_analysis_requests",
    "photo_materializations",
    "photo_confirmation_history",
    "sync_push_batches",
    "canonical_weights",
    "sync_conflict_decisions",
    "canonical_domains",
    "canonical_goal_timelines",
    "import_plans",
    "guest_assignments",
    "import_sources",
    "import_identities",
    "import_item_identities",
    "import_decisions",
    "reconciliation_batches",
    "reconciliation_evidence",
    "reconciliation_pulls",
    "import_origins",
    "snapshot_archive_receipts",
    "sync_work_state",
    "reconciliation_completions",
    "community_cache",
    "community_attempts",
    "community_backoff",
    "energy_cache",
    "energy_attempts",
    "energy_backoff",
    "sync_protocol_states",
    "canonical_energy_versions",
    "private_preview_cache",
)
PLAN_FIELDS = {
    "format",
    "created_at",
    "trial_id",
    "owner_id",
    "account_generation",
    "context_revision",
    "operation_id",
    "entity_id",
    "sync_epoch",
    "local_date",
    "item_count",
    "expected_schema",
    "operation_sha256",
    "envelope_sha256",
    "expected_meal",
    "driver",
    "runtime",
}


def now():
    return datetime.now(UTC)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_digest(value):
    return digest(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    )


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Canonical UUID required")


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("SHA256 required")


def positive(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Positive integer required")


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Offset required")
    return result


def read_json(path, limit=5_000_000):
    from calorie_app.modules.catalog.validation import parse_json

    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if not 1 <= len(raw) <= limit:
        raise ValueError("Evidence size refused")
    return parse_json(raw)


def runtime(stack):
    """Qualify live PID births/executables and the pinned source, never a PASS file."""
    binding = stack.require_running()
    if binding.get("state") != "RUNNING":
        raise ValueError("Qualified running generation required")
    uuid(binding["generation"])
    source = binding["source"]
    if source.get("shared_helper_sha256", {}).get(HELPER) != digest(
        (native.ROOT / HELPER).read_bytes()
    ):
        raise ValueError("Observer helper is not bound to the running source")
    if source.get("adapter_sha256", {}).get("observe.py") != digest(Path(__file__).read_bytes()):
        raise ValueError("Native observer is not bound to the running source")
    paths = {
        "postgres": stack.pg / "postgres.exe",
        "java": Path(stack.config["java_home"]) / "bin/java.exe",
        "python": Path(stack.config["python"]),
        "keycloak_bootstrap": stack.state / "keycloak/lib/quarkus-run.jar",
    }
    if set(binding["processes"]) != {
        "postgres.process.json",
        "keycloak.process.json",
        "gateway.process.json",
        "worker.process.json",
    }:
        raise ValueError("Exact owned processes required")
    for name, record in binding["processes"].items():
        if set(record) != {"pid", "created", "executable"}:
            raise ValueError("Exact process identity required")
        positive(record["pid"])
        positive(record["created"])
        paths["process:" + name] = Path(record["executable"])
    if (
        paths["process:postgres.process.json"].resolve() != paths["postgres"].resolve()
        or (paths["process:gateway.process.json"].resolve() != paths["python"].resolve())
        or (paths["process:worker.process.json"].resolve() != paths["python"].resolve())
    ):
        raise ValueError("Configured runtime and process executables differ")
    binaries = {name: digest(path.read_bytes()) for name, path in paths.items()}
    if stack.require_running() != binding:
        raise ValueError("Runtime changed during admission")
    return deepcopy(
        {
            "state": str(stack.state),
            "origin": stack.origin,
            "pg_port": stack.config["pg_port"],
            "generation": binding["generation"],
            "binding_sha256": json_digest(binding),
            "source": source,
            "processes": binding["processes"],
            "binary_sha256": binaries,
        }
    )


def operation(plan):
    return {
        "operation_id": plan["operation_id"],
        "entity_id": plan["entity_id"],
        "sync_epoch": plan["sync_epoch"],
        "entity_type": "meal",
        "action": "upsert",
        "base_revision": None,
        "payload": plan["expected_meal"],
    }


def validate_plan(plan):
    from calorie_app.modules.diary.validation import validate_payload
    from calorie_app.modules.sync.service import fingerprint

    if (
        set(plan) != PLAN_FIELDS
        or plan["format"] != PLAN_FORMAT
        or plan["expected_schema"] != SCHEMA
    ):
        raise ValueError("Native plan format or schema refused")
    for key in ("trial_id", "owner_id", "operation_id", "entity_id", "sync_epoch"):
        uuid(plan[key])
    for key in ("account_generation", "context_revision", "item_count"):
        positive(plan[key])
    for key in ("operation_sha256", "envelope_sha256"):
        sha(plan[key])
    driver = plan["driver"]
    if (
        set(driver)
        != {
            "room",
            "guard_version",
            "batch_id",
            "local_scope",
            "isolation_deadline",
            "prepared_sha256",
            "protected_sha256",
        }
        or type(driver["room"]) is not int
        or driver["room"] != 27
        or (type(driver["guard_version"]) is not int or driver["guard_version"] != 2)
    ):
        raise ValueError("A new guard2 Room27 trial is required")
    uuid(driver["batch_id"])
    uuid(driver["local_scope"])
    sha(driver["prepared_sha256"])
    sha(driver["protected_sha256"])
    positive(driver["isolation_deadline"])
    created = instant(plan["created_at"])
    if not 0 < driver["isolation_deadline"] - int(created.timestamp() * 1000) <= 1_800_000:
        raise ValueError("Driver isolation deadline refused")
    validate_payload(plan["expected_meal"], "Meal")
    expected = legacy.meal_content(plan["expected_meal"])
    if expected["local_date"] != plan["local_date"] or len(expected["items"]) != plan["item_count"]:
        raise ValueError("Meal metadata differs from the plan")
    if fingerprint(operation(plan)) != plan["operation_sha256"]:
        raise ValueError("Canonical operation differs from the plan")
    return json_digest(plan)


def admit(stack, plan):
    validate_plan(plan)
    current = now()
    if (
        current < instant(plan["created_at"])
        or int(current.timestamp() * 1000) >= plan["driver"]["isolation_deadline"]
    ):
        raise ValueError("Trial is expired or the observer clock moved backwards")
    if runtime(stack) != plan["runtime"]:
        raise ValueError("Runtime source, binaries or process generation changed")


def prepare(stack, raw_prepared, trial):
    from calorie_app.modules.catalog.validation import parse_json
    from calorie_app.modules.sync.errors import SyncFailure
    from calorie_app.modules.sync.schemas import preflight_structure
    from calorie_app.modules.sync.service import fingerprint

    uuid(trial)
    if (
        not isinstance(raw_prepared, bytes)
        or not 1 <= len(raw_prepared) <= legacy.MAX_DRIVER_PREPARED_BYTES
    ):
        raise ValueError("Driver preparation size refused")
    prepared = parse_json(raw_prepared)
    if (
        set(prepared)
        != {
            "trial",
            "owner",
            "driver_guard_version",
            "isolation_deadline",
            "meal",
            "operation",
            "batch",
            "request",
            "hash",
            "context",
            "room",
            "protected_tables",
            "protected",
        }
        or prepared["trial"] != trial
        or prepared["protected_tables"] != list(PROTECTED)
    ):
        raise ValueError("Exact Room27 driver preparation required")
    for key in ("request", "context", "protected"):
        if not isinstance(prepared[key], str):
            raise ValueError("Driver strings required")
    protected = parse_json(prepared["protected"].encode("utf-8"))
    if set(protected) != {*PROTECTED, "__schema__"}:
        raise ValueError("Exact protected table and schema digests required")
    for value in protected.values():
        sha(value)
    raw_request = prepared["request"].encode("utf-8")
    if (
        not 1 <= len(raw_request) <= legacy.MAX_DRIVER_REQUEST_BYTES
        or digest(raw_request) != prepared["hash"]
    ):
        raise ValueError("Frozen UTF8 envelope digest differs")
    context = parse_json(prepared["context"].encode("utf-8"))
    if set(context) != {"account_id", "generation", "sync_epoch", "context_revision"}:
        raise ValueError("Exact wire account context required")
    request = parse_json(raw_request)
    try:
        preflight_structure(request)
    except SyncFailure:
        raise ValueError("Invalid frozen envelope") from None
    if len(request["operations"]) != 1:
        raise ValueError("Exactly one canonical Meal/create required")
    op = request["operations"][0]
    if (
        op["entity_type"] != "meal"
        or op["action"] != "upsert"
        or op["base_revision"] is not None
        or (
            op["sync_epoch"] != context["sync_epoch"]
            or request["sync_epoch"] != context["sync_epoch"]
            or op["entity_id"] != prepared["meal"]
            or op["operation_id"] != prepared["operation"]
        )
    ):
        raise ValueError("Driver operation/context differs from the frozen Meal/create")
    with stack.operation():
        plan = {
            "format": PLAN_FORMAT,
            "created_at": now().isoformat(),
            "trial_id": trial,
            "owner_id": context["account_id"],
            "account_generation": context["generation"],
            "context_revision": context["context_revision"],
            "operation_id": op["operation_id"],
            "entity_id": op["entity_id"],
            "sync_epoch": context["sync_epoch"],
            "local_date": op["payload"]["local_date"],
            "item_count": len(op["payload"]["items"]),
            "expected_schema": SCHEMA,
            "operation_sha256": fingerprint(op),
            "envelope_sha256": digest(raw_request),
            "expected_meal": op["payload"],
            "driver": {
                "room": prepared["room"],
                "guard_version": prepared["driver_guard_version"],
                "batch_id": prepared["batch"],
                "local_scope": prepared["owner"],
                "isolation_deadline": prepared["isolation_deadline"],
                "prepared_sha256": digest(raw_prepared),
                "protected_sha256": digest(prepared["protected"].encode("utf-8")),
            },
            "runtime": runtime(stack),
        }
        admit(stack, plan)
    return plan


def observation_sql(plan, phase):
    plan_hash = validate_plan(plan)
    sql = legacy._observation_sql(plan, phase, plan_hash)
    foreign = ", ".join(
        f"'{table}', (SELECT jsonb_build_object('count',count(*),'sha256',"
        "encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),"
        "'[]'::jsonb)::text,'UTF8')),'hex')) "
        f"FROM app.{table} t WHERE owner_id<>'{plan['owner_id']}'::uuid)"
        for table in legacy.TABLES
    )
    unchanged = ", ".join(
        f"'{table}', (SELECT jsonb_build_object('count',count(*),'sha256',"
        "encode(sha256(convert_to(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),"
        "'[]'::jsonb)::text,'UTF8')),'hex')) "
        f"FROM app.{table} t WHERE owner_id='{plan['owner_id']}'::uuid)"
        for table in UNCHANGED
    )
    if not sql.endswith("ROLLBACK;\n"):
        raise ValueError("Shared SQL transaction boundary changed")
    return (
        sql.removesuffix("ROLLBACK;\n")
        + f"""
SELECT jsonb_build_object(
 'server_version_num',current_setting('server_version_num')::integer,
 'address',host(inet_server_addr()),'port',inet_server_port(),'database',current_database(),
 'user',current_user,'postmaster_started_at',pg_postmaster_start_time(),
 'read_only',current_setting('transaction_read_only'),
 'isolation',current_setting('transaction_isolation'),
 'foreign_tables',jsonb_build_object({foreign}),
 'unchanged_tables',jsonb_build_object({unchanged})
);
ROLLBACK;
"""
    )


def query(stack, sql):
    """No inherited DSN/PG target: one explicit loopback connection, read-only from startup."""
    import psycopg
    from sqlalchemy.engine import make_url

    url = make_url(stack.env("migrate")["DATABASE_URL"])
    if (
        (url.drivername, url.host, url.port, url.database, url.username)
        != (
            "postgresql+psycopg",
            "127.0.0.1",
            stack.config["pg_port"],
            "calorie_app",
            "calorie_app_migrator",
        )
        or url.query
        or not url.password
    ):
        raise ValueError("Owned loopback migrator connection required")
    with (
        psycopg.connect(
            host="127.0.0.1",
            port=url.port,
            dbname=url.database,
            user=url.username,
            password=url.password,
            connect_timeout=5,
            sslmode="disable",
            autocommit=True,
            options=(
                "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000"
            ),
            application_name="calorie-native-read-only-observer",
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(sql, prepare=False)
        results = []
        while True:
            if cursor.description is not None:
                rows = cursor.fetchall()
                if len(rows) != 1 or len(rows[0]) != 1:
                    raise ValueError("Unexpected observation result shape")
                results.append(rows[0][0])
            if not cursor.nextset():
                break
    if len(results) != 2 or any(not isinstance(value, dict) for value in results):
        raise ValueError("Two read-only observation result sets required")
    return results


def check_capture(plan, snapshot, phase):
    if (
        set(snapshot) != {"format", "runtime", "database", "server"}
        or snapshot["format"] != CAPTURE_FORMAT
        or snapshot["runtime"] != plan["runtime"]
    ):
        raise ValueError("Native capture identity refused")
    data, server = snapshot["database"], snapshot["server"]
    if (
        data["format"] != 2
        or data["phase"] != phase
        or data["plan_sha256"] != validate_plan(plan)
        or (
            data["read_only"] != "on"
            or data["schema"] != [SCHEMA]
            or data["epoch"] != plan["sync_epoch"]
            or data["account"]
            != {"id": plan["owner_id"], "generation": plan["account_generation"], "state": "active"}
        )
    ):
        raise ValueError("Database context, account, schema or epoch differs")
    positive(data["backend_pid"])
    instant(data["observed_at"])
    if not 170000 <= server["server_version_num"] < 180000 or (
        server["address"] != "127.0.0.1"
        or server["port"] != plan["runtime"]["pg_port"]
        or server["database"] != "calorie_app"
        or server["user"] != "calorie_app_migrator"
        or server["read_only"] != "on"
        or server["isolation"] != "repeatable read"
    ):
        raise ValueError("PostgreSQL target or read-only snapshot differs")
    instant(server["postmaster_started_at"])
    for tables, expected_tables in (
        (data["tables"], legacy.TABLES),
        (server["foreign_tables"], legacy.TABLES),
        (server["unchanged_tables"], UNCHANGED),
    ):
        if set(tables) != set(expected_tables):
            raise ValueError("Exact observed table set required")
        for row in tables.values():
            if set(row) != {"count", "sha256"} or type(row["count"]) is not int or row["count"] < 0:
                raise ValueError("Invalid table aggregate")
            sha(row["sha256"])


def capture(stack, plan, phase):
    sql = observation_sql(plan, phase)
    with stack.operation():
        admit(stack, plan)
        data, server = query(stack, sql)
        admit(stack, plan)
        result = {
            "format": CAPTURE_FORMAT,
            "runtime": deepcopy(plan["runtime"]),
            "database": data,
            "server": server,
        }
        check_capture(plan, result, phase)
        return result


def compare(stack, plan, snapshots):
    """Current-generation server-only verdict. Does not infer APK or kill evidence."""
    with stack.operation():
        admit(stack, plan)
        if len(snapshots) != 3:
            raise ValueError("Require separate C0, C1 and C2")
        for snapshot, phase in zip(snapshots, ("C0", "C1", "C2"), strict=True):
            check_capture(plan, snapshot, phase)
        c0, c1, c2 = [s["database"] for s in snapshots]
        times = [instant(s["observed_at"]) for s in (c0, c1, c2)]
        if not times[0] < times[1] < times[2] or any(
            s["server"] != snapshots[0]["server"] for s in snapshots
        ):
            raise ValueError(
                "Observation order, PostgreSQL identity, foreign or unchanged tables changed"
            )
        if (
            c0["meal"] is not None
            or c0["receipt"] is not None
            or c0["items"] != 0
            or c0["meal_content"] is not None
        ):
            raise ValueError("C0 must precede the selected target and receipt")
        if (
            c1["meal"]
            != {
                "id": plan["entity_id"],
                "revision": 1,
                "local_date": plan["local_date"],
                "deleted": False,
            }
            or c1["items"] != plan["item_count"]
        ):
            raise ValueError("C1 does not contain the exact committed Meal")
        expected_receipt = {
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
        if c1["receipt"] != expected_receipt or legacy.meal_content(
            c1["meal_content"]
        ) != legacy.meal_content(plan["expected_meal"]):
            raise ValueError("C1 receipt or Meal content differs from the original operation")
        if (
            c1["day"] is None
            or c1["day"]["deleted"]
            or (c0["day"] is not None and c0["day"] != c1["day"])
        ):
            raise ValueError("C1 DiaryDay missing or an existing day changed")
        new_day = int(c0["day"] is None)
        deltas = {
            "meals": 1,
            "meal_items": plan["item_count"],
            "diary_days": new_day,
            "sync_receipts": 1,
            "sync_changes": 1 + new_day,
            "sync_counters": int(c0["position"] is None),
        }
        if (
            any(
                c1["tables"][table]["count"] - c0["tables"][table]["count"] != delta
                for table, delta in deltas.items()
            )
            or c1["position"] - (c0["position"] or 0) != 1 + new_day
        ):
            raise ValueError("C0 to C1 is not exactly one selected commit")
        if any(
            c2[key] != c1[key]
            for key in ("meal", "items", "meal_content", "day", "receipt", "position", "tables")
        ):
            raise ValueError("Replay changed committed server state")
        admit(stack, plan)
        return {
            "format": "calorie-native-meal-verdict/v1",
            "server_observations": "PASS",
            "trial_id": plan["trial_id"],
            "plan_sha256": validate_plan(plan),
            "runtime_generation": plan["runtime"]["generation"],
            "overall_apk_api_trial": (
                "REQUIRES_SEPARATE_HTTP_ROOM_BARRIER_REAL_KILL_AND_PULL_EVIDENCE"
            ),
            "full_user_flow": False,
            "release_authorized": False,
        }


def output_path(stack, path):
    path = native.confined(path)
    if not path.is_relative_to(stack.state) or not path.parent.is_dir() or path.exists():
        raise ValueError("New output inside the ACL-private native state required")
    return path


def save(path, value):
    # Windows inherits the operator's private state ACL; POSIX additionally uses0600.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    plan = sub.add_parser("prepare")
    plan.add_argument("--driver-prepared", type=Path, required=True)
    plan.add_argument("--trial", required=True)
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--plan", type=Path, required=True)
    capture_parser.add_argument("--phase", choices=("C0", "C1", "C2"), required=True)
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--plan", type=Path, required=True)
    compare_parser.add_argument("snapshots", type=Path, nargs=3)
    for command in (plan, capture_parser, compare_parser):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        stack = native.Native(args.state)
        destination = output_path(stack, args.output)
        if args.action == "prepare":
            with args.driver_prepared.open("rb") as stream:
                raw = stream.read(legacy.MAX_DRIVER_PREPARED_BYTES + 1)
            result = prepare(stack, raw, args.trial)
        elif args.action == "capture":
            result = capture(stack, read_json(args.plan), args.phase)
        else:
            result = compare(stack, read_json(args.plan), [read_json(p) for p in args.snapshots])
        save(destination, result)
        print(
            json.dumps(
                {
                    "action": args.action,
                    "server_observations": "PASS"
                    if args.action == "compare"
                    else "SAVED_NOT_A_VERDICT",
                    "full_user_flow": False,
                }
            )
        )
        return 0
    except Exception:
        print(
            "Native observation refused; private inputs and database output withheld",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
