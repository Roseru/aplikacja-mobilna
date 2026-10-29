"""D1 safety contracts on synthetic files/command boundaries, never real services."""

import importlib.util
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infra.local.integration import native_existing as e


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(e.native, "ROOT", tmp_path)
    source_code = {"commit": "e" * 40, "backend_tree": "unchanged"}
    monkeypatch.setattr(e.native, "source", lambda _pin: source_code)
    monkeypatch.setattr(e.native, "available", lambda *_args: None)
    monkeypatch.setattr(e, "ready", lambda _stack: None)
    monkeypatch.setattr(e, "private_directory", lambda p: p.mkdir(parents=True))
    monkeypatch.setattr(e.restore, "private_directory", lambda p: p.mkdir(parents=True))
    w = SimpleNamespace(
        root=tmp_path,
        code=source_code,
        live={},
        events=[],
        facts={},
        next_pid=100,
        clients=0,
        locks=0,
    )
    bin_path = tmp_path / "pg17"
    bin_path.mkdir()
    for name in e.PG_TOOLS:
        (bin_path / (name + ".exe")).write_bytes(name.encode())
    java = tmp_path / "java/bin"
    java.mkdir(parents=True)
    (java / "java.exe").write_bytes(b"synthetic java executable identity")
    w.pg = bin_path

    def identity(pid):
        if pid not in w.live:
            raise ProcessLookupError
        return w.live[pid]

    def process(exe):
        w.next_pid += 1
        record = {"pid": w.next_pid, "created": 100000 + w.next_pid, "executable": str(exe)}
        w.live[record["pid"]] = record
        return record

    def sql(pg, database, statement):
        if "pg_stat_activity" in statement:
            return str(w.clients)
        if "pg_reload_conf" in statement:
            w.events.append(("reload", pg.state))
            return "t"
        if "json_build_object('data'" in statement:
            return json.dumps(w.facts[pg.state])
        if "FROM app.deletion_ledger_source" in statement:
            return json.dumps(w.ledger)
        if statement == "SELECT sync_epoch FROM app.installation_state;":
            return w.facts[pg.state]["epoch"]
        if "SELECT version_num" in statement:
            return e.restore.EXPECTED_REVISION
        if "count(*)" in statement:
            return "2"
        if statement in e.restore.FINGERPRINTS.values():
            return "[]"
        raise AssertionError("Unspecified synthetic SQL boundary")

    def terminate(record):
        assert w.live.pop(record["pid"]) == record
        w.events.append(("stop-service", record["pid"]))

    def launch(stack, name, arguments, env):
        assert "--import-realm" not in arguments
        record = process(Path(stack.python) if name == "gateway" else tmp_path / "cmd.exe")
        e.native.write_json(stack.state / (name + ".process.json"), record)
        w.events.append(("launch", name, list(map(str, arguments)), dict(env)))
        return SimpleNamespace(pid=record["pid"])

    def run(stack, arguments, **kwargs):
        arguments = list(map(str, arguments))
        assert Path(arguments[0]).name == "pg_ctl.exe"
        assert "initdb" not in arguments and "alembic" not in arguments
        if arguments[-1] == "start":
            record = process(stack.pg / "postgres.exe")
            (stack.state / "postgres/postmaster.pid").write_text(
                f"{record['pid']}\n{stack.state / 'postgres'}\n0\n{stack.config['pg_port']}\n"
            )
            w.events.append(("pg-start", stack.state))
        else:
            assert arguments[-1] == "stop"
            pid = int((stack.state / "postgres/postmaster.pid").read_text().splitlines()[0])
            w.live.pop(pid)
            (stack.state / "postgres/postmaster.pid").unlink()
            w.events.append(("pg-stop", stack.state))
        result = "synthetic checked command success"
        (stack.state / (kwargs.get("label", "command") + ".log")).write_bytes(result.encode())
        return result

    original_lock = e.native.Native.operation

    @contextmanager
    def operation(stack):
        w.locks += 1
        with original_lock(stack):
            yield

    monkeypatch.setattr(e.native, "identity", identity)
    monkeypatch.setattr(e.native, "terminate", terminate)
    monkeypatch.setattr(e.native.Native, "launch", launch)
    monkeypatch.setattr(e.native.Native, "run", run)
    monkeypatch.setattr(e.native.Native, "operation", operation)
    monkeypatch.setattr(e.native.Native, "up", lambda *_a, **_k: pytest.fail("Forbidden native.up"))
    monkeypatch.setattr(
        e.native, "prepare", lambda *_a, **_k: pytest.fail("Forbidden native.prepare")
    )
    monkeypatch.setattr(e.NativePG, "sql", sql)
    monkeypatch.setattr(e.restore.OwnedPG, "sql", sql)
    monkeypatch.setattr(e.native.Native, "sql", lambda s, db, q: sql(s, db, q))
    monkeypatch.setattr(e, "execute", lambda *_a, **_k: pytest.fail("Unexpected external command"))

    def make_state(name="source", *, target=False):
        state = tmp_path / ".tools" / name
        (state / "postgres/global").mkdir(parents=True)
        (state / "postgres/PG_VERSION").write_text("17\n")
        (state / "postgres/global/pg_control").write_bytes(b"ID123456control fixture")
        (state / "postgres/pg_hba.conf").write_bytes(b"host all all 127.0.0.1/32 scram-sha-256\r\n")
        config = {
            "format": "calorie-native/v1",
            "state": str(state),
            "host": "172.16.0.2",
            "port": 25443,
            "origin": "https://172.16.0.2:25443",
            "project": "calorie-native-o2",
            "pg_port": 25432 if not target else 25433,
            "pg_bin": str(bin_path),
            "python": sys.executable,
            "java_home": str(java.parent),
            "source": source_code,
        }
        config.update(keycloak_port=25080, management_port=25090)
        e.native.write_json(state / "native.json", config)
        e.native.write_json(
            state / "config.json", {k: config[k] for k in ("host", "port", "origin", "project")}
        )
        for filename, raw in {
            "postgres.env": b"POSTGRES_PASSWORD="
            + b"a" * 64
            + b"\nAPP_API_PASSWORD=restored-api\n",
            "api.env": (
                "AI_PROVIDER=mock\nCATALOG_PAGE_TOKEN_SECRET="
                + "c" * 64
                + "\nCATALOG_ARTIFACT_ROOT="
                + (state / "catalog").as_posix()
                + "\nOIDC_CA_BUNDLE="
                + (state / "tls/ca.pem").as_posix()
                + "\nDATABASE_URL=postgresql+psycopg://calorie_app_api:restored-api@127.0.0.1:25432/calorie_app\n"
            ).encode(),
            "migrate.env": b"DATABASE_URL=postgresql+psycopg://calorie_app_migrator:restored@127.0.0.1:25432/calorie_app\n",
            "worker.env": b"DATABASE_URL=postgresql+psycopg://calorie_app_worker:restored@127.0.0.1:25432/calorie_app\n",
            "keycloak.env": b"KC_DB_URL=jdbc:postgresql://127.0.0.1:25432/keycloak\nKC_DB_PASSWORD=restored-kc\n",
            "credentials.json": b'{"fixture":"no real credentials"}',
            "tls/ca.pem": b"same CA",
            "tls/server.pem": b"same certificate",
            "tls/server.key": b"synthetic leaf key",
            "keycloak/lib/quarkus-run.jar": b"same bootstrap",
            "keycloak/bin/kc.bat": b"synthetic launcher",
            "catalog/manifest.json": b"{}",
        }.items():
            path = state / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        pg_record = process(bin_path / "postgres.exe")
        (state / "postgres/postmaster.pid").write_text(
            f"{pg_record['pid']}\n{state / 'postgres'}\n0\n{config['pg_port']}\n"
        )
        stack = e.native.Native(state)
        records = {
            "postgres.process.json": pg_record,
            "gateway.process.json": process(Path(sys.executable)),
            "keycloak.process.json": process(tmp_path / "cmd.exe"),
        }
        for key, value in records.items():
            e.native.write_json(state / key, value)
        generation = str(uuid4())
        binding = {
            "generation": generation,
            "state": "RUNNING",
            "source": source_code,
            "configuration": {},
            "processes": records,
            "binary_sha256": e.runtime_binaries(stack),
            "configuration_files": {k: e.sha(v) for k, v in e.cohort(stack).items()},
            "lifecycle": {
                "kind": "source",
                "generation": generation,
                "original_hba_hex": (state / "postgres/pg_hba.conf").read_bytes().hex(),
                "capture_sha256": None,
                "parent_handoff": None,
            },
        }
        e.native.write_json(state / "runtime-binding.json", binding)
        w.facts[state] = {
            "data": str(state / "postgres"),
            "port": config["pg_port"],
            "listen": "127.0.0.1",
            "address": "127.0.0.1/32",
            "user": "postgres",
            "epoch": str(uuid4()),
            "revision": e.restore.EXPECTED_REVISION,
            "sessions": 0,
            "ai": not target,
            "nemesis": False,
            "closed_at": "synthetic-clock-fixture" if target else None,
        }
        return stack

    w.make_state, w.process, w.sql = make_state, process, sql
    w.source = make_state()
    w.ledger = {
        k: str(uuid4()) for k in ("installation_id", "stream_id", "anchor_id", "receiver_id")
    }
    w.ledger.update(issuer=w.source.origin + "/realms/calorie-dev", sequence=0, chain_hash="0" * 64)
    w.code_sha = e.sha(json.dumps(source_code, sort_keys=True, separators=(",", ":")).encode())
    return w


def load(path):
    return json.loads(Path(path).read_bytes())


def captured(world, monkeypatch):
    def dump(pg, name, _args, **kwargs):
        assert name in {"pg_dump", "pg_dumpall"}
        kwargs["output_path"].write_bytes(
            b"CREATE ROLE postgres;\n" if name == "pg_dumpall" else b"synthetic dump"
        )
        world.events.append(("dump", name))

    monkeypatch.setattr(e.NativePG, "command", dump)
    generation = load(world.source.state / "runtime-binding.json")["generation"]
    return e.capture_native(world.source.state, generation, world.root / ".tools/archive")


def test_native_capture_one_lock_no_owner_and_separate_ledger_identity(world, monkeypatch):
    original_hba = (world.source.state / "postgres/pg_hba.conf").read_bytes()
    result = captured(world, monkeypatch)
    assert world.locks == 1
    assert not (world.source.state / "owner.json").exists()
    assert result["capture"]["source_owner"] != world.ledger["installation_id"]
    assert result["capture"]["ledger_backup"]["installation_id"] == world.ledger["installation_id"]
    handoff = load(result["handoff"]["path"])
    assert bytes.fromhex(handoff["original_hba_hex"]) == original_hba
    assert (world.source.state / "postgres/pg_hba.conf").read_bytes() == e.SEALED_HBA
    assert load(world.source.state / "runtime-binding.json")["state"] == "CAPTURE_SEALED"


def test_resume_source_restores_exact_hba_without_pg_restart(world, monkeypatch):
    result = captured(world, monkeypatch)
    world.events.clear()
    started = e.start_existing(
        world.source.state,
        handoff_path=result["handoff"]["path"],
        handoff_sha256=result["handoff"]["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    assert started["phase"] == "MAINTENANCE" and not started["pg_started"]
    assert not any(event[0] == "pg-start" for event in world.events)
    assert (world.source.state / "postgres/pg_hba.conf").read_bytes() == bytes.fromhex(
        load(result["handoff"]["path"])["original_hba_hex"]
    )
    commands = [event for event in world.events if event[0] == "launch"]
    assert [event[1] for event in commands] == ["keycloak", "gateway"]
    assert "--spi-connections-jpa--quarkus--migration-strategy=validate" in commands[0][2]
    assert "--spi-connections-jpa--quarkus--initialize-empty=false" in commands[0][2]
    assert commands[1][3]["RESTORE_MAINTENANCE"] == "1"


@pytest.mark.parametrize(
    "defect", ["generation", "owner", "pid", "data", "port", "cohort", "binary", "hba"]
)
def test_capture_refuses_before_stop_or_hba(world, defect):
    state = world.source.state
    before = (state / "postgres/pg_hba.conf").read_bytes()
    binding = load(state / "runtime-binding.json")
    generation = binding["generation"]
    if defect == "generation":
        generation = str(uuid4())
    if defect == "owner":
        (state / "owner.json").write_text("{}")
    if defect == "pid":
        world.live.pop(binding["processes"]["postgres.process.json"]["pid"])
    if defect == "data":
        world.facts[state]["data"] = str(world.root / "foreign")
    if defect == "port":
        world.facts[state]["port"] += 1
    if defect == "cohort":
        (state / "api.env").write_bytes(b"AI_PROVIDER=foreign\n")
    if defect == "binary":
        (world.pg / "pg_dump.exe").write_bytes(b"unqualified tool")
    if defect == "hba":
        before = b"host all all 127.0.0.1/32 trust\n"
        (state / "postgres/pg_hba.conf").write_bytes(before)
    with pytest.raises((ValueError, ProcessLookupError)):
        e.capture_native(state, generation, world.root / ".tools/refused")
    assert world.events == [] and (state / "postgres/pg_hba.conf").read_bytes() == before


def test_existing_native_lock_is_not_nested(world):
    state = world.source.state
    with world.source.operation(), pytest.raises(OSError):
        e.capture_native(
            state, load(state / "runtime-binding.json")["generation"], world.root / ".tools/refused"
        )
    assert world.events == []


def test_held_pg_and_launch_environments_ignore_later_file_mutation(world, monkeypatch):
    stack = world.source
    files = e.cohort(stack)
    pg = e.NativePG(stack, load(stack.state / "postgres.process.json"), files)
    (stack.state / "postgres.env").write_bytes(b"POSTGRES_PASSWORD=UNPINNED\n")
    (stack.state / "api.env").write_bytes(b"AI_PROVIDER=foreign\nPYTHONPATH=UNPINNED\n")
    assert pg.env()["PGPASSWORD"] == "a" * 64
    assert e.runtime_env(stack, files, "api")["AI_PROVIDER"] == "mock"
    called = []
    monkeypatch.setattr(e, "execute", lambda *_a, **kw: called.append(kw["environment"]) or b"ok")
    pg.command("psql", [])
    assert called[0]["PGPASSWORD"] == "a" * 64
    for forbidden in ("initdb", "pg_ctl", "pg_restore"):
        with pytest.raises(ValueError, match="Existing-only"):
            pg.command(forbidden, [])


def test_old_bridge_stops_before_new_source_integration_and_resumes(world):
    tool = Path(__file__).resolve().parents[3] / "tools/native_stop_bridge.py"
    spec = importlib.util.spec_from_file_location("old_bridge", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = world.source.state
    old = load(state / "runtime-binding.json")
    destination = state / "old-stop.private.json"
    pin = module.stop_old(
        e.native,
        SimpleNamespace(runtime=lambda stack: {"binary_sha256": e.runtime_binaries(stack)}),
        state,
        destination,
        old["generation"],
        e.sha((state / "runtime-binding.json").read_bytes()),
    )
    assert load(destination)["result"] == "STOPPED" and not list(state.glob("*.process.json"))
    started = e.start_existing(
        state, destination, pin, source_pin="e" * 40, source_sha256=world.code_sha
    )
    assert started["pg_started"] and started["generation"] != old["generation"]
    assert world.facts[state]["epoch"] == load(destination)["database"]["epoch"]


def bound_target(world, monkeypatch, *, different_pg_path=False):
    capture = captured(world, monkeypatch)
    source = world.source
    e.start_existing(
        source.state,
        capture["handoff"]["path"],
        capture["handoff"]["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    generation = load(source.state / "runtime-binding.json")["generation"]
    stopped = e.stop_existing(source.state, generation)
    state = world.root / ".tools/target"
    (state / "postgres/global").mkdir(parents=True)
    for name, raw in {
        "PG_VERSION": b"17\n",
        "global/pg_control": b"TARGETIDcontrol fixture",
        "pg_hba.conf": e.SEALED_HBA,
    }.items():
        (state / "postgres" / name).write_bytes(raw)
    pg_bin = world.pg
    if different_pg_path:
        pg_bin = world.root / "other-pg17"
        pg_bin.mkdir()
        for path in world.pg.iterdir():
            (pg_bin / path.name).write_bytes(path.read_bytes())
    record = world.process(pg_bin / "postgres.exe")
    port = 25433
    (state / "postgres/postmaster.pid").write_text(
        f"{record['pid']}\n{state / 'postgres'}\n0\n{port}\n"
    )
    (state / "password.private").write_bytes(b"b" * 64 + b"\n")
    owner = {
        "format": e.restore.FORMAT,
        "owner": str(uuid4()),
        "state": str(state),
        "pg_bin": str(pg_bin),
        "port": port,
        "user": "postgres",
        "process": record,
        "status": "SEALED",
        "hba_sha256": e.sha(e.SEALED_HBA),
        "binaries": {p.name: {"sha256": e.digest(p)} for p in pg_bin.iterdir()},
    }
    e.native.write_json(state / "owner.json", owner)
    (state / "catalog-restored/catalog").mkdir(parents=True)
    (state / "catalog-restored/catalog/manifest.json").write_bytes(b"{}")
    world.facts[state] = world.facts[source.state] | {
        "data": str(state / "postgres"),
        "port": port,
        "epoch": str(uuid4()),
        "ai": False,
        "sessions": 0,
        "closed_at": "synthetic-fixed-closed-at",
    }
    receipt = {
        "result": "PASS",
        "paired_restore": True,
        "external_evidence_validated_before_target_create": True,
        "archive_manifest_sha256": capture["capture"]["trusted_manifest_sha256"],
        "source_epoch": world.facts[source.state]["epoch"],
        "restored_epoch": world.facts[state]["epoch"],
    }
    e.native.write_json(state / "receipt.json", receipt)
    descriptor = e.bind_target(
        state,
        capture_path=capture["handoff"]["path"],
        capture_sha256=capture["handoff"]["sha256"],
        source_stop_path=stopped["path"],
        source_stop_sha256=stopped["sha256"],
        restore_receipt_sha256=e.digest(state / "receipt.json"),
    )
    world.events.clear()
    return state, descriptor


def test_target_uses_own_password_data_catalog_and_real_dual_markers(world, monkeypatch):
    source_files = e.cohort(world.source)
    state, descriptor = bound_target(world, monkeypatch, different_pg_path=True)
    before_epoch = world.facts[state]["epoch"]
    started = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    assert not started["pg_started"] and not any(x[0] == "pg-start" for x in world.events)
    assert load(state / "owner.json")["process"] == load(state / "postgres.process.json")
    assert load(state / "owner.json")["status"] == "RUNNING"
    assert load(state / "native.json")["pg_bin"] == str(world.root / "other-pg17")
    assert e.env_bytes((state / "postgres.env").read_bytes())["POSTGRES_PASSWORD"] == "b" * 64
    assert e.env_bytes((state / "postgres.env").read_bytes())["APP_API_PASSWORD"] == "restored-api"
    target_api = e.env_bytes((state / "api.env").read_bytes())
    assert (
        target_api["CATALOG_PAGE_TOKEN_SECRET"]
        == e.env_bytes(source_files["api.env"])["CATALOG_PAGE_TOKEN_SECRET"]
    )
    assert target_api["CATALOG_ARTIFACT_ROOT"] == (state / "catalog-restored/catalog").as_posix()
    assert target_api["OIDC_CA_BUNDLE"] == (state / "tls/ca.pem").as_posix()
    assert (state / "tls/ca.pem").read_bytes() == source_files["tls/ca.pem"]
    assert not (state / "provisioned.json").exists() and not (state / "realm").exists()
    assert (state / "postgres/pg_hba.conf").read_bytes() == e.SERVICE_HBA
    assert b"calorie_app_worker" not in e.SERVICE_HBA
    assert world.facts[state]["epoch"] == before_epoch


def test_target_stopped_resume_preserves_sessions_epoch_and_closed_at(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    first = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    world.facts[state]["sessions"] = (
        3  # Legitimate same-epoch sessions from earlier target activity.
    )
    snapshot = dict(world.facts[state])
    stopped = e.stop_existing(state, first["generation"])
    world.events.clear()
    second = e.start_existing(
        state, stopped["path"], stopped["sha256"], source_pin="e" * 40, source_sha256=world.code_sha
    )
    assert second["pg_started"] and first["generation"] != second["generation"]
    assert [x[0] for x in world.events].count("pg-start") == 1
    assert world.facts[state] == snapshot
    assert load(state / "owner.json")["process"] == load(state / "postgres.process.json")


@pytest.mark.parametrize("defect", ["owner", "password", "receipt", "source-live", "catalog-alias"])
def test_target_refusal_before_service_or_hba_change(world, monkeypatch, defect):
    state, descriptor = bound_target(world, monkeypatch)
    hba = (state / "postgres/pg_hba.conf").read_bytes()
    if defect == "owner":
        value = load(state / "owner.json")
        value["owner"] = str(uuid4())
        e.native.write_json(state / "owner.json", value)
    if defect == "password":
        (state / "password.private").write_bytes(b"d" * 64 + b"\n")
    if defect == "receipt":
        (state / "receipt.json").write_bytes(b"{}")
    if defect == "source-live":
        (world.source.state / "postgres/postmaster.pid").write_text("foreign live authority")
    if defect == "catalog-alias":
        # Portable rejection of a known junction/symlink boundary, no OS link privileges needed.
        original = Path.is_junction
        monkeypatch.setattr(
            Path, "is_junction", lambda p: p == state / "catalog-restored" or original(p)
        )
    with pytest.raises((ValueError, KeyError)):
        e.start_existing(
            state,
            descriptor["path"],
            descriptor["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )
    assert world.events == [] and (state / "postgres/pg_hba.conf").read_bytes() == hba


def test_stopped_target_replaced_cluster_refuses_before_pg_start(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    first = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    stopped = e.stop_existing(state, first["generation"])
    (state / "postgres/global/pg_control").write_bytes(b"FOREIGN!control fixture")
    world.events.clear()
    with pytest.raises(ValueError, match="physical cluster"):
        e.start_existing(
            state,
            stopped["path"],
            stopped["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )
    assert world.events == []


def maintenance_proof(world, monkeypatch):
    capture = captured(world, monkeypatch)
    started = e.start_existing(
        world.source.state,
        capture["handoff"]["path"],
        capture["handoff"]["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    state = world.source.state
    binding = load(state / "runtime-binding.json")
    closed_at = datetime.fromisoformat(binding["lifecycle"]["started_at"]) + timedelta(seconds=1)
    closed_mono = binding["lifecycle"]["started_monotonic"] + 1
    proof = {
        "format": "native-existing-auth-fence/v1",
        "generation": started["generation"],
        "issuer": world.source.origin + "/realms/calorie-dev",
        "qualified_minimum_seconds": 421,
        "qualified_token_settings_sha256": "d" * 64,
        "logout_all_succeeded": True,
        "issuance_api_503_observed": True,
        "provider_user_session_counts": {"synthetic-a": 0},
        "closed_after_logout_at": closed_at.isoformat(),
        "closed_after_logout_monotonic": closed_mono,
    }

    # Explicit policy-clock test boundary; no server/database clocks or closed_at are changed.
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return closed_at + timedelta(seconds=500)

    monkeypatch.setattr(e, "datetime", Clock)
    monkeypatch.setattr(e.time, "monotonic", lambda: closed_mono + 500)
    world.events.clear()
    return state, binding, proof


@pytest.mark.parametrize(
    "defect", ["generation", "timer-generation", "short", "sessions", "settings"]
)
def test_activation_rejects_incomplete_fence_before_gateway_mutation(world, monkeypatch, defect):
    state, binding, proof = maintenance_proof(world, monkeypatch)
    if defect == "generation":
        proof["generation"] = str(uuid4())
    if defect == "timer-generation":
        binding["lifecycle"]["generation"] = str(uuid4())
        e.native.write_json(state / "runtime-binding.json", binding)
    if defect == "short":
        monkeypatch.setattr(
            e.time, "monotonic", lambda: proof["closed_after_logout_monotonic"] + 420
        )
    if defect == "sessions":
        proof["provider_user_session_counts"]["synthetic-a"] = 1
    if defect == "settings":
        proof["qualified_token_settings_sha256"] = "not-qualified"
    path = state / "synthetic-fence.private.json"
    reference = e.write_new(path, proof)
    with pytest.raises(ValueError):
        e.activate(state, binding["generation"], path, reference["sha256"])
    assert world.events == []


def test_activation_has_new_real_generation_and_does_not_claim_old_token_probe(world, monkeypatch):
    state, binding, proof = maintenance_proof(world, monkeypatch)
    reference = e.write_new(state / "synthetic-fence.private.json", proof)
    result = e.activate(state, binding["generation"], reference["path"], reference["sha256"])
    assert result["generation"] != binding["generation"]
    assert result["old_token_refusals"] == "REQUIRED_AFTER_OPEN_BEFORE_CLIENT_ADMISSION"
    assert load(state / "runtime-binding.json")["processes"] == {
        p.name: load(p) for p in state.glob("*.process.json")
    }
    assert world.source.require_running()["generation"] == result["generation"]
    assert not (state / "existing-runtime.private.json").exists()


def test_failed_service_start_preserves_real_partial_markers_and_can_stop(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    original_launch = e.native.Native.launch

    def fail_gateway(stack, name, arguments, env):
        if name == "gateway":
            raise RuntimeError("Synthetic launch boundary failure")
        return original_launch(stack, name, arguments, env)

    monkeypatch.setattr(e.native.Native, "launch", fail_gateway)
    with pytest.raises(RuntimeError, match="Synthetic launch"):
        e.start_existing(
            state,
            descriptor["path"],
            descriptor["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )
    binding = load(state / "runtime-binding.json")
    assert binding["state"] == "START_FAILED"
    assert set(binding["processes"]) == {"postgres.process.json", "keycloak.process.json"}
    stopped = e.stop_existing(state, binding["generation"])
    assert load(stopped["path"])["result"] == "STOPPED"
    assert load(state / "owner.json")["status"] == "STOPPED"
    assert not list(state.glob("*.process.json"))


def test_pg_ctl_failure_after_own_start_keeps_qualified_real_pid(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    first = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    stopped = e.stop_existing(state, first["generation"])
    original_run = e.native.Native.run

    def failed_checked_start(stack, arguments, **kwargs):
        result = original_run(stack, arguments, **kwargs)
        if str(arguments[-1]) == "start":
            raise RuntimeError("Synthetic pg_ctl failed after child start")
        return result

    monkeypatch.setattr(e.native.Native, "run", failed_checked_start)
    with pytest.raises(RuntimeError, match="after child start"):
        e.start_existing(
            state,
            stopped["path"],
            stopped["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )
    binding = load(state / "runtime-binding.json")
    assert binding["state"] == "START_FAILED"
    assert load(state / "owner.json")["process"] == load(state / "postgres.process.json")
    assert world.live[load(state / "postgres.process.json")["pid"]] == load(
        state / "postgres.process.json"
    )
    final = e.stop_existing(state, binding["generation"])
    assert load(final["path"])["pg_stop"]["exit_code"] == 0


def test_receipt_pin_is_of_held_serialization_not_reopened_output(world, monkeypatch):
    original = e.native.private_write

    def substituted(path, text):
        original(path, text)
        path.write_bytes(b"untrusted substitution")

    monkeypatch.setattr(e.native, "private_write", substituted)
    value = {"fixed": "controller input"}
    reference = e.write_new(world.source.state / "pin.private.json", value)
    assert reference["sha256"] == e.sha((json.dumps(value, indent=2) + "\n").encode())
    assert reference["sha256"] != e.digest(Path(reference["path"]))


def test_generation_ancestry_supports_multiple_real_handoffs_and_rejects_mismatch(world):
    state = world.source.state
    capture = {
        "format": "native-existing-capture/v1",
        "kind": "source",
        "result": "SEALED",
        "state": str(state),
    }
    root = e.write_new(state / "ancestor-capture.private.json", capture)
    reference = root
    for n in range(4):
        parent = {
            "format": "native-existing-stop/v1",
            "kind": "source",
            "result": "STOPPED",
            "state": str(state),
            "runtime": {"parent": reference},
            "parent_handoff": reference,
        }
        reference = e.write_new(state / f"ancestor-stop-{n}.private.json", parent)
    e.descends_from_capture(parent, root["sha256"])
    parent["parent_handoff"] = root
    with pytest.raises(ValueError, match="parent/runtime"):
        e.descends_from_capture(parent, root["sha256"])


def test_failed_capture_preserves_hba_evidence_and_source_can_resume_after_safe_stop(
    world, monkeypatch
):
    state = world.source.state
    original = (state / "postgres/pg_hba.conf").read_bytes()
    generation = load(state / "runtime-binding.json")["generation"]
    world.clients = 1
    with pytest.raises(ValueError, match="clients remain"):
        e.capture_native(state, generation, world.root / ".tools/refused-capture")
    assert (state / "postgres/pg_hba.conf").read_bytes() == e.SEALED_HBA
    admission = next((state / "existing-lifecycle").glob("*/admission.private.json"))
    assert bytes.fromhex(load(admission)["original_hba_hex"]) == original
    assert load(state / "runtime-binding.json")["state"] == "CAPTURE_FAILED"
    world.clients = 0
    stopped = e.stop_existing(state, generation)
    assert load(stopped["path"])["stopped_hba_sha256"] == e.sha(e.SEALED_HBA)
    e.start_existing(
        state, stopped["path"], stopped["sha256"], source_pin="e" * 40, source_sha256=world.code_sha
    )
    assert (state / "postgres/pg_hba.conf").read_bytes() == original


def test_old_owned_capture_wrapper_retains_marker_identity_and_archive_shape(world, monkeypatch):
    stack = world.source
    state = stack.state
    record = load(state / "postgres.process.json")
    owner = {
        "format": e.restore.FORMAT,
        "owner": str(uuid4()),
        "state": str(state),
        "pg_bin": str(world.pg),
        "port": stack.config["pg_port"],
        "user": "postgres",
        "process": record,
        "status": "SEALED",
        "hba_sha256": e.sha(e.SEALED_HBA),
        "binaries": {p.name: {"sha256": e.digest(p)} for p in world.pg.iterdir()},
    }
    e.native.write_json(state / "owner.json", owner)
    (state / "postgres/pg_hba.conf").write_bytes(e.SEALED_HBA)

    def dump(_pg, name, _args, **kwargs):
        kwargs["output_path"].write_bytes(b"synthetic boundary dump")

    monkeypatch.setattr(e.restore.OwnedPG, "command", dump)
    pg = e.restore.OwnedPG(state)
    result = e.restore.capture(pg, world.root / ".tools/owned-archive")
    assert result["source_owner"] == owner["owner"]
    assert "generation" not in result["native_source"]
    assert set(result["files"]) == {"roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar"}


def test_source_stop_does_not_assume_stopping_api_kc_removes_other_clients(world, monkeypatch):
    capture = captured(world, monkeypatch)
    started = e.start_existing(
        world.source.state,
        capture["handoff"]["path"],
        capture["handoff"]["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    world.clients = 1
    with pytest.raises(ValueError, match="clients remain"):
        e.stop_existing(world.source.state, started["generation"])
    failed = load(world.source.state / "runtime-binding.json")
    assert failed["state"] == "STOP_FAILED"
    assert set(failed["processes"]) == {"postgres.process.json"}
    assert (world.source.state / "postgres/postmaster.pid").exists()
    world.clients = 0
    completed = e.stop_existing(world.source.state, started["generation"])
    assert load(completed["path"])["result"] == "STOPPED"


def test_service_launch_uses_admitted_bytes_when_env_file_changes_after_admission(
    world, monkeypatch
):
    capture = captured(world, monkeypatch)
    original = e.native.Native.launch

    def changed_after_admission(stack, name, arguments, env):
        if name == "keycloak":
            (stack.state / "api.env").write_bytes(b"AI_PROVIDER=foreign\nPYTHONPATH=untrusted\n")
        return original(stack, name, arguments, env)

    monkeypatch.setattr(e.native.Native, "launch", changed_after_admission)
    e.start_existing(
        world.source.state,
        capture["handoff"]["path"],
        capture["handoff"]["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    gateway = next(x for x in world.events if x[0:2] == ("launch", "gateway"))
    assert gateway[3]["AI_PROVIDER"] == "mock" and "untrusted" not in gateway[3]["PYTHONPATH"]
    with pytest.raises(ValueError, match="cohort stale"):
        e.qualified_runtime(e.native.Native(world.source.state), {"MAINTENANCE"})
    generation = load(world.source.state / "runtime-binding.json")["generation"]
    stopped = e.stop_existing(world.source.state, generation)
    receipt = load(stopped["path"])
    assert (
        receipt["result"] == "STOPPED_COHORT_DRIFT" and not receipt["automatic_resume_authorized"]
    )
    assert "api.env" in receipt["configuration_drift"]
    assert receipt["configuration_files"]["api.env"] != e.digest(world.source.state / "api.env")
    world.events.clear()
    with pytest.raises(ValueError, match="Incomplete source handoff"):
        e.start_existing(
            world.source.state,
            stopped["path"],
            stopped["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )
    assert world.events == []


@pytest.mark.parametrize("suffix", [" ", ".", ":stream"])
def test_ambiguous_native_state_refuses_before_any_effect(world, suffix):
    with pytest.raises(ValueError, match="Ambiguous"):
        e.capture_native(str(world.source.state) + suffix, str(uuid4()), world.root / ".tools/new")
    assert world.events == []


def test_failed_activation_closes_new_gateway_and_never_publishes_running(world, monkeypatch):
    state, binding, proof = maintenance_proof(world, monkeypatch)
    reference = e.write_new(state / "synthetic-fence.private.json", proof)

    def unavailable(_stack):
        raise RuntimeError("Synthetic readiness failure")

    monkeypatch.setattr(e, "ready", unavailable)
    with pytest.raises(RuntimeError, match="readiness"):
        e.activate(state, binding["generation"], reference["path"], reference["sha256"])
    actual = load(state / "runtime-binding.json")
    assert actual["state"] == "ACTIVATION_FAILED" and not (state / "gateway.process.json").exists()
    assert set(actual["processes"]) == {"postgres.process.json", "keycloak.process.json"}
    completed = e.stop_existing(state, actual["generation"])
    assert load(completed["path"])["result"] == "STOPPED"


def test_stop_receipt_uses_final_sessions_after_inflight_pull_finishes(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    first = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    original = e.native.terminate

    def completed_inflight_request(record):
        original(record)
        world.facts[state]["sessions"] = 3

    monkeypatch.setattr(e.native, "terminate", completed_inflight_request)
    stopped = e.stop_existing(state, first["generation"])
    assert load(stopped["path"])["database"]["sessions"] == 3
    resumed = e.start_existing(
        state, stopped["path"], stopped["sha256"], source_pin="e" * 40, source_sha256=world.code_sha
    )
    assert resumed["pg_started"] and world.facts[state]["sessions"] == 3


def test_materialized_target_never_repins_config_changed_during_promotion(world, monkeypatch):
    original = e.shutil.move
    target = world.root / ".tools/target"

    def changed_after_move(source, destination):
        result = original(source, destination)
        if Path(destination) == target / "worker.env":
            (target / "api.env").write_bytes(b"AI_PROVIDER=foreign\n")
        return result

    monkeypatch.setattr(e.shutil, "move", changed_after_move)
    with pytest.raises(ValueError, match="Materialized configuration changed"):
        bound_target(world, monkeypatch)
    assert not (target / "existing-target.private.json").exists()
    assert (target / "postgres/pg_hba.conf").read_bytes() == e.SEALED_HBA
    assert not any(
        x[0] == "launch" and x[3]["CALORIE_NATIVE_STATE"] == str(target) for x in world.events
    )
