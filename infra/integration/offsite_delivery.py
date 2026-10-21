"""Prepare immutable encrypted uploads and accept only downloaded, restored deliveries.

Cloud credentials stay in the connected file service. This tool never uploads,
deletes remote files, or infers remote success from the presence of a local file.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup import private_directory, rehearse, verify_archive
from maintenance import OWNER, lock
from monitor import write
from offsite_package import bounded_read, decrypt, pack, read_key, unpack


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def current_time():
    return datetime.now(UTC)


def fresh(value):
    captured = datetime.fromisoformat(value)
    if (
        captured.utcoffset() is None
        or not 0 <= (current_time() - captured).total_seconds() <= 86400
    ):
        raise ValueError("A backup captured within 24 hours is required")
    return captured


def physical(path):
    path = Path(path)
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("Redirected private path refused")
    return path.resolve(strict=True)


def prepare(settings):
    operations = physical(settings["operations"])
    root = physical(settings["backups"])
    output = physical(settings["outgoing"])
    key = physical(settings["key"])
    owner = read(root / "owner.json")
    if owner != {"owner": OWNER, "project": settings["project"]}:
        raise ValueError("Backup owner differs")
    prefix = settings["dropbox_folder"]
    if prefix != "/Calorie O3 backups":
        raise ValueError("Explicit approved Dropbox folder required")
    with lock(operations):
        receipt = read(operations / "backup-receipt.json")
        if receipt.get("result") != "PASS" or not all(
            receipt.get(k) is True
            for k in ("archive_integrity", "restore_rehearsal", "services_resumed")
        ):
            raise ValueError("A verified complete local backup is required")
        fresh(receipt["verified_at"])
        backup = physical(receipt["backup"])
        if backup.parent != root or read(backup / "automatic.json") != {
            "owner": OWNER,
            "result": "PASS",
        }:
            raise ValueError("Only owned scheduled backups may be delivered")
        manifest = verify_archive(backup)
        captured = fresh(manifest["captured_at"])
        manifest_hash = hashlib.sha256((backup / "manifest.json").read_bytes()).hexdigest()
        filename = f"auto-{captured.astimezone(UTC):%Y%m%dT%H%M%SZ}-{manifest_hash[:12]}.enc"
        package = output / filename
        if package.exists():
            members = decrypt(package, key)
            if hashlib.sha256(members["manifest.json"]).hexdigest() != manifest_hash:
                raise ValueError("Existing encrypted delivery has another manifest")
        else:
            pack(backup, package, key)
        result = {
            "format": 1,
            "result": "PREPARED",
            "source_file": str(package),
            "destination_path": prefix + "/" + filename,
            "package_sha256": hashlib.sha256(bounded_read(package, 256 * 1024**2 + 64)).hexdigest(),
            "backup_manifest_sha256": manifest_hash,
            "archive_captured_at": manifest["captured_at"],
            "offsite_verified": False,
        }
        write(output / (filename + ".json"), result)
        write(output / "pending.json", result)
        return result


def accept_download(settings, prepared, downloaded, remote):
    """Trusted connector supplies the metadata and actual independently downloaded file.

    Metadata is provenance supplied by that connector's operator, not a proof
    that this local CLI can authenticate to Dropbox by itself.
    """
    if prepared.get("format") != 1 or prepared.get("result") != "PREPARED":
        raise ValueError("Prepared delivery required")
    fresh(prepared["archive_captured_at"])
    if (
        remote.get("path", "").casefold() != prepared["destination_path"].casefold()
        or not isinstance(remote.get("file_id"), str)
        or not remote["file_id"].startswith("id:")
    ):
        raise ValueError("Connector metadata does not identify the prepared destination")
    downloaded = physical(downloaded)
    if downloaded == physical(prepared["source_file"]):
        raise ValueError("An independent download file is required")
    digest = hashlib.sha256(bounded_read(downloaded, 256 * 1024**2 + 64)).hexdigest()
    if (
        not re.fullmatch("[0-9a-f]{64}", prepared["package_sha256"])
        or digest != prepared["package_sha256"]
    ):
        raise ValueError("Downloaded ciphertext differs")
    key = physical(settings["key"])
    members = decrypt(downloaded, key)
    if hashlib.sha256(members["manifest.json"]).hexdigest() != prepared["backup_manifest_sha256"]:
        raise ValueError("Downloaded manifest differs")
    # A caller cannot substitute a newer claimed capture date for an old archive.
    manifest = json.loads(members["manifest.json"])
    if manifest["captured_at"] != prepared["archive_captured_at"]:
        raise ValueError("Capture time differs")
    fresh(manifest["captured_at"])
    restored = physical(settings["outgoing"]) / ("download-restore-" + uuid4().hex)
    unpack(downloaded, restored, key)
    proof = rehearse(restored)
    if proof.get("result") != "PASS" or proof.get("traffic_reopened") is not False:
        raise ValueError("Independent offline restore did not pass")
    fresh(manifest["captured_at"])
    receipt = {
        "result": "PASS",
        "verified_at": current_time().isoformat(),
        "archive_captured_at": manifest["captured_at"],
        "offsite_verified": True,
        "package_sha256": digest,
        "backup_manifest_sha256": prepared["backup_manifest_sha256"],
        "remote_file_id": remote["file_id"],
        "remote_path": remote["path"],
        "remote_modified_at": remote.get("modified_time"),
        "restore_seconds": proof["offline_rehearsal_seconds"],
        "independent_key_recovery_verified": False,
        "production_rpo_rto": False,
        "traffic_reopened": False,
    }
    write(Path(settings["receipt"]), receipt)
    return receipt


def recovery_kit(settings, destination):
    """Prepare a private local kit. Moving it to an independent medium is separate."""
    key = read_key(physical(settings["key"]))
    private_directory(destination)
    target = destination / "recovery.key"
    with target.open("xb") as stream:
        stream.write(key)
    target.chmod(0o600)
    (destination / "ODZYSKIWANIE.txt").write_text(
        "Ten katalog zawiera poufny klucz odszyfrowania kopii Calorie O3.\n"
        "Przenieś na oddzielny chroniony nośnik USB; nie zapisuj w Dropbox z kopiami ani w Git.\n"
        "Na drugim komputerze zachowaj Python 3.13, cryptography i źródła wydania.\n"
        "Pobierz plik .enc i porównaj cały SHA-256 z neutralnym receipt.\n"
        "Użyj offsite_package.py unpack z recovery.key do nowego prywatnego katalogu,\n"
        "następnie backup.py rehearse. Nie odtwarzaj do czynnej instalacji.\n"
        "Samo przygotowanie tego katalogu nie potwierdza niezależnej kopii klucza.\n",
        encoding="utf-8",
    )
    return {"result": "PREPARED", "independent_key_recovery_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "accept-download", "recovery-kit"))
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--downloaded", type=Path)
    parser.add_argument("--remote-metadata", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        settings = read(args.settings)
        if args.action == "prepare":
            result = prepare(settings)
        elif args.action == "recovery-kit":
            if args.output is None:
                raise ValueError("New private destination required")
            result = recovery_kit(settings, args.output)
        else:
            if any(
                value is None for value in (args.prepared, args.downloaded, args.remote_metadata)
            ):
                raise ValueError(
                    "Prepared receipt, independent download and connector metadata required"
                )
            result = accept_download(
                settings, read(args.prepared), args.downloaded, read(args.remote_metadata)
            )
        print(json.dumps(result))
        return 0
    except Exception:
        print('{"result":"FAIL","offsite_verified":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
