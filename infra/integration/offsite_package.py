"""Encrypt a verified paired backup for delivery; never claims an offsite restore."""

import argparse
import hashlib
import io
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from backup import ARCHIVES, private_directory, verify_archive
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"CALORIE-OFFSITE1\n"
MAX_BYTES = 256 * 1024**2
MAX_FILES = 4096


def safe_name(name):
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 512
        or any(ord(char) < 32 for char in name)
        or "\\" in name
        or ":" in name
    ):
        raise ValueError("Invalid package member")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != name or name == ".":
        raise ValueError("Package member escaped backup")
    devices = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
    }
    if any(
        part.endswith((".", " ")) or part.split(".")[0].upper() in devices for part in path.parts
    ):
        raise ValueError("Nonportable backup member")
    return path


def bounded_read(path, maximum=MAX_BYTES):
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError("Regular source file required")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Package size limit exceeded")
    return data


def read_key(path):
    data = bounded_read(path, 32)
    if len(data) != 32:
        raise ValueError("Expected a private 256-bit key")
    return data


def generate_key(path):
    # A dedicated new directory receives restrictive Windows ACL/Linux permissions.
    private_directory(path.parent)
    with path.open("xb") as stream:
        stream.write(AESGCM.generate_key(bit_length=256))
    path.chmod(0o600)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest field")
        result[key] = value
    return result


def validate_members(members):
    if "manifest.json" not in members or len(members["manifest.json"]) > 1024**2:
        raise ValueError("Missing or oversized backup manifest")
    manifest = json.loads(members["manifest.json"], object_pairs_hook=unique)
    if manifest.get("format") != 1 or manifest.get("writers_stopped") is not True:
        raise ValueError("Incomplete paired backup")
    UUID(manifest["source_epoch"])
    datetime.fromisoformat(manifest["captured_at"])
    files = manifest["files"]
    if not isinstance(files, dict) or set(members) != set(files) | {"manifest.json"}:
        raise ValueError("Backup package member set differs from manifest")
    if not ARCHIVES <= set(files):
        raise ValueError("Missing paired archive")
    if "manifest.json" in files or len(members) > MAX_FILES:
        raise ValueError("Invalid backup member set")
    for name, expected in files.items():
        safe_name(name)
        data = members[name]
        if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError("Backup member checksum mismatch")
    return manifest


def pack(backup, output, key):
    backup = backup.resolve(strict=True)
    if key.resolve(strict=True).is_relative_to(backup):
        raise ValueError("Keep the encryption key outside the backup")
    manifest = verify_archive(backup)
    names = ["manifest.json", *manifest["files"]]
    if len(names) > MAX_FILES or len(names) != len(set(names)):
        raise ValueError("Invalid backup member set")
    members = {}
    total = 0
    for name in names:
        relative = safe_name(name)
        path = backup.joinpath(*relative.parts)
        if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
            raise ValueError("Redirected backup member")
        data = bounded_read(path)
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError("Backup exceeds bounded package limit")
        members[name] = data
    validate_members(members)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as stream:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.mode, info.size = 0o600, len(data)
            stream.addfile(info, io.BytesIO(data))
    plaintext = archive.getvalue()
    if len(plaintext) > MAX_BYTES:
        raise ValueError("Archive exceeds bounded package limit")
    nonce = os.urandom(12)
    encrypted = MAGIC + nonce + AESGCM(read_key(key)).encrypt(nonce, plaintext, MAGIC)
    with output.open("xb") as stream:
        stream.write(encrypted)
    output.chmod(0o600)
    return {
        "result": "PASS",
        "scope": "encrypted package prepared; no remote delivery verified",
        "package_sha256": hashlib.sha256(encrypted).hexdigest(),
        "backup_manifest_sha256": hashlib.sha256(members["manifest.json"]).hexdigest(),
        "bytes": len(encrypted),
        "offsite_verified": False,
    }


def decrypt(package, key):
    encrypted = bounded_read(package, MAX_BYTES + len(MAGIC) + 28)
    if not encrypted.startswith(MAGIC) or len(encrypted) < len(MAGIC) + 28:
        raise ValueError("Unsupported encrypted backup package")
    nonce = encrypted[len(MAGIC) : len(MAGIC) + 12]
    try:
        plaintext = AESGCM(read_key(key)).decrypt(nonce, encrypted[len(MAGIC) + 12 :], MAGIC)
    except InvalidTag:
        raise ValueError("Backup authentication failed") from None
    members, total = {}, 0
    # Uncompressed TAR avoids decompression bombs. No extractall or link following.
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:") as archive:
        for member in archive:
            safe_name(member.name)
            if not member.isfile() or member.name in members or len(members) >= MAX_FILES:
                raise ValueError("Unexpected backup member type or duplicate")
            total += member.size
            if member.size < 0 or total > MAX_BYTES:
                raise ValueError("Backup member size limit exceeded")
            data = archive.extractfile(member).read(member.size + 1)
            if len(data) != member.size:
                raise ValueError("Truncated backup member")
            members[member.name] = data
    validate_members(members)
    return members


def unpack(package, output, key):
    members = decrypt(package, key)  # Authenticate and validate before creating output.
    private_directory(output)  # Refuses any existing destination.
    for name, data in members.items():
        path = output.joinpath(*safe_name(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        path.chmod(0o600)
    verify_archive(output)
    return {"result": "PASS", "scope": "authenticated local unpack", "offsite_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("key", "pack", "unpack", "verify"))
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "key":
            generate_key(args.key)
            result = {"result": "PASS", "scope": "private key created; retain separately"}
        elif args.action == "pack":
            if args.backup is None or args.output is None:
                parser.error("pack requires --backup and --output")
            result = pack(args.backup, args.output, args.key)
        else:
            if args.package is None:
                parser.error("verify/unpack requires --package")
            if args.action == "unpack":
                if args.output is None:
                    parser.error("unpack requires a new --output")
                result = unpack(args.package, args.output, args.key)
            else:
                decrypt(args.package, args.key)
                result = {
                    "result": "PASS",
                    "scope": "authenticated package",
                    "offsite_verified": False,
                }
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        parser.exit(1, "Encrypted backup operation failed; no offsite acceptance\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
