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


def test_optional_photo_topology_changes_only_private_new_volume_initialization(tmp_path):
    original = restore.configuration(tmp_path, "owned-target", {}, images(), "owner")
    changed = restore.configuration(tmp_path, "owned-target", {}, images(), "owner", photos=True)
    assert original["services"]["api"] == changed["services"]["api"]
    assert original["services"]["keycloak"] == changed["services"]["keycloak"]
    assert original["volumes"] == changed["volumes"]
    assert not any(
        "/photo-input" in mount for mount in original["services"]["catalog-init"]["volumes"]
    )
    assert changed["services"]["catalog-init"]["volumes"][-1].endswith(
        "/photos-restored/photos:/photo-input:ro"
    )
    command = changed["services"]["catalog-init"]["command"][-1]
    compile(command, "photo-copy-command", "exec")
    assert "shutil.copytree('/photo-input','/photos'" in command
    assert "ai-worker" not in changed["services"]
    assert not any("ports" in service for service in changed["services"].values())


@pytest.mark.parametrize("has_photos", [False, True])
def test_materialize_optional_photo_payload_before_init_preserves_old_path_and_closed_jobs(
    paired, tmp_path, monkeypatch, has_photos
):
    import io
    import re
    import tarfile

    from calorie_app.health import EXPECTED_REVISION

    folder, _ = paired
    manifest = restore.read(folder / "manifest.json")
    manifest["revision"] = EXPECTED_REVISION
    (folder / "roles.sql").write_text("CREATE ROLE postgres;\n")
    manifest["files"]["roles.sql"] = {
        "size": (folder / "roles.sql").stat().st_size,
        "sha256": restore.digest(folder / "roles.sql"),
    }
    payload = b"\xff\xd8prepared-private-fixture\xff\xd9"
    photo_name = "a" * 32 + ".jpg"
    if has_photos:
        archive = folder / "photos.tar"
        with tarfile.open(archive, "w") as output:
            root = tarfile.TarInfo("photos")
            root.type, root.mode = tarfile.DIRTYPE, 0o700
            output.addfile(root)
            item = tarfile.TarInfo("photos/" + photo_name)
            item.mode, item.size, item.mtime = 0o600, len(payload), 1_700_000_000
            output.addfile(item, io.BytesIO(payload))
        manifest["optional_photos"] = {"format": 1, "archive": "photos.tar", "root": "photos"}
        manifest["files"]["photos.tar"] = {
            "size": archive.stat().st_size,
            "sha256": restore.digest(archive),
        }
    restore.write(folder / "manifest.json", manifest)
    events = []
    queries = []

    class Offline:
        def __init__(self, state):
            self.state = state
            self.record = restore.read(state / "restore-target.json")
            self.epoch = manifest["source_epoch"]

        def save(self):
            restore.write(self.state / "restore-target.json", self.record)

        def compose(self, *args):
            events.append(args)
            if args[-1] == "catalog-init":
                staged = self.state / "photos-restored" / "photos" / photo_name
                assert staged.exists() is has_photos
                if has_photos:
                    assert staged.read_bytes() == payload
                    assert staged.stat().st_mtime == 1_700_000_000
            return "new-owned-postgres"

        def sql(self, database, query):
            queries.append(query)
            if "version_num" in query:
                return EXPECTED_REVISION
            if query in restore.FINGERPRINTS.values():
                return "[]"
            if "UPDATE app.installation_state SET sync_epoch=" in query:
                self.epoch = re.search(r"sync_epoch='([^']+)'", query).group(1)
                return ""
            if "SELECT sync_epoch" in query:
                return self.epoch
            if "e8n_restore_maintain" in query:
                return '{"pending":0}'
            if "SELECT dispatch_open" in query or "SELECT enabled" in query:
                return "f"
            if "SELECT count(*) FROM app.sync_sessions" in query:
                return "0"
            return ""

    def catalog(archive, target):
        (target / "catalog").mkdir(parents=True)

    monkeypatch.setattr(restore, "empty_project", lambda _: None)
    monkeypatch.setattr(restore, "docker", lambda *args: args[-1])
    monkeypatch.setattr(restore, "execute", lambda *args, **kwargs: b"")
    monkeypatch.setattr(restore, "Target", Offline)
    monkeypatch.setattr(restore, "restore_catalog", catalog)
    target = tmp_path / "brand-new"
    result = restore.materialize(
        folder, target, "owned-target", restore.digest(folder / "manifest.json"), images()
    )
    assert result["phase"] == "OFFLINE_TARGET_READY"
    assert result["api_started"] is result["ports_published"] is result["ai_started"] is False
    assert all(command[-1] not in {"api", "ai-worker", "gateway"} for command in events)
    assert any("dispatch_open=false" in query for query in queries)
    assert not any("dispatch_open=true" in query or "configure-pool" in query for query in queries)
    if has_photos:
        assert result["optional_photos"] == {
            "files": 1,
            "bytes": len(payload),
            "archive_sha256": manifest["files"]["photos.tar"]["sha256"],
            "jobs_resumed": False,
        }
    else:
        assert "optional_photos" not in result
        assert not (target / "photos-restored").exists()


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


@pytest.mark.parametrize("stop_fails", [False, True])
def test_partial_gateway_activation_error_closes_ingress(monkeypatch, tmp_path, stop_fails):
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
            if args[0] == "stop" and stop_fails:
                raise RuntimeError("own stop failed")

    owned = Owned()
    monkeypatch.setattr(restore, "Target", lambda state: owned)
    monkeypatch.setattr(restore, "source_closed", lambda target: None)
    with pytest.raises(
        RuntimeError, match="own stop failed" if stop_fails else "partial owned gateway"
    ):
        restore.activate(tmp_path, sessions, restore.digest(sessions))
    assert calls[-1] == ("stop", "gateway", "api")
    if stop_fails:
        assert owned.record["phase"] == "ADMISSION_CLOSE_FAILED"
        assert owned.record["api_started"] == "UNKNOWN"
        assert owned.record["ports_published"] == "UNKNOWN"
    else:
        assert owned.record["phase"] == "ADMISSION_FAILED_CLOSED"
        assert owned.record["api_started"] is False
        assert owned.record["ports_published"] is False


def test_source_password_or_role_drift_refuses_cutover_with_readonly_source_sql(
    monkeypatch, tmp_path
):
    (tmp_path / "paired-input").mkdir()
    restore.write(
        tmp_path / "paired-input/manifest.json",
        {"fingerprints": {"calorie_app": restore.sha(b"[]"), "keycloak": restore.sha(b"[]")}},
    )
    queries = []

    class Owned:
        state = tmp_path
        record = {"source_project": "owned-source"}

        def sql(self, database, query):
            assert database == "keycloak"
            assert query.startswith("SELECT")
            return '["changed target credentials"]'

    def command(*args):
        if args[0] == "ps":
            return "owned-source-pg-id"
        if args[0] == "inspect":
            return "postgres"
        pytest.fail("No Docker mutation")

    def execute(directory, args, *, input_path):
        query = input_path.read_text()
        queries.append(query)
        assert query.startswith("BEGIN READ ONLY;") and query.endswith("ROLLBACK;")
        assert args[0:3] == ["docker", "exec", "-i"]
        return b"0" if "pg_stat_activity" in query else b"[]"

    monkeypatch.setattr(restore, "docker", command)
    monkeypatch.setattr(restore, "execute", execute)
    with pytest.raises(ValueError, match="credentials/roles/profile drift"):
        restore.source_closed(Owned())
    assert len(queries) == 4
