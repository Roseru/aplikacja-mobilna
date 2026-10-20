import hashlib
import io
import json
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import offsite_package as package


@pytest.fixture
def prepared(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    files = {}
    for name in ("roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar", "config/api.env"):
        path = backup / name
        path.parent.mkdir(exist_ok=True)
        data = ("private fixture: " + name).encode()
        path.write_bytes(data)
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    manifest = {
        "format": 1,
        "writers_stopped": True,
        "captured_at": datetime.now(UTC).isoformat(),
        "source_epoch": str(uuid4()),
        "files": files,
    }
    (backup / "manifest.json").write_text(json.dumps(manifest))
    key = tmp_path / "keys" / "secret.key"
    package.generate_key(key)
    return backup, key, tmp_path / "backup.enc"


def test_authenticated_roundtrip_preserves_exact_declared_files(prepared, tmp_path):
    backup, key, encrypted = prepared
    (backup / "extra-private-log").write_text("not part of backup")
    receipt = package.pack(backup, encrypted, key)
    assert receipt["offsite_verified"] is False
    assert b"private fixture" not in encrypted.read_bytes()
    restored = tmp_path / "restored"
    assert package.unpack(encrypted, restored, key)["offsite_verified"] is False
    assert not (restored / "extra-private-log").exists()
    for path in restored.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (backup / path.relative_to(restored)).read_bytes()


@pytest.mark.parametrize("damage", ["ciphertext", "nonce", "header", "truncate", "wrong_key"])
def test_tamper_or_wrong_key_creates_no_plaintext(prepared, tmp_path, damage):
    backup, key, encrypted = prepared
    package.pack(backup, encrypted, key)
    data = bytearray(encrypted.read_bytes())
    if damage == "wrong_key":
        key = tmp_path / "other-key"
        key.write_bytes(AESGCM.generate_key(bit_length=256))
    elif damage == "truncate":
        data = data[:-1]
    else:
        index = {"header": 0, "nonce": len(package.MAGIC), "ciphertext": -1}[damage]
        data[index] ^= 1
    encrypted.write_bytes(data)
    output = tmp_path / "refused"
    with pytest.raises(ValueError):
        package.unpack(encrypted, output, key)
    assert not output.exists()


def test_changed_source_and_existing_package_are_refused(prepared):
    backup, key, encrypted = prepared
    package.pack(backup, encrypted, key)
    original = encrypted.read_bytes()
    with pytest.raises(FileExistsError):
        package.pack(backup, encrypted, key)
    assert encrypted.read_bytes() == original
    (backup / "roles.sql").write_text("corruption")
    with pytest.raises(ValueError, match="checksum"):
        package.pack(backup, encrypted.with_suffix(".new"), key)
    assert not encrypted.with_suffix(".new").exists()


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escaped", "file"),
        ("link", "link"),
        ("roles.sql", "duplicate"),
        ("NUL", "file"),
        ("config/key.", "file"),
    ],
)
def test_authenticated_unsafe_tar_is_still_refused(prepared, tmp_path, name, kind):
    backup, key, encrypted = prepared
    package.pack(backup, encrypted, key)
    members = package.decrypt(encrypted, key)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for member_name, data in members.items():
            info = tarfile.TarInfo(member_name)
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo(name)
        if kind == "link":
            info.type, info.linkname = tarfile.SYMTYPE, "../escaped"
        stream.addfile(info, io.BytesIO())
    nonce = b"\x01" * 12  # Unique only within this isolated test key.
    ciphertext = AESGCM(key.read_bytes()).encrypt(nonce, archive.getvalue(), package.MAGIC)
    encrypted.write_bytes(package.MAGIC + nonce + ciphertext)
    output = tmp_path / "refused"
    with pytest.raises(ValueError):
        package.unpack(encrypted, output, key)
    assert not output.exists()


def test_existing_restore_destination_is_preserved(prepared, tmp_path):
    backup, key, encrypted = prepared
    package.pack(backup, encrypted, key)
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep").write_text("preserve")
    with pytest.raises(FileExistsError):
        package.unpack(encrypted, output, key)
    assert list(output.iterdir()) == [output / "keep"]


@pytest.mark.parametrize("damage", ["format", "writers", "missing_pair"])
def test_invalid_paired_manifest_creates_no_restore_directory(prepared, tmp_path, damage):
    backup, key, encrypted = prepared
    package.pack(backup, encrypted, key)
    members = package.decrypt(encrypted, key)
    manifest = json.loads(members["manifest.json"])
    if damage == "format":
        manifest["format"] = 99
    elif damage == "writers":
        manifest["writers_stopped"] = False
    else:
        del manifest["files"]["keycloak.dump"]
        del members["keycloak.dump"]
    members["manifest.json"] = json.dumps(manifest).encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
    nonce = b"\x02" * 12
    ciphertext = AESGCM(key.read_bytes()).encrypt(nonce, archive.getvalue(), package.MAGIC)
    encrypted.write_bytes(package.MAGIC + nonce + ciphertext)
    output = tmp_path / "refused"
    with pytest.raises(ValueError):
        package.unpack(encrypted, output, key)
    assert not output.exists()
