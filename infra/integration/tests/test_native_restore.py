"""Fail-before-mutation tests for the additive native offline restore transport."""

import io
import json
import os
import subprocess
import sys
import tarfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infra.local.integration import rehearse_restore, restore, restore_trust

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from tests.unit.test_deletion_ledger_contract import fence_pin, fixtures


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(restore.native, "ROOT", tmp_path)
    folder = tmp_path / ".tools/archive"
    folder.mkdir(parents=True)
    (folder / "roles.sql").write_text("CREATE ROLE postgres;\n", newline="\n")
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


def rehash(folder, *, update_pin=True):
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
    trust, batch, backup, cutoff = fixtures()
    manifest.setdefault(
        "ledger_backup",
        trust.identity()
        | {
            "issuer": trust.issuer,
            "sequence": backup["sequence"],
            "chain_hash": backup["chain_hash"],
        },
    )
    path.write_text(json.dumps(manifest))
    if update_pin:
        raw = trust.identity() | {
            "issuer": trust.issuer,
            "source_key": trust.source_key.hex(),
            "ack_key": trust.ack_key.hex(),
        }
        value = {
            "format": restore_trust.FORMAT,
            "archive_manifest_sha256": restore.digest(path),
            "source_owner": manifest["source_owner"],
            "ledger": {
                "trust": raw,
                "envelopes": [batch],
                "backup_point": backup,
                "cutoff": cutoff,
                "fence_pin": fence_pin(trust).fields(),
            },
        }
        (folder.parent / "trusted-checkpoint.json").write_text(json.dumps(value))


def refuse_before_create(archive, monkeypatch, match, target=None):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Target creation reached before refusal")

    monkeypatch.setattr(restore.OwnedPG, "create", forbidden)
    with pytest.raises((ValueError, FileExistsError), match=match):
        restore.restore(
            archive,
            target or archive.parent / "target",
            Path("unused"),
            55432,
            checkpoint=archive.parent / "trusted-checkpoint.json",
            checkpoint_sha256=restore.digest(archive.parent / "trusted-checkpoint.json"),
        )


def test_self_consistent_archive_replacement_refuses_independent_pin(archive, monkeypatch):
    (archive / "roles.sql").write_text("CREATE ROLE postgres;\n-- replaced privileged SQL\n")
    rehash(archive, update_pin=False)
    refuse_before_create(archive, monkeypatch, "independently captured pin")


@pytest.mark.parametrize("field", ["backup_point", "cutoff", "fence_pin", "envelopes"])
def test_trusted_checkpoint_invalid_ledger_refuses_before_create(archive, monkeypatch, field):
    path = archive.parent / "trusted-checkpoint.json"
    value = json.loads(path.read_text())
    if field == "envelopes":
        value["ledger"][field] = []
    elif field == "fence_pin":
        value["ledger"][field]["fence_id"] = str(uuid4())
    else:
        value["ledger"][field]["chain_hash"] = "f" * 64
    path.write_text(json.dumps(value))
    refuse_before_create(archive, monkeypatch, "unauthenticated|missing|mismatch")


def test_checkpoint_tamper_cannot_change_external_sha(archive, monkeypatch):
    path = archive.parent / "trusted-checkpoint.json"
    expected = restore.digest(path)
    path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(restore.OwnedPG, "create", lambda *_: pytest.fail("Create reached"))
    with pytest.raises(ValueError, match="checkpoint checksum"):
        restore.restore(
            archive,
            archive.parent / "target",
            Path("unused"),
            55432,
            checkpoint=path,
            checkpoint_sha256=expected,
        )
    assert not (archive.parent / "target").exists()


def test_missing_checkpoint_pin_refuses_before_any_target(archive, monkeypatch):
    monkeypatch.setattr(restore.OwnedPG, "create", lambda *_: pytest.fail("Create reached"))
    with pytest.raises(ValueError, match="SHA256 required"):
        restore.restore(
            archive,
            archive.parent / "target",
            Path("unused"),
            55432,
            checkpoint=archive.parent / "missing.json",
            checkpoint_sha256=None,
        )
    assert not (archive.parent / "target").exists()


def test_missing_external_checkpoint_file_refuses_before_create(archive, monkeypatch):
    monkeypatch.setattr(restore.OwnedPG, "create", lambda *_: pytest.fail("Create reached"))
    with pytest.raises(FileNotFoundError):
        restore.restore(
            archive,
            archive.parent / "target",
            Path("unused"),
            55432,
            checkpoint=archive.parent / "missing.json",
            checkpoint_sha256="0" * 64,
        )
    assert not (archive.parent / "target").exists()


def test_linked_manifest_refuses_before_manifest_digest(archive, monkeypatch):
    original = restore_trust.native.confined
    original_read = Path.read_bytes

    def confined(path):
        if Path(path) == archive / "manifest.json":
            raise ValueError("Linked state paths are refused")
        return original(path)

    def no_manifest_read(path):
        if Path(path) == archive / "manifest.json":
            pytest.fail("Linked manifest was read before refusal")
        return original_read(path)

    monkeypatch.setattr(restore_trust.native, "confined", confined)
    monkeypatch.setattr(Path, "read_bytes", no_manifest_read)
    refuse_before_create(archive, monkeypatch, "Linked state paths")


def test_independently_valid_ledger_cannot_be_mixed_with_other_capture(archive, monkeypatch):
    path = archive / "manifest.json"
    value = json.loads(path.read_text())
    value["ledger_backup"]["stream_id"] = str(uuid4())
    path.write_text(json.dumps(value))
    # Trusted outer digest still cannot combine independently valid stream B with DB A.
    pinpath = archive.parent / "trusted-checkpoint.json"
    pin = json.loads(pinpath.read_text())
    pin["archive_manifest_sha256"] = restore.digest(path)
    pinpath.write_text(json.dumps(pin))
    refuse_before_create(archive, monkeypatch, "trusted ledger backup point")


def test_valid_independent_checkpoint_reaches_only_new_target_creation(archive, monkeypatch):
    class ReachedNewTarget(Exception):
        pass

    def create(*_args):
        raise ReachedNewTarget

    monkeypatch.setattr(restore.OwnedPG, "create", create)
    with pytest.raises(ReachedNewTarget):
        pin = archive.parent / "trusted-checkpoint.json"
        restore.restore(
            archive,
            archive.parent / "target",
            Path("unused"),
            55432,
            checkpoint=pin,
            checkpoint_sha256=restore.digest(pin),
        )


def test_valid_native_archive_reuses_shared_verifier(archive):
    assert restore.verify_native_archive(archive)["transport"] == restore.FORMAT


@pytest.mark.parametrize("name", ["roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar"])
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
    pinpath = archive.parent / "trusted-checkpoint.json"
    pin = json.loads(pinpath.read_text())
    pin["archive_manifest_sha256"] = restore.digest(path)
    pinpath.write_text(json.dumps(pin))
    monkeypatch.setattr(restore, "verify_archive", lambda *_: pytest.fail("Unsafe shared read"))
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
    monkeypatch.setattr(restore.native, "identity", lambda _: {"pid": 12, "created": 11})
    pg.command = lambda *_args, **_kw: pytest.fail("Foreign stop reached command")
    with pytest.raises(ValueError, match="PID identity"):
        pg.stop()


def test_lifecycle_lock_refuses_overlap(archive):
    pg = object.__new__(restore.OwnedPG)
    pg.state = archive
    with pg.operation(), pytest.raises(OSError), pg.operation():
        pytest.fail("Concurrent operation admitted")


def test_checkpoint_and_manifest_hash_parse_same_single_read(archive, monkeypatch):
    checkpoint = archive.parent / "trusted-checkpoint.json"
    expected = restore.digest(checkpoint)
    manifest = archive / "manifest.json"
    original_read = Path.read_bytes
    counts = {checkpoint: 0, manifest: 0}

    def read_once(path):
        raw = original_read(path)
        if path in counts:
            counts[path] += 1
            path.write_bytes(b"untrusted replacement after first read")
        return raw

    original_text = Path.read_text

    def no_reopen(path, *args, **kwargs):
        if path in counts:
            pytest.fail("Authenticated input reopened for parsing")
        return original_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_once)
    monkeypatch.setattr(Path, "read_text", no_reopen)
    verified = restore_trust.preflight(archive, checkpoint, expected)
    assert verified["_manifest"]["transport"] == restore.FORMAT
    assert counts == {checkpoint: 1, manifest: 1}


def test_payload_replaced_during_copy_refuses_before_target(archive, monkeypatch):
    original = restore.copy_payload

    def swapped(source, destination, expected):
        if source.name == "roles.sql":
            source.write_text("CREATE ROLE postgres;\n-- attacker substitution")
            rehash(source.parent, update_pin=False)
        return original(source, destination, expected)

    monkeypatch.setattr(restore, "copy_payload", swapped)
    refuse_before_create(archive, monkeypatch, "changed while copying")
    assert not (archive.parent / "target").exists()


def test_original_swap_after_sealing_cannot_change_executed_inputs(archive, monkeypatch):
    expected = {
        name: (archive / name).read_bytes()
        for name in ("roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar")
    }
    checkpoint = archive.parent / "trusted-checkpoint.json"
    checkpoint_sha = restore.digest(checkpoint)
    dummy = SimpleNamespace(seal=lambda: None, operation=lambda: nullcontext())

    def create(*_args):
        for name in expected:
            (archive / name).write_bytes(b"untrusted original replacement after sealed snapshot")
        (archive / "manifest.json").write_bytes(b"invalid original manifest")
        checkpoint.write_bytes(b"invalid original checkpoint")
        return dummy

    def execute_into(pg, staged, manifest, roles, pin):
        assert staged != archive
        assert roles.encode() == expected["roles.sql"]
        assert all((staged / name).read_bytes() == raw for name, raw in expected.items())
        return pg, {"result": "PASS", "only_trusted_sealed_bytes_used": True}

    monkeypatch.setattr(restore.OwnedPG, "create", create)
    monkeypatch.setattr(restore, "_restore_into", execute_into)
    _, result = restore.restore(
        archive,
        archive.parent / "target",
        Path("unused"),
        55432,
        checkpoint=checkpoint,
        checkpoint_sha256=checkpoint_sha,
    )
    assert result["only_trusted_sealed_bytes_used"]


def test_witness_hash_and_parse_use_one_read(archive, monkeypatch):
    folder = archive.parent / "witness"
    folder.mkdir()
    path = folder / "observation.json"
    path.write_bytes(b'{"fact":"original trusted witness"}')
    state = {
        "witness_directory": str(folder),
        "witness_files": {path.name: restore.digest(path)},
    }
    original = Path.read_bytes
    reads = []

    def replace_after_read(item):
        raw = original(item)
        if item == path:
            reads.append(item)
            item.write_bytes(b'{"fact":"replacement after hash"}')
        return raw

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    assert restore_trust.read_witness(state, path.name) == {"fact": "original trusted witness"}
    assert reads == [path]


def test_restore_cli_has_no_missing_checkpoint_bypass(archive):
    root = Path(__file__).resolve().parents[3]
    environment = restore.native.clean_env() | {
        "PYTHONPATH": os.pathsep.join((str(root), str(root / "backend/src")))
    }
    target = archive.parent / "cli-target"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "infra.local.integration.restore",
            "restore",
            "--archive",
            str(archive),
            "--state",
            str(target),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        **restore.native.FLAGS,
    )
    assert result.returncode == 2 and "external --checkpoint" in result.stderr
    assert not target.exists()


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
    assert receipt["result"] == "FAIL" and receipt["stage"] == "verify_final_source_binding"
    assert "paired" not in receipt


def test_cleanup_failure_is_preserved_and_other_own_cleanup_continues():
    receipt = {"result": "PASS"}
    stopped = []

    def fail():
        raise PermissionError("identity differs")

    clusters = [
        SimpleNamespace(config={"owner": "first"}, stop=lambda: stopped.append("first")),
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
