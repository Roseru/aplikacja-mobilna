"""Synthetic unit vectors only: no database, services, credentials or Android control."""

import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infra.integration.tests.native_retention_fixture import seed_worker
from infra.local.integration import native, observe


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "now", lambda: datetime(2026, 10, 29, 12, tzinfo=UTC))
    monkeypatch.setattr(native, "ROOT", tmp_path)
    state = tmp_path / ".tools/owned"
    state.mkdir(parents=True)
    helper = tmp_path / observe.HELPER
    helper.parent.mkdir(parents=True)
    helper.write_bytes(Path(observe.legacy.__file__).read_bytes())
    paths = {
        "postgres": state / "pg/postgres.exe",
        "python": state / "python/python.exe",
        "java": state / "java/bin/java.exe",
        "jar": state / "keycloak/lib/quarkus-run.jar",
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic " + name).encode())
    common = {
        "host": "172.16.0.2",
        "port": 28443,
        "origin": "https://172.16.0.2:28443",
        "project": "calorie-native-o2",
    }
    (state / "config.json").write_text(json.dumps(common))
    source = {
        "commit": "a" * 40,
        "backend_tree": "b" * 40,
        "contracts_tree": "c" * 40,
        "lock_sha256": "d" * 64,
        "packages": {"synthetic": "1"},
        "adapter_sha256": {"observe.py": observe.digest(Path(observe.__file__).read_bytes())},
        "shared_helper_sha256": {observe.HELPER: observe.digest(helper.read_bytes())},
    }
    (state / "native.json").write_text(
        json.dumps(
            common
            | {
                "format": "calorie-native/v1",
                "state": str(state),
                "source": source,
                "pg_bin": str(paths["postgres"].parent),
                "java_home": str(state / "java"),
                "python": str(paths["python"]),
                "pg_port": 28444,
            }
        )
    )
    processes = {
        name + ".process.json": {"pid": pid, "created": 1000 + pid, "executable": str(paths[exe])}
        for name, exe, pid in (
            ("postgres", "postgres", 101),
            ("keycloak", "java", 102),
            ("gateway", "python", 103),
        )
    }
    binding = {
        "state": "RUNNING",
        "generation": str(uuid4()),
        "source": source,
        "processes": processes,
    }
    for name, value in processes.items():
        (state / name).write_text(json.dumps(value))
    owned = native.Native(state)
    seed_worker(owned, binding, {"pid": 104, "created": 1104, "executable": str(paths["python"])})
    (state / "runtime-binding.json").write_text(json.dumps(binding))
    monkeypatch.setattr(native, "source", lambda pin: source)
    monkeypatch.setattr(
        native, "identity", lambda pid: next(r for r in processes.values() if r["pid"] == pid)
    )
    return native.Native(state)


@pytest.fixture
def driver(stack):
    meal = json.loads(
        (
            Path(observe.legacy.__file__).resolve().parents[2]
            / "contracts/examples/valid/meal.json"
        ).read_text(encoding="utf-8")
    )
    meal["title"] = "Private unicode Żółć 🍲"
    meal["items"][0]["nutrition_per_100"].update(protein_g=None, fat_g="0")
    op = {
        "operation_id": str(uuid4()),
        "entity_id": str(uuid4()),
        "entity_type": "meal",
        "action": "upsert",
        "base_revision": None,
        "sync_epoch": str(uuid4()),
        "payload": meal,
    }
    request = {
        "protocol_version": 1,
        "sync_epoch": op["sync_epoch"],
        "checkpoint": "synthetic-private-checkpoint",
        "operations": [op],
    }
    wire = " \r\n" + json.dumps(request, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\t "
    return {
        "trial": str(uuid4()),
        "owner": str(uuid4()),
        "driver_guard_version": 2,
        "isolation_deadline": int(observe.now().timestamp() * 1000) + 1_200_000,
        "meal": op["entity_id"],
        "operation": op["operation_id"],
        "batch": str(uuid4()),
        "request": wire,
        "hash": observe.digest(wire.encode()),
        "context": json.dumps(
            {
                "account_id": str(uuid4()),
                "generation": 2,
                "sync_epoch": op["sync_epoch"],
                "context_revision": 3,
            }
        ),
        "room": 27,
        "protected_tables": list(observe.PROTECTED),
        "protected": json.dumps({key: "0" * 64 for key in (*observe.PROTECTED, "__schema__")}),
    }


def encoded(driver):
    return json.dumps(driver, ensure_ascii=True).encode()


@pytest.fixture
def plan(stack, driver):
    return observe.prepare(stack, encoded(driver), driver["trial"])


def snapshots(plan):
    common = {
        "format": 2,
        "plan_sha256": observe.validate_plan(plan),
        "read_only": "on",
        "schema": [observe.SCHEMA],
        "epoch": plan["sync_epoch"],
        "backend_pid": 104,
        "account": {"id": plan["owner_id"], "generation": 2, "state": "active"},
    }
    c0 = common | {
        "phase": "C0",
        "observed_at": "2026-10-29T12:00:01Z",
        "meal": None,
        "items": 0,
        "meal_content": None,
        "receipt": None,
        "day": None,
        "position": None,
        "tables": {t: {"count": 0, "sha256": "a" * 64} for t in observe.legacy.TABLES},
    }
    c1 = common | {
        "phase": "C1",
        "observed_at": "2026-10-29T12:00:02Z",
        "meal": {
            "id": plan["entity_id"],
            "revision": 1,
            "local_date": plan["local_date"],
            "deleted": False,
        },
        "items": plan["item_count"],
        "meal_content": deepcopy(plan["expected_meal"]),
        "day": {"id": str(uuid4()), "revision": 1, "deleted": False},
        "position": 2,
        "receipt": {
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
        },
        "tables": {
            t: {
                "count": 2
                if t == "sync_changes"
                else plan["item_count"]
                if t == "meal_items"
                else 1,
                "sha256": "b" * 64,
            }
            for t in observe.legacy.TABLES
        },
    }
    c2 = deepcopy(c1) | {"phase": "C2", "observed_at": "2026-10-29T12:00:03Z"}
    server = {
        "server_version_num": 170006,
        "address": "127.0.0.1",
        "port": 28444,
        "database": "calorie_app",
        "user": "calorie_app_migrator",
        "postmaster_started_at": "2026-10-29T11:00:00Z",
        "read_only": "on",
        "isolation": "repeatable read",
        "foreign_tables": {t: {"count": 1, "sha256": "c" * 64} for t in observe.legacy.TABLES},
        "unchanged_tables": {t: {"count": 1, "sha256": "d" * 64} for t in observe.UNCHANGED},
    }
    return [
        {
            "format": observe.CAPTURE_FORMAT,
            "runtime": deepcopy(plan["runtime"]),
            "database": data,
            "server": deepcopy(server),
        }
        for data in (c0, c1, c2)
    ]


def test_room27_plan_preserves_wire_ids_utf8_hash_lf_and_no_checkpoint(stack, driver, plan):
    from calorie_app.modules.catalog.validation import canonical_json

    op = json.loads(driver["request"])["operations"][0]
    assert canonical_json(op).endswith(b"\n")
    assert plan["operation_sha256"] == hashlib.sha256(canonical_json(op)).hexdigest()
    assert plan["operation_sha256"] != hashlib.sha256(canonical_json(op).rstrip(b"\n")).hexdigest()
    assert plan["owner_id"] == json.loads(driver["context"])["account_id"] != driver["owner"]
    assert plan["entity_id"] == op["entity_id"] and plan["operation_id"] == op["operation_id"]
    assert plan["expected_meal"] == op["payload"]
    assert plan["envelope_sha256"] == observe.digest(driver["request"].encode())
    assert plan["driver"]["prepared_sha256"] == observe.digest(encoded(driver))
    assert len(observe.PROTECTED) == 45 and len(set(observe.PROTECTED)) == 45
    assert "checkpoint" not in json.dumps(plan) and "api_image" not in json.dumps(plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("room", 23),
        ("room", "27"),
        ("room", True),
        ("driver_guard_version", 1),
        ("trial", str(uuid4())),
        ("meal", str(uuid4())),
        ("operation", str(uuid4())),
        ("hash", "f" * 64),
        ("protected_tables", []),
        ("protected", "{}"),
        ("isolation_deadline", 1),
        ("owner", "not-a-uuid"),
    ],
)
def test_driver_changes_refused_without_query(stack, driver, field, value, monkeypatch):
    driver[field] = value
    monkeypatch.setattr(
        observe, "query", lambda *args: pytest.fail("query during plan preparation")
    )
    with pytest.raises((ValueError, TypeError)):
        observe.prepare(
            stack, encoded(driver), driver["trial"] if field != "trial" else str(uuid4())
        )


@pytest.mark.parametrize(
    "fault", ["update", "epoch", "many", "recovery", "invalid_payload", "duplicate_json"]
)
def test_only_one_canonical_create_accepted(stack, driver, fault):
    request = json.loads(driver["request"])
    op = request["operations"][0]
    if fault == "update":
        op["base_revision"] = 1
    elif fault == "epoch":
        op["sync_epoch"] = str(uuid4())
    elif fault == "many":
        request["operations"].append(
            deepcopy(op) | {"operation_id": str(uuid4()), "entity_id": str(uuid4())}
        )
    elif fault == "recovery":
        op["recovery"] = {"source_epoch": str(uuid4()), "source_entity_id": str(uuid4())}
    elif fault == "invalid_payload":
        op["payload"]["items"][0]["quantity"]["amount"] = 1.5
    driver["request"] = json.dumps(request)
    if fault == "duplicate_json":
        driver["request"] = '{"protocol_version":1,' + driver["request"][1:]
    driver["hash"] = observe.digest(driver["request"].encode())
    with pytest.raises(ValueError):
        observe.prepare(stack, encoded(driver), driver["trial"])


@pytest.mark.parametrize(
    "damage",
    ["source", "process", "stopped", "missing", "binary", "helper", "static", "generation"],
)
def test_real_native_admission_refuses_stale_before_query(stack, plan, monkeypatch, damage):
    if damage == "source":
        monkeypatch.setattr(native, "source", lambda pin: {})
    elif damage == "process":
        monkeypatch.setattr(native, "identity", lambda pid: {"pid": pid, "created": 0})
    elif damage == "missing":
        (stack.state / "gateway.process.json").unlink()
    elif damage == "binary":
        (stack.pg / "postgres.exe").write_bytes(b"changed binary")
    elif damage == "helper":
        (native.ROOT / observe.HELPER).write_bytes(b"changed helper")
    elif damage == "static":
        (stack.state / "runtime-binding.json").write_text('{"result":"PASS"}')
    else:
        binding = json.loads((stack.state / "runtime-binding.json").read_text())
        binding["state" if damage == "stopped" else "generation"] = (
            "STOPPED" if damage == "stopped" else str(uuid4())
        )
        (stack.state / "runtime-binding.json").write_text(json.dumps(binding))
    monkeypatch.setattr(
        observe, "query", lambda *args: pytest.fail("query before native admission")
    )
    with pytest.raises((ValueError, KeyError, FileNotFoundError)):
        observe.capture(stack, plan, "C0")


def test_capture_qualifies_before_and_after_query(stack, plan, monkeypatch):
    expected = snapshots(plan)[0]
    calls = []
    original = stack.require_running

    def running():
        calls.append("admit")
        return original()

    def query(*args):
        calls.append("query")
        return expected["database"], expected["server"]

    monkeypatch.setattr(stack, "require_running", running)
    monkeypatch.setattr(observe, "query", query)
    assert observe.capture(stack, plan, "C0") == expected
    assert calls == ["admit", "admit", "query", "admit", "admit"]


def test_change_during_query_cannot_make_capture(stack, plan, monkeypatch):
    expected = snapshots(plan)[0]

    def query(*args):
        (stack.pg / "postgres.exe").write_bytes(b"changed during read")
        return expected["database"], expected["server"]

    monkeypatch.setattr(observe, "query", query)
    with pytest.raises(ValueError, match="binaries"):
        observe.capture(stack, plan, "C0")


def test_sql_keeps_one_repeatable_read_read_only_snapshot_with_foreign_hashes(plan):
    sql = observe.observation_sql(plan, "C0")
    assert sql.count("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;") == 1
    assert sql.count("ROLLBACK;") == 1 and sql.rstrip().endswith("ROLLBACK;")
    assert sql.count("\nSELECT jsonb_build_object(") == 2
    assert "'foreign_tables'" in sql and "statement_timeout = '5s'" in sql
    assert all(f"FROM app.{table} t WHERE owner_id<>" in sql for table in observe.legacy.TABLES)
    assert all(f"FROM app.{table} t WHERE owner_id=" in sql for table in observe.UNCHANGED)
    assert "api_image" not in sql and "INSERT " not in sql and "UPDATE " not in sql
    with pytest.raises(ValueError):
        observe.observation_sql(plan | {"owner_id": "'; DELETE FROM app.meals;--"}, "C0")


def test_pg_connection_is_explicit_read_only_from_start_and_reads_both_sets(
    stack, plan, monkeypatch
):
    import psycopg

    expected = snapshots(plan)[0]
    calls = []

    class Cursor:
        index = 0
        sets = [None, None, expected["database"], expected["server"], None]

        @property
        def description(self):
            return None if self.sets[self.index] is None else [("json",)]

        def execute(self, sql, *, prepare):
            assert sql == observe.observation_sql(plan, "C0") and prepare is False

        def fetchall(self):
            return [(self.sets[self.index],)]

        def nextset(self):
            self.index += 1
            return self.index < len(self.sets)

    cursor = Cursor()

    def connect(**kwargs):
        calls.append(kwargs)
        return nullcontext(SimpleNamespace(cursor=lambda: nullcontext(cursor)))

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(
        stack,
        "env",
        lambda name: {
            "DATABASE_URL": "postgresql+psycopg://calorie_app_migrator:synthetic@127.0.0.1:28444/calorie_app"
        },
    )
    assert observe.query(stack, observe.observation_sql(plan, "C0")) == [
        expected["database"],
        expected["server"],
    ]
    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 28444
    assert calls[0]["user"] == "calorie_app_migrator" and calls[0]["dbname"] == "calorie_app"
    assert calls[0]["autocommit"] is True and calls[0]["sslmode"] == "disable"
    assert "default_transaction_read_only=on" in calls[0]["options"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://postgres:synthetic@127.0.0.1:28444/calorie_app",
        "postgresql+psycopg://calorie_app_migrator:synthetic@other:28444/calorie_app",
        "postgresql+psycopg://calorie_app_migrator:synthetic@127.0.0.1:5432/calorie_app",
        "postgresql+psycopg://calorie_app_migrator:synthetic@127.0.0.1:28444/keycloak",
        "postgresql+psycopg://calorie_app_migrator@127.0.0.1:28444/calorie_app",
        "postgresql+psycopg://calorie_app_migrator:synthetic@127.0.0.1:28444/calorie_app?options=unsafe",
    ],
)
def test_foreign_or_incomplete_dsn_never_connects(stack, monkeypatch, url):
    import psycopg

    monkeypatch.setattr(stack, "env", lambda name: {"DATABASE_URL": url})
    monkeypatch.setattr(
        psycopg, "connect", lambda **kwargs: pytest.fail("foreign database connection")
    )
    with pytest.raises(ValueError, match="loopback"):
        observe.query(stack, "unused")


def test_old_runtime_without_helper_binding_cannot_prepare(stack, driver):
    source = native.source("a" * 40)
    source["shared_helper_sha256"].pop(observe.HELPER)
    path = stack.state / "runtime-binding.json"
    binding = json.loads(path.read_text())
    binding["source"] = source
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="helper is not bound"):
        observe.prepare(stack, encoded(driver), driver["trial"])


def test_success_is_server_only_and_preserves_null_zero(stack, plan):
    result = observe.compare(stack, plan, snapshots(plan))
    assert result["server_observations"] == "PASS" and result["full_user_flow"] is False
    assert result["release_authorized"] is False and "REAL_KILL" in result["overall_apk_api_trial"]


@pytest.mark.parametrize("table", ["weights", "user_profiles", "goal_versions"])
def test_other_domain_hash_change_is_rejected_even_with_unchanged_count(stack, plan, table):
    values = snapshots(plan)
    assert values[0]["server"]["unchanged_tables"][table]["count"] == 1
    values[1]["server"]["unchanged_tables"][table]["sha256"] = "e" * 64
    assert values[1]["server"]["unchanged_tables"][table]["count"] == 1
    with pytest.raises(ValueError, match="unchanged tables"):
        observe.compare(stack, plan, values)


@pytest.mark.parametrize(
    "part,key,value",
    [
        ("database", "schema", ["0021_e8_nemesis_results"]),
        ("database", "epoch", str(uuid4())),
        ("database", "phase", "PUSH"),
        ("database", "read_only", "off"),
        ("server", "port", 5555),
        ("server", "server_version_num", 180000),
        ("server", "isolation", "read committed"),
    ],
)
def test_database_identity_changes_cannot_pass(stack, plan, part, key, value):
    values = snapshots(plan)
    values[1][part][key] = value
    with pytest.raises(ValueError):
        observe.compare(stack, plan, values)


@pytest.mark.parametrize(
    "damage",
    [
        "c0_present",
        "receipt_hash",
        "duplicate",
        "foreign",
        "timestamp",
        "null_zero",
        "item_id",
        "content_time",
        "no_c2",
        "push_only",
        "retroactive_plan",
    ],
)
def test_witnesses_not_just_push_are_required(stack, plan, damage):
    values = snapshots(plan)
    if damage == "c0_present":
        values[0]["database"]["meal"] = values[1]["database"]["meal"]
    elif damage == "receipt_hash":
        values[1]["database"]["receipt"]["request_hash"] = "f" * 64
    elif damage == "duplicate":
        values[2]["database"]["tables"]["meals"]["count"] += 1
    elif damage == "foreign":
        values[1]["server"]["foreign_tables"]["meals"]["sha256"] = "f" * 64
    elif damage == "timestamp":
        values[2]["database"]["observed_at"] = values[0]["database"]["observed_at"]
    elif damage in {"null_zero", "item_id", "content_time"}:
        for snapshot in values[1:]:
            meal = snapshot["database"]["meal_content"]
            if damage == "null_zero":
                meal["items"][0]["nutrition_per_100"]["protein_g"] = "0"
            elif damage == "item_id":
                meal["items"][0]["item_id"] = str(uuid4())
            else:
                meal["occurred_at"] = "2026-10-20T08:00:01Z"
    elif damage == "no_c2":
        values.pop()
    elif damage == "push_only":
        values = [{"result": "PASS", "status": "already_applied"}] * 3
    else:
        plan["expected_meal"]["title"] = "retroactive expectation"
    with pytest.raises((ValueError, KeyError)):
        observe.compare(stack, plan, values)


def test_expired_or_clock_rollback_trial_refused_before_query(stack, plan, monkeypatch):
    monkeypatch.setattr(observe, "query", lambda *args: pytest.fail("query after expiry"))
    for clock in (
        datetime(2026, 10, 29, 12, 20, tzinfo=UTC),
        datetime(2026, 10, 29, 11, 59, tzinfo=UTC),
    ):
        monkeypatch.setattr(observe, "now", lambda clock=clock: clock)
        with pytest.raises(ValueError, match="expired|clock"):
            observe.capture(stack, plan, "C0")


def test_legacy_public_sql_always_checks_legacy_plan(plan, monkeypatch):
    def refuse(value):
        assert value is plan
        raise ValueError("legacy qualifier called")

    monkeypatch.setattr(observe.legacy, "validate_plan", refuse)
    monkeypatch.setattr(
        observe.legacy, "_observation_sql", lambda *args: pytest.fail("legacy qualifier bypassed")
    )
    with pytest.raises(ValueError, match="legacy qualifier called"):
        observe.legacy.observation_sql(plan, "C0")


def test_new_native_plan_is_not_a_relaxed_legacy_plan(plan):
    with pytest.raises(ValueError, match="fields"):
        observe.legacy.observation_sql(plan, "C0")


def test_outputs_are_exclusive_and_existing_file_refused_before_query(
    stack, tmp_path, monkeypatch, capsys
):
    output = stack.state / "existing.json"
    output.write_text("original private evidence")
    monkeypatch.setattr(observe.native, "Native", lambda state: stack)
    monkeypatch.setattr(
        observe, "capture", lambda *args: pytest.fail("capture before exclusive output check")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observe",
            "--state",
            str(stack.state),
            "capture",
            "--plan",
            "unused",
            "--phase",
            "C0",
            "--output",
            str(output),
        ],
    )
    assert observe.main() == 1 and output.read_text() == "original private evidence"
    assert "original private evidence" not in capsys.readouterr().err
    with pytest.raises(ValueError):
        observe.output_path(stack, tmp_path / "outside.json")
    fresh = observe.output_path(stack, stack.state / "new.json")
    observe.save(fresh, {"private": "preserved"})
    with pytest.raises(FileExistsError):
        observe.save(fresh, {"private": "overwritten"})


def test_cli_help_imports_in_a_fresh_interpreter():
    environment = native.clean_env() | {
        "PYTHONPATH": os_path(native.ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-B", "-m", "infra.local.integration.observe", "--help"],
        cwd=native.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        **native.FLAGS,
    )
    assert result.returncode == 0 and "prepare" in result.stdout and "capture" in result.stdout


def os_path(root):
    import os

    return os.pathsep.join((str(root), str(root / "backend/src")))
