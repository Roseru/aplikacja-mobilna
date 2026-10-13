import io
import json
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup import (  # noqa: E402
    ARCHIVES,
    digest,
    private_directory,
    restore_catalog,
    verify_archive,
)


def archive_fixture(directory):
    files = {}
    for name in ARCHIVES:
        path = directory / name
        path.write_bytes(b"owned fixture contents")
        files[name] = {"size": path.stat().st_size, "sha256": digest(path)}
    manifest = {
        "format": 1,
        "writers_stopped": True,
        "source_epoch": str(uuid4()),
        "captured_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_integrity_rejects_same_size_tampering(tmp_path):
    manifest = archive_fixture(tmp_path)
    assert verify_archive(tmp_path) == manifest
    path = tmp_path / "keycloak.dump"
    original = path.read_bytes()
    path.write_bytes(b"X" + original[1:])
    with pytest.raises(ValueError, match="checksum"):
        verify_archive(tmp_path)


def test_missing_paired_archive_is_not_partial_success(tmp_path):
    manifest = archive_fixture(tmp_path)
    del manifest["files"]["keycloak.dump"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Missing paired"):
        verify_archive(tmp_path)


def test_incomplete_capture_is_rejected(tmp_path):
    manifest = archive_fixture(tmp_path)
    manifest["writers_stopped"] = False
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Incomplete"):
        verify_archive(tmp_path)


def test_manifest_cannot_escape_private_directory(tmp_path):
    directory = tmp_path / "backup"
    directory.mkdir()
    outside = tmp_path / "untouched"
    outside.write_bytes(b"private external file")
    manifest = archive_fixture(directory)
    manifest["files"]["../untouched"] = {"size": outside.stat().st_size, "sha256": digest(outside)}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid archive path"):
        verify_archive(directory)
    assert outside.read_bytes() == b"private external file"


def test_existing_backup_directory_is_preserved(tmp_path):
    marker = tmp_path / "marker"
    marker.write_text("existing data")
    with pytest.raises(FileExistsError):
        private_directory(tmp_path)
    assert marker.read_text() == "existing data"


def test_catalog_restores_binary_content(tmp_path):
    archive = tmp_path / "catalog.tar"
    payload = b"\x00\xffsigned catalog artifact\n"
    with tarfile.open(archive, "w") as output:
        entry = tarfile.TarInfo("catalog/release/package.gz")
        entry.size = len(payload)
        output.addfile(entry, io.BytesIO(payload))
    restore_catalog(archive, tmp_path / "restored")
    assert (tmp_path / "restored/catalog/release/package.gz").read_bytes() == payload


@pytest.mark.parametrize(
    "name,kind",
    [
        ("catalog/../../outside", tarfile.REGTYPE),
        ("/catalog/outside", tarfile.REGTYPE),
        ("catalog-other/outside", tarfile.REGTYPE),
        ("catalog/link", tarfile.SYMTYPE),
        ("catalog/hardlink", tarfile.LNKTYPE),
        ("catalog/device", tarfile.CHRTYPE),
    ],
)
def test_catalog_rejects_traversal_links_and_devices(tmp_path, name, kind):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as output:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "../../outside"
        output.addfile(entry)
    with pytest.raises(ValueError):
        restore_catalog(archive, tmp_path / "restored")
    assert not (tmp_path / "outside").exists()
