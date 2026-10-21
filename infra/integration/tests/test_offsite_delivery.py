import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import offsite_delivery as delivery
from maintenance import OWNER
from offsite_package import generate_key


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def settings(tmp_path):
    root, operations, outgoing = (tmp_path / name for name in ("backups", "operations", "outgoing"))
    for directory in (root, operations, outgoing):
        directory.mkdir()
    save(root / "owner.json", {"owner": OWNER, "project": "synthetic"})
    backup = root / "auto-test"
    backup.mkdir()
    files = {}
    for name in ("roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar"):
        data = b"synthetic private backup"
        (backup / name).write_bytes(data)
        files[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    captured = datetime.now(UTC).isoformat()
    save(
        backup / "manifest.json",
        {
            "format": 1,
            "writers_stopped": True,
            "captured_at": captured,
            "source_epoch": str(uuid4()),
            "files": files,
        },
    )
    save(backup / "automatic.json", {"owner": OWNER, "result": "PASS"})
    save(
        operations / "backup-receipt.json",
        {
            "result": "PASS",
            "verified_at": captured,
            "backup": str(backup),
            "archive_integrity": True,
            "restore_rehearsal": True,
            "services_resumed": True,
        },
    )
    key = tmp_path / "keys" / "backup.key"
    generate_key(key)
    return {
        "operations": str(operations),
        "backups": str(root),
        "outgoing": str(outgoing),
        "key": str(key),
        "project": "synthetic",
        "dropbox_folder": "/Calorie O3 backups",
        "receipt": str(tmp_path / "offsite-receipt.json"),
    }


def remote(prepared):
    return {
        "path": prepared["destination_path"],
        "file_id": "id:synthetic",
        "modified_time": datetime.now(UTC).isoformat(),
    }


def test_prepare_reuses_exact_ciphertext_and_never_claims_delivery(settings):
    first = delivery.prepare(settings)
    data = Path(first["source_file"]).read_bytes()
    second = delivery.prepare(settings)
    assert first == second and data == Path(second["source_file"]).read_bytes()
    assert first["result"] == "PREPARED" and first["offsite_verified"] is False
    assert not Path(settings["receipt"]).exists()
    assert first["destination_path"].startswith("/Calorie O3 backups/auto-")


@pytest.mark.parametrize(
    "field", ["result", "archive_integrity", "restore_rehearsal", "services_resumed"]
)
def test_incomplete_local_backup_refused(settings, field):
    path = Path(settings["operations"]) / "backup-receipt.json"
    receipt = delivery.read(path)
    receipt[field] = "FAIL" if field == "result" else False
    save(path, receipt)
    with pytest.raises(ValueError):
        delivery.prepare(settings)
    assert list(Path(settings["outgoing"]).iterdir()) == []


@pytest.mark.parametrize("age", [25 * 3600, -300])
def test_recent_verification_cannot_hide_stale_or_future_capture(settings, age):
    manifest = Path(settings["backups"]) / "auto-test" / "manifest.json"
    data = delivery.read(manifest)
    data["captured_at"] = (datetime.now(UTC) - timedelta(seconds=age)).isoformat()
    save(manifest, data)
    with pytest.raises(ValueError, match="24 hours"):
        delivery.prepare(settings)


def test_wrong_owner_or_changed_ciphertext_refused(settings):
    prepared = delivery.prepare(settings)
    Path(prepared["source_file"]).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        delivery.prepare(settings)
    save(Path(settings["backups"]) / "owner.json", {"owner": OWNER, "project": "other"})
    with pytest.raises(ValueError, match="owner"):
        delivery.prepare(settings)


def test_verified_independent_download_requires_restore_before_receipt(
    settings, tmp_path, monkeypatch
):
    prepared = delivery.prepare(settings)
    downloaded = tmp_path / "downloaded.enc"
    shutil.copyfile(prepared["source_file"], downloaded)
    calls = []

    def rehearse(directory):
        calls.append(directory)
        assert (directory / "keycloak.dump").read_bytes() == b"synthetic private backup"
        assert not Path(settings["receipt"]).exists()
        return {"result": "PASS", "traffic_reopened": False, "offline_rehearsal_seconds": 1.23}

    monkeypatch.setattr(delivery, "rehearse", rehearse)
    receipt = delivery.accept_download(settings, prepared, downloaded, remote(prepared))
    assert len(calls) == 1 and receipt["offsite_verified"] is True
    assert receipt["independent_key_recovery_verified"] is False
    assert receipt["production_rpo_rto"] is False
    assert delivery.read(settings["receipt"]) == receipt


@pytest.mark.parametrize("damage", ["same_file", "path", "id", "ciphertext", "captured_at"])
def test_false_remote_provenance_or_changed_package_cannot_create_receipt(
    settings, tmp_path, damage
):
    prepared = delivery.prepare(settings)
    downloaded = tmp_path / "downloaded.enc"
    shutil.copyfile(prepared["source_file"], downloaded)
    metadata = remote(prepared)
    if damage == "same_file":
        downloaded = Path(prepared["source_file"])
    elif damage == "path":
        metadata["path"] = "/other.enc"
    elif damage == "id":
        metadata["file_id"] = "not a connector ID"
    elif damage == "ciphertext":
        downloaded.write_bytes(b"tampered")
    else:
        prepared["archive_captured_at"] = datetime.now(UTC).isoformat()
    with pytest.raises(ValueError):
        delivery.accept_download(settings, prepared, downloaded, metadata)
    assert not Path(settings["receipt"]).exists()


def test_failed_restore_preserves_previous_receipt(settings, tmp_path, monkeypatch):
    prepared = delivery.prepare(settings)
    downloaded = tmp_path / "downloaded.enc"
    shutil.copyfile(prepared["source_file"], downloaded)
    save(Path(settings["receipt"]), {"previous": "preserve"})
    monkeypatch.setattr(delivery, "rehearse", lambda _: {"result": "FAIL"})
    with pytest.raises(ValueError, match="restore"):
        delivery.accept_download(settings, prepared, downloaded, remote(prepared))
    assert delivery.read(settings["receipt"]) == {"previous": "preserve"}


def test_private_key_kit_is_only_preparation_and_cannot_overwrite(settings, tmp_path):
    destination = tmp_path / "new-kit"
    receipt = delivery.recovery_kit(settings, destination)
    assert receipt["independent_key_recovery_verified"] is False
    assert (destination / "recovery.key").read_bytes() == Path(settings["key"]).read_bytes()
    with pytest.raises(FileExistsError):
        delivery.recovery_kit(settings, destination)
