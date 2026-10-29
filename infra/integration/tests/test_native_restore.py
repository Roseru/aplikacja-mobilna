"""Fail-before-mutation tests for the additive native offline restore transport."""

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infra.local.integration import rehearse_restore, restore


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(restore.native, "ROOT", tmp_path)
    folder = tmp_path / ".tools/archive"
    folder.mkdir(parents=True)
    (folder / "roles.sql").write_text("CREATE ROLE postgres;\n")
    for name in ("calorie_app.dump", "keycloak.dump"):
        (folder / name).write_bytes(b"synthetic dump boundary fixture")
    write_tar(folder / "catalog.tar", "catalog/manifest.json")
    manifest = {
        "format": 1,
        "transport": restore.FORMAT,
        "revision": restore.EXPECTED_REVISION,
        "source_owner": str(uuid4()),
        "source_epoch": str(uuid4()),
        "captured_at": "2026-10-29T00:00:00+00:00",
        "writers_stopped": True,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    rehash(folder)
    return folder


def write_tar(path, member, *, kind=tarfile.REGTYPE, second=None):
    with tarfile.open(path, "w") as archive:
        root = tarfile.TarInfo("catalog")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name in (member, second):
            if name is None:
                continue
            item = tarfile.TarInfo(name)
            item.type = kind
            item.size = 2 if kind == tarfile.REGTYPE else 0
            archive.addfile(item, io.BytesIO(b"{}") if item.size else None)


def rehash(folder):
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"] = {
        name: {
            "size": (folder / name).stat().st_size,
            "sha256": restore.digest(folder / name),
        }
        for name in ("roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar")
        if (folder / name).exists()
    }
    path.write_text(json.dumps(manifest))


def refuse_before_create(archive, monkeypatch, match, target=None):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Target creation reached before refusal")

    monkeypatch.setattr(restore.OwnedPG, "create", forbidden)
    with pytest.raises((ValueError, FileExistsError), match=match):
        restore.restore(
            archive, target or archive.parent / "target", Path("unused"), 55432
        )


def test_valid_native_archive_reuses_shared_verifier(archive):
    assert restore.verify_native_archive(archive)["transport"] == restore.FORMAT


@pytest.mark.parametrize(
    "name", ["roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar"]
)
def test_missing_pair_member_refuses_before_create(archive, monkeypatch, name):
    (archive / name).unlink()
    rehash(archive)
    refuse_before_create(archive, monkeypatch, "archive member")


def test_same_size_tamper_refuses_before_create(archive, monkeypatch):
    path = archive / "keycloak.dump"
    path.write_bytes(b"x" * path.stat().st_size)
    refuse_before_create(archive, monkeypatch, "checksum")


def test_existing_target_refuses_before_create(archive, monkeypatch):
    target = archive.parent / "target"
    target.mkdir()
    refuse_before_create(archive, monkeypatch, "Existing target", target)


@pytest.mark.parametrize(
    "member",
    [
        "../escape",
        "/catalog/x",
        "catalog/../x",
        "catalog/./x",
        "catalog//x",
        "catalog/x.",
        "catalog/x ",
        "catalog/a:stream",
        "catalog/NUL",
        "catalog/con.txt",
        "catalog/COM1.bin",
        "catalog/LPT9",
        "catalog/a\\b",
        "catalog/a?b",
        "catalog/a\x01b",
    ],
)
def test_dangerous_catalog_refuses_before_create(archive, monkeypatch, member):
    write_tar(archive / "catalog.tar", member)
    rehash(archive)
    refuse_before_create(archive, monkeypatch, "Unsafe catalog")


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE]
)
def test_special_catalog_members_refuse_before_create(archive, monkeypatch, kind):
    write_tar(archive / "catalog.tar", "catalog/linked", kind=kind)
    rehash(archive)
    refuse_before_create(archive, monkeypatch, "Unsafe catalog")


def test_case_collision_refuses_before_create(archive, monkeypatch):
    write_tar(archive / "catalog.tar", "catalog/A", second="catalog/a")
    rehash(archive)
    refuse_before_create(archive, monkeypatch, "Unsafe catalog")


def test_catalog_file_parent_refuses_before_create(archive, monkeypatch):
    write_tar(archive / "catalog.tar", "catalog/file", second="catalog/file/nested")
    rehash(archive)
    refuse_before_create(archive, monkeypatch, "parent directory")


def test_catalog_root_must_be_directory(archive, monkeypatch):
    with tarfile.open(archive / "catalog.tar", "w") as tar:
        item = tarfile.TarInfo("catalog")
        item.size = 2
        tar.addfile(item, io.BytesIO(b"{}"))
    rehash(archive)
    refuse_before_create(archive, monkeypatch, "Missing catalog root")


def test_unexpected_manifest_path_never_read(archive, monkeypatch):
    path = archive / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["../secret"] = {"size": 1, "sha256": "0" * 64}
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        restore, "verify_archive", lambda *_: pytest.fail("Unsafe shared read")
    )
    refuse_before_create(archive, monkeypatch, "archive member")


@pytest.mark.parametrize(
    "path", ["bad:stream/x", "bad./x", "bad /x", "//server/share/x", "\\\\?\\C:\\x"]
)
def test_aliases_rejected_before_filesystem(path, monkeypatch):
    monkeypatch.setattr(
        restore.native, "confined", lambda *_: pytest.fail("Alias reached filesystem")
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        restore.owned_path(path)


def test_overlapping_target_refuses_before_create(archive, monkeypatch):
    refuse_before_create(archive, monkeypatch, "overlap", archive / "nested-target")


def test_foreign_state_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(restore.native, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="under this checkout"):
        restore.OwnedPG(tmp_path / "foreign")


def test_reused_pid_refuses_before_stop(archive, monkeypatch):
    pg = object.__new__(restore.OwnedPG)
    pg.state = archive
    pg.data = archive
    pg.config = {"process": {"pid": 12, "created": 10, "executable": "postgres.exe"}}
    monkeypatch.setattr(
        restore.native, "identity", lambda _: {"pid": 12, "created": 11}
    )
    pg.command = lambda *_args, **_kw: pytest.fail("Foreign stop reached command")
    with pytest.raises(ValueError, match="PID identity"):
        pg.stop()


def test_lifecycle_lock_refuses_overlap(archive):
    pg = object.__new__(restore.OwnedPG)
    pg.state = archive
    with pg.operation(), pytest.raises(OSError), pg.operation():
        pytest.fail("Concurrent operation admitted")


def test_late_source_mismatch_cannot_preserve_pass(monkeypatch):
    receipt = {"result": "PASS", "stage": "previous"}
    binding = {"commit": "a" * 40, "adapter_sha256": {"restore.py": "original"}}
    monkeypatch.setattr(
        rehearse_restore.native,
        "source",
        lambda _: binding | {"adapter_sha256": {"restore.py": "changed"}},
    )
    with pytest.raises(ValueError, match="Source changed"):
        rehearse_restore.finish_checks(receipt, binding, paired={"result": "PASS"})
    assert (
        receipt["result"] == "FAIL"
        and receipt["stage"] == "verify_final_source_binding"
    )
    assert "paired" not in receipt


def test_cleanup_failure_is_preserved_and_other_own_cleanup_continues():
    receipt = {"result": "PASS"}
    stopped = []

    def fail():
        raise PermissionError("identity differs")

    clusters = [
        SimpleNamespace(
            config={"owner": "first"}, stop=lambda: stopped.append("first")
        ),
        SimpleNamespace(config={"owner": "second"}, stop=fail),
    ]
    errors = rehearse_restore.stop_owned_clusters(clusters, receipt)
    assert receipt["result"] == "FAIL" and stopped == ["first"]
    assert receipt["stopped_owned_clusters"] == ["first"]
    assert (
        errors
        == receipt["cleanup_errors"]
        == [{"owner": "second", "error_kind": "PermissionError"}]
    )
