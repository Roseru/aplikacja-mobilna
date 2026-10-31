import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docker_restore as restore  # noqa: E402


@pytest.fixture
def paired(tmp_path):
    folder = tmp_path / "paired"
    folder.mkdir()
    payloads = {name: b"paired payload" for name in restore.ARCHIVES}
    source = {
        "project": "owned-source",
        "host": "127.0.0.1",
        "port": 28443,
        "origin": "https://127.0.0.1:28443",
    }
    payloads["config/config.json"] = json.dumps(source).encode()
    payloads["config/credentials.json"] = b"{}"
    for name in ("postgres.env", "api.env", "keycloak.env"):
        payloads["config/" + name] = b"OWNED_FIXTURE=true\n"
    for name in ("ca.pem", "server.pem", "server.key"):
        payloads["config/tls/" + name] = b"owned fixture, no actual key"
    for name, value in payloads.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    manifest = {
        "format": 1,
        "writers_stopped": True,
        "source_epoch": str(uuid4()),
        "captured_at": datetime.now(UTC).isoformat(),
        "revision": "0026_ledger_review",
        "fingerprints": {"calorie_app": restore.sha(b"[]"), "keycloak": restore.sha(b"[]")},
        "files": {
            name: {"size": len(value), "sha256": restore.sha(value)}
            for name, value in payloads.items()
        },
    }
    restore.write(folder / "manifest.json", manifest)
    return folder, restore.digest(folder / "manifest.json")


def images():
    return {
        name: "sha256:" + digit * 64
        for name, digit in zip(("postgres", "keycloak", "backend", "gateway"), "abcd", strict=True)
    }


@pytest.mark.parametrize(
    "name",
    [
        "../secret",
        "config/a:stream",
        "config/a.",
        "config/a ",
        "C:/secret",
        "config\\secret",
        "/secret",
    ],
)
def test_untrusted_payload_names_refused(name):
    with pytest.raises(ValueError):
        restore.relative(name)


def test_external_pin_mismatch_precedes_docker_and_target_creation(paired, tmp_path, monkeypatch):
    folder, _ = paired
    monkeypatch.setattr(restore, "docker", lambda *args: pytest.fail("Docker must stay untouched"))
    target = tmp_path / "new"
    with pytest.raises(ValueError, match="pin differs"):
        restore.materialize(folder, target, "owned-target", "0" * 64, images())
    assert not target.exists()


def test_same_size_payload_change_refused_before_target(paired, tmp_path, monkeypatch):
    folder, pin = paired
    path = folder / "calorie_app.dump"
    path.write_bytes(b"X" + path.read_bytes()[1:])
    monkeypatch.setattr(restore, "docker", lambda *args: pytest.fail("No Docker on corrupt input"))
    target = tmp_path / "new"
    with pytest.raises(ValueError, match="checksum"):
        restore.materialize(folder, target, "owned-target", pin, images())
    assert not target.exists()


def test_existing_target_preserved(paired, tmp_path, monkeypatch):
    folder, pin = paired
    target = tmp_path / "existing"
    target.mkdir()
    (target / "marker").write_text("do not touch")
    monkeypatch.setattr(
        restore, "docker", lambda *args: pytest.fail("No Docker for existing target")
    )
    with pytest.raises(ValueError, match="New disjoint"):
        restore.materialize(folder, target, "owned-target", pin, images())
    assert (target / "marker").read_text() == "do not touch"


def test_source_project_is_never_a_target(paired, tmp_path, monkeypatch):
    folder, pin = paired
    monkeypatch.setattr(
        restore, "docker", lambda *args: pytest.fail("Do not inspect/mutate source")
    )
    with pytest.raises(ValueError, match="Source project"):
        restore.materialize(folder, tmp_path / "new", "owned-source", pin, images())


@pytest.mark.parametrize("resource", ["container", "volume", "network", "named_volume"])
def test_existing_resources_refuse_even_with_missing_state(resource, monkeypatch):
    def existing(*args):
        if resource == "container" and args[:2] == ("ps", "-aq"):
            return "foreign"
        if resource == "volume" and args[:3] == ("volume", "ls", "-q"):
            return "foreign"
        if resource == "network" and args[:3] == ("network", "ls", "-q"):
            return "foreign"
        if resource == "named_volume" and args == ("volume", "ls", "-q"):
            return "owned-target_postgres_data"
        return ""

    monkeypatch.setattr(restore, "docker", existing)
    with pytest.raises(ValueError, match="Existing"):
        restore.empty_project("owned-target")


def test_target_topology_has_no_source_init_migration_import_ai_or_ports(tmp_path):
    cfg = restore.configuration(tmp_path, "owned-target", {}, images(), "owner")
    assert set(cfg["services"]) == {"postgres", "keycloak", "api", "gateway", "catalog-init"}
    assert not any("ports" in value or "build" in value for value in cfg["services"].values())
    assert cfg["services"]["postgres"]["volumes"] == ["postgres_data:/var/lib/postgresql/data"]
    assert cfg["services"]["keycloak"]["command"] == restore.KC_VALIDATE
    assert "--import-realm" not in json.dumps(cfg)
    assert "init-db.sh" not in json.dumps(cfg)
    assert "migrate" not in cfg["services"]
    assert "ai-worker" not in cfg["services"]
    assert cfg["services"]["api"]["read_only"] is True


def test_mutable_tag_refused_before_any_resource(tmp_path):
    bad = images() | {"backend": "calorie-backend:latest"}
    with pytest.raises(ValueError, match="Immutable"):
        restore.configuration(tmp_path, "owned-target", {}, bad, "owner")


def test_target_loader_refuses_changed_compose(tmp_path):
    cfg = {"project": "owned-target", "origin": "https://127.0.0.1:28443"}
    restore.write(tmp_path / "config.json", cfg)
    restore.write(tmp_path / "compose.restore.json", {"services": {}})
    record = {
        "format": restore.FORMAT,
        "project": "owned-target",
        "owner": "own",
        "files": {"compose.restore.json": restore.digest(tmp_path / "compose.restore.json")},
    }
    restore.write(tmp_path / "restore-target.json", record)
    restore.write(tmp_path / "compose.restore.json", {"services": {"foreign": {}}})
    with pytest.raises(ValueError, match="configuration drift"):
        restore.Target(tmp_path)


def test_live_source_writer_prevents_cutover_before_sql(monkeypatch, tmp_path):
    class Owned:
        state = tmp_path
        record = {"source_project": "owned-source"}

    def running(*args):
        if args[:2] == ("ps", "-q"):
            return "live-api-id"
        if args[0] == "inspect":
            return "api"
        pytest.fail("No other command is authorized")

    monkeypatch.setattr(restore, "docker", running)
    monkeypatch.setattr(restore, "execute", lambda *args, **kwargs: pytest.fail("No source SQL"))
    with pytest.raises(ValueError, match="Source writer/issuer"):
        restore.source_closed(Owned())


def test_unfenced_target_cannot_start_api(monkeypatch, tmp_path):
    class Owned:
        state = tmp_path
        record = {"phase": "OFFLINE_TARGET_READY"}

        def compose(self, *args, **kwargs):
            pytest.fail("No API/gateway mutation before real fence")

    monkeypatch.setattr(restore, "Target", lambda state: Owned())
    with pytest.raises(ValueError, match="Real provider fence"):
        restore.activate(tmp_path, tmp_path / "sessions", "0" * 64)


@pytest.mark.parametrize("wall_scale,expected", [(1.0, "FENCE_COMPLETE"), (0.5, "MAINTENANCE")])
def test_fence_observes_real_monotonic_and_wall_bound(monkeypatch, tmp_path, wall_scale, expected):
    ticks = {"elapsed": 0.0, "checks": []}

    class Clock:
        @staticmethod
        def now(zone):
            return datetime(2026, 10, 31, tzinfo=UTC) + timedelta(
                seconds=ticks["elapsed"] * wall_scale
            )

    class Owned:
        state = tmp_path
        record = {"phase": "OFFLINE_TARGET_READY"}

        def save(self):
            if self.record["phase"] == "FENCE_COMPLETE":
                assert ticks["elapsed"] >= 421

        def compose(self, *args, **kwargs):
            assert args[-1] == "gateway"
            assert kwargs["maintenance"] is True

        def sql(self, database, query):
            return "300" if "access_token_lifespan" in query else str(UUID)

    class Reply:
        def __init__(self, value):
            self.value = value

        def json(self):
            return self.value

    owned = Owned()
    UUID = uuid4()
    monkeypatch.setattr(restore, "Target", lambda state: owned)
    monkeypatch.setattr(restore, "Probe", lambda target: object())
    monkeypatch.setattr(restore, "datetime", Clock)
    monkeypatch.setattr(restore.time, "monotonic", lambda: ticks["elapsed"])
    monkeypatch.setattr(
        restore.time,
        "sleep",
        lambda seconds: ticks.__setitem__("elapsed", ticks["elapsed"] + seconds),
    )
    monkeypatch.setattr(restore, "source_closed", lambda target: None)
    monkeypatch.setattr(restore, "maintenance_configuration", lambda target: None)
    monkeypatch.setattr(
        restore, "wait_maintenance", lambda probe: ticks["checks"].append(ticks["elapsed"])
    )
    monkeypatch.setattr(
        restore,
        "admin",
        lambda probe, method, path: Reply({"failedRequests": []} if method == "POST" else []),
    )
    if wall_scale == 1.0:
        result = restore.fence(tmp_path)
        assert result["real_fence_seconds"] >= 421
        assert len(ticks["checks"]) > 40
    else:
        with pytest.raises(ValueError, match="Wall and monotonic"):
            restore.fence(tmp_path)
    assert owned.record["phase"] == expected


def test_partial_gateway_activation_error_closes_ingress(monkeypatch, tmp_path):
    (tmp_path / "tls").mkdir()
    (tmp_path / "tls/ca.pem").write_bytes(b"own public CA fixture")
    restore.write(tmp_path / "compose.restore.json", {"services": {"gateway": {}}})
    sessions = tmp_path / "old-private.json"
    restore.write(
        sessions,
        {
            "format": restore.FORMAT + "/old-sessions",
            "origin": "https://127.0.0.1:28443",
            "ca_sha256": restore.digest(tmp_path / "tls/ca.pem"),
            "sessions": {"a": {"source_http_status": 200}},
        },
    )
    calls = []

    class Owned:
        state = tmp_path
        origin = "https://127.0.0.1:28443"
        config = {"host": "127.0.0.1", "port": 28443}
        record = {"phase": "FENCE_COMPLETE", "files": {}}

        def save(self):
            pass

        def compose(self, *args):
            calls.append(args)
            if args[0] == "up" and args[-1] == "gateway":
                raise RuntimeError("partial owned gateway start")

    owned = Owned()
    monkeypatch.setattr(restore, "Target", lambda state: owned)
    monkeypatch.setattr(restore, "source_closed", lambda target: None)
    with pytest.raises(RuntimeError, match="partial owned gateway"):
        restore.activate(tmp_path, sessions, restore.digest(sessions))
    assert calls[-1] == ("stop", "gateway", "api")
    assert owned.record["phase"] == "ADMISSION_FAILED_CLOSED"
