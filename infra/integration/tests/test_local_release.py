import copy
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backup  # noqa: E402
import local_release as release  # noqa: E402
from run import Stack  # noqa: E402


@pytest.fixture
def installed(tmp_path, monkeypatch):
    source = tmp_path / "source"
    state = tmp_path / "private-state"
    source.mkdir()
    state.mkdir()
    monkeypatch.setattr(release, "HERE", source)
    monkeypatch.setattr(release, "ROOT", source)
    project = "owned-local"
    (state / "config.json").write_text(
        json.dumps(
            {
                "project": project,
                "origin": "https://127.0.0.1:28443",
                "host": "127.0.0.1",
            }
        )
    )
    for name in ("compose.env", "worker.env", "postgres.env", "api.env"):
        (state / name).write_text("PRIVATE_SECRET=never-print-this\n")
    (state / "credentials.json").write_text("{}")
    (state / "realm").mkdir()
    (state / "tls").mkdir()
    (state / "tls" / "ca.pem").write_text("test-only")
    for name in release.SOURCE_FILES:
        (source / name).write_text("test source")
    compose = [
        source / "compose.yaml",
        state / "mock.yaml",
        state / "spi.yaml",
        source / "compose.e8.yaml",
    ]
    for path in compose:
        path.write_text("test fixture, never executed")
    values = {}
    photo = project + "_ai_photo_data"
    for index, service in enumerate(sorted(release.SERVICES), 1):
        values[service] = {
            "Id": f"{index:064x}",
            "Image": "sha256:" + "a" * 64,
            "Config": {
                "Cmd": ["start", "--optimized"] if service == "keycloak" else ["fixture"],
                "Env": ["AI_PROVIDER=mock"],
                "Labels": {
                    "com.docker.compose.project": project,
                    "com.docker.compose.service": service,
                },
            },
            "HostConfig": {"PortBindings": {}},
            "NetworkSettings": {"Networks": {project + "_default": {}}},
            "State": {"Running": True, "Pid": 100 + index, "Health": {"Status": "healthy"}},
            "Mounts": [],
        }
    for service in ("api", "ai-worker"):
        values[service]["Mounts"] = [
            {"Type": "volume", "Name": photo, "Destination": "/photos", "RW": True}
        ]
    values["postgres"]["Mounts"] = [
        {
            "Type": "volume",
            "Name": project + "_postgres_data",
            "Destination": "/var/lib/postgresql/data",
            "RW": True,
        }
    ]
    volume_names = {photo, project + "_postgres_data"}
    profile = {
        "format": 1,
        "project": project,
        "state": str(state),
        "origin": "https://127.0.0.1:28443",
        "docker_endpoint": "unix:///qualified.sock",
        "engine_id": "engine-fixture",
        "source_commit": "b" * 40,
        "ai_provider": "mock",
        "compose_files": [release.pin(path) for path in compose],
        "files": [
            release.pin(path)
            for path in sorted(
                {
                    state / "config.json",
                    state / "compose.env",
                    state / "worker.env",
                    state / "tls" / "ca.pem",
                    *(source / name for name in release.SOURCE_FILES),
                }
            )
        ],
        "containers": {
            name: {
                "id": value["Id"],
                "image": value["Image"],
                "configuration_sha256": release.configuration_hash(value),
            }
            for name, value in values.items()
        },
        "volumes": sorted(volume_names),
    }
    profile_path = tmp_path / "runtime.json"
    profile_path.write_text(json.dumps(profile))
    calls = []

    def docker(endpoint, *args):
        calls.append(("docker", endpoint, *args))
        if args[0] == "info":
            return "engine-fixture"
        if args[0] == "ps":
            return "\n".join(value["Id"] for value in values.values())
        if args[0] == "inspect":
            return json.dumps(list(values.values()))
        if args[:2] == ("volume", "inspect"):
            return json.dumps(
                [
                    {"Name": name, "Labels": {"com.docker.compose.project": project}}
                    for name in sorted(volume_names)
                ]
            )
        raise AssertionError(args)

    monkeypatch.setattr(release, "docker", docker)
    stack = release.ReleaseStack(profile_path)

    def compose(*args, **_):
        calls.append(("compose", *args))
        if args[0] in {"start", "stop"}:
            for service in args:
                if service in values:
                    values[service]["State"]["Running"] = args[0] == "start"
                    values[service]["State"]["Pid"] = 100 if args[0] == "start" else 0
        if args[0] == "exec" and args[2] in release.E8:
            task = release.E8[args[2]]
            metrics = {
                "motivation": {
                    "status": "ok",
                    "owners_handled": 0,
                    "dates_processed": 0,
                    "backlog": {
                        "pending_backfill": 0,
                        "pending_materialization": 0,
                        "oldest_matures_at": None,
                    },
                },
                "lifecycle": {"transitioned": 0, "responses_pruned": 0, "admissions_pruned": 0},
                "finalizer": {"processed": 0, "finalized": 0, "backlog": 0, "ready": True},
            }[task]
            from datetime import UTC, datetime

            return json.dumps(
                {"state": "ok", "last_success": datetime.now(UTC).isoformat(), "metrics": metrics}
            )
        return ""

    monkeypatch.setattr(stack, "compose", compose)
    monkeypatch.setattr(stack, "https_ready", lambda: True)
    return SimpleNamespace(
        stack=stack,
        state=state,
        source=source,
        values=values,
        profile=profile,
        path=profile_path,
        calls=calls,
    )


def test_binary_and_text_calls_share_full_chain_and_pinned_socket(installed, monkeypatch):
    stack = installed.stack
    command = stack.compose_command("exec", "-T", "postgres", "pg_dump")
    assert command[:3] == ["docker", "--host", "unix:///qualified.sock"]
    assert [command[index + 1] for index, item in enumerate(command) if item == "-f"] == [
        item["path"] for item in installed.profile["compose_files"]
    ]
    assert command[-4:] == ["exec", "-T", "postgres", "pg_dump"]
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote:2376")
    monkeypatch.setenv("DOCKER_TLS", "1")
    assert not {"DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS"} & stack.compose_environment().keys()
    old = Stack(installed.state)
    assert old.compose_command()[0:2] == ["docker", "compose"]
    assert old.compose_command().count("-f") == 1
    assert old.compose_environment() is None


@pytest.mark.parametrize(
    "change",
    [
        lambda item: item.update(docker_endpoint="tcp://remote:2376"),
        lambda item: item.update(origin="https://192.168.1.3:28443"),
        lambda item: item.update(secret="must-not-be-an-operational-field"),
        lambda item: item["containers"]["api"].update(image="latest"),
        lambda item: item.update(compose_files=item["compose_files"][:1]),
    ],
)
def test_invalid_profile_refuses_before_any_docker_or_mutation(installed, change):
    profile = copy.deepcopy(installed.profile)
    change(profile)
    installed.path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):
        release.ReleaseStack(installed.path)
    assert installed.calls == []


def test_file_drift_and_duplicate_json_keys_are_refused_before_docker(installed):
    (installed.source / "Caddyfile").write_text("changed trusted transport")
    with pytest.raises(ValueError, match="changed"):
        release.ReleaseStack(installed.path)
    installed.path.write_text('{"format":1,"format":1}')
    with pytest.raises(ValueError, match="Duplicate"):
        release.ReleaseStack(installed.path)
    assert installed.calls == []


@pytest.mark.parametrize(
    "change",
    [
        lambda values: values["api"].update(Id="d" * 64),
        lambda values: values["api"].update(Image="sha256:" + "d" * 64),
        lambda values: values["keycloak"]["Config"].update(Cmd=["start", "--import-realm"]),
        lambda values: values["api"]["Config"].update(
            Env=["AI_PROVIDER=gemini", "GEMINI_API_KEY=secret-canary"]
        ),
        lambda values: values["api"]["Config"]["Labels"].update(
            {"com.docker.compose.project": "other"}
        ),
    ],
)
def test_container_identity_image_and_configuration_drift_never_mutates(installed, change):
    change(installed.values)
    with pytest.raises(ValueError):
        installed.stack.start()
    assert not any(call[0] == "compose" for call in installed.calls)


def test_unexpected_running_service_refuses_instead_of_ignoring_an_extra_writer(installed):
    extra = copy.deepcopy(installed.values["api"])
    extra["Id"] = "e" * 64
    extra["Config"]["Labels"]["com.docker.compose.service"] = "unknown-writer"
    installed.values["unknown-writer"] = extra
    with pytest.raises(ValueError, match="Unexpected"):
        installed.stack.stop()
    assert not any(call[0] == "compose" for call in installed.calls)


def test_stop_closes_every_service_without_removing_containers_or_data(installed):
    identifiers = {name: value["Id"] for name, value in installed.values.items()}
    result = installed.stack.stop()
    assert result["result"] == "STOPPED" and result["data_removed"] is False
    assert all(
        not value["State"]["Running"] and value["State"]["Pid"] == 0
        for value in installed.values.values()
    )
    assert identifiers == {name: value["Id"] for name, value in installed.values.items()}
    operations = [call[1:] for call in installed.calls if call[0] == "compose"]
    assert operations[0] == ("stop", "gateway")
    assert operations[-1] == ("stop", "postgres")
    assert all(operation[0] == "stop" for operation in operations)


def test_writer_closure_requires_no_physical_pid_even_when_running_false(installed):
    for value in installed.values.values():
        value["State"].update(Running=False, Pid=0)
    installed.values["ai-worker"]["State"]["Pid"] = 123
    with pytest.raises(ValueError, match="processes"):
        installed.stack.assert_closed()


def test_start_reuses_existing_containers_and_does_not_provision_or_activate(installed):
    identifiers = {name: value["Id"] for name, value in installed.values.items()}
    report = installed.stack.start()
    assert report["https_api_issuer_ready"] is True
    assert identifiers == {name: value["Id"] for name, value in installed.values.items()}
    commands = [call for call in installed.calls if call[0] == "compose"]
    forbidden = {"build", "up", "run", "down", "rm", "provision", "activate", "--import-realm"}
    assert not any(forbidden & set(command) for command in commands)
    assert all(report["services"][name]["worker"]["fresh_success"] for name in release.E8)


def test_start_failure_keeps_ingress_and_all_writers_closed(installed, monkeypatch):
    monkeypatch.setattr(installed.stack, "https_ready", lambda: False)
    with pytest.raises(ValueError, match="HTTPS"):
        installed.stack.start()
    installed.stack.assert_closed()
    assert installed.values["postgres"]["State"]["Running"] is True


def test_status_is_factual_and_does_not_publish_env_ids_or_credentials(installed):
    report = installed.stack.status()
    serialized = json.dumps(report)
    assert "never-print-this" not in serialized and "sha256:" not in serialized
    assert installed.profile["engine_id"] not in serialized
    assert not any(
        call[:2] in {("compose", "start"), ("compose", "stop")} for call in installed.calls
    )


def test_operation_lock_refuses_overlap_without_deleting_existing_lock(installed):
    with release.operation(installed.path):
        with pytest.raises(FileExistsError):
            with release.operation(installed.path):
                pytest.fail("second writer entered")
        assert installed.path.with_suffix(".operation.lock").is_file()
    assert not installed.path.with_suffix(".operation.lock").exists()


def photo_tar(path, *, name=None, kind=tarfile.REGTYPE, size=None, mode=0o600):
    payload = b"\xff\xd8test-only\xff\xd9"
    with tarfile.open(path, "w") as archive:
        root = tarfile.TarInfo("photos")
        root.type, root.mode = tarfile.DIRTYPE, 0o700
        archive.addfile(root)
        member = tarfile.TarInfo(name or "photos/" + "a" * 32 + ".jpg")
        member.type, member.mode = kind, mode
        member.linkname = "../../external"
        member.size = len(payload) if size is None else size
        member.mtime = 1_700_000_000
        archive.addfile(
            member, io.BytesIO(payload) if kind == tarfile.REGTYPE and member.size else None
        )
    return payload


def test_optional_photo_restore_preserves_payload_and_retention_mtime_privately(tmp_path):
    archive = tmp_path / "photos.tar"
    payload = photo_tar(archive)
    target = tmp_path / "new-private"
    assert backup.restore_photos(archive, target) == {"files": 1, "bytes": len(payload)}
    restored = target / "photos" / ("a" * 32 + ".jpg")
    assert restored.read_bytes() == payload
    assert restored.stat().st_mtime == 1_700_000_000


@pytest.mark.parametrize(
    "name,kind,mode",
    [
        ("photos/../../outside", tarfile.REGTYPE, 0o600),
        ("/photos/outside", tarfile.REGTYPE, 0o600),
        ("photos/" + "a" * 32 + ".jpg", tarfile.SYMTYPE, 0o600),
        ("photos/" + "a" * 32 + ".jpg", tarfile.LNKTYPE, 0o600),
        ("photos/" + "a" * 32 + ".jpg", tarfile.REGTYPE, 0o644),
        ("photos/raw-original.png", tarfile.REGTYPE, 0o600),
    ],
)
def test_optional_photo_restore_rejects_links_traversal_raw_names_and_public_files(
    tmp_path, name, kind, mode
):
    archive = tmp_path / "bad.tar"
    photo_tar(archive, name=name, kind=kind, mode=mode)
    with pytest.raises(ValueError):
        backup.restore_photos(archive, tmp_path / "private-new")
    assert not (tmp_path / "outside").exists()


def test_capture_full_chain_closure_photo_hash_and_legacy_required_archives(
    installed, tmp_path, monkeypatch
):
    from calorie_app.health import EXPECTED_REVISION

    stack = installed.stack
    epoch = str(uuid4())
    queries = []

    def sql(database, query, **_):
        queries.append(query)
        if "pg_stat_activity" in query:
            stack.assert_closed()
            return "0"
        if "version_num" in query:
            return EXPECTED_REVISION
        if "sync_epoch" in query:
            return epoch
        if "count(*)" in query:
            return "2"
        return "[]"

    streams = []

    def execute(directory, command, *, output_path, environment=None):
        streams.append(command)
        if output_path.name == "photos.tar":
            photo_tar(output_path)
        else:
            output_path.write_bytes(b"binary fixture")

    monkeypatch.setattr(stack, "sql", sql)
    monkeypatch.setattr(backup, "execute", execute)
    target = tmp_path / "paired"
    result = stack.backup(target)
    assert result["writers_stopped"] is True and result["traffic_reopened"] is False
    stack.assert_closed()
    manifest = backup.verify_archive(target)
    assert manifest["format"] == 1 and backup.ARCHIVES <= manifest["files"].keys()
    assert manifest["optional_photos"] == {"format": 1, "archive": "photos.tar", "root": "photos"}
    assert manifest["files"]["photos.tar"]["sha256"] == backup.digest(target / "photos.tar")
    assert "release/runtime.json" in {name.removeprefix("config/") for name in manifest["files"]}
    for command in streams:
        assert command[:3] == ["docker", "--host", "unix:///qualified.sock"]
        assert command.count("-f") == 4
    assert any("photos:ro" in " ".join(command) for command in streams)
    assert installed.values["postgres"]["State"]["Running"] is True
    assert not any("e8n_activate" in query for query in queries)


def test_photo_marker_cannot_silently_ignore_or_invent_payload(tmp_path):
    # Missing legacy paired files are tested separately; this checks optional framing.
    manifest = {
        "format": 1,
        "writers_stopped": True,
        "source_epoch": str(uuid4()),
        "captured_at": "2026-10-31T00:00:00+00:00",
        "files": {},
    }
    for name in backup.ARCHIVES:
        path = tmp_path / name
        path.write_bytes(b"fixture")
        manifest["files"][name] = {"size": path.stat().st_size, "sha256": backup.digest(path)}
    manifest["optional_photos"] = {"format": 1, "archive": "photos.tar", "root": "photos"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="paired"):
        backup.verify_archive(tmp_path)
