"""Export and verify a portable public-only Android handoff, without O3 paths or leases."""

import argparse
import hashlib
import json
import re
import ssl
import zipfile
from datetime import UTC, datetime
from pathlib import Path

FILES = (
    "handoff.json",
    "config.json",
    "tls/ca.pem",
    "validation.apk",
    "android_overlay.py",
    "android_transport.py",
    "android_peer.py",
    "android_handoff.py",
    "AndroidHttpsProbe.java",
    "README.md",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def certificate(data):
    if not re.fullmatch(
        rb"\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*",
        data,
    ):
        raise ValueError("Expected one public CA certificate, never a private key or env")
    ssl.create_default_context(cadata=data.decode("ascii"))


def verify(bundle):
    entries = (bundle / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    hashes = {}
    for entry in entries:
        expected, name = entry.split("  ", 1)
        if name not in FILES or name in hashes or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Unexpected or duplicate handoff member")
        path = bundle / name
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError(f"Missing or changed handoff member: {name}")
        hashes[name] = expected
    if set(hashes) != set(FILES):
        raise ValueError("Incomplete portable handoff")
    certificate((bundle / "tls/ca.pem").read_bytes())
    info = json.loads((bundle / "handoff.json").read_text(encoding="utf-8"))
    config = json.loads((bundle / "config.json").read_text(encoding="utf-8"))
    if set(config) != {"host", "port"}:
        raise ValueError("Configuration must contain public host/port only")
    if not re.fullmatch(r"[0-9a-f]{40}", info["apk_source"]):
        raise ValueError("Expected exact source commit")
    origin = f"https://{config['host']}:{config['port']}"
    if (
        info["origin"] != origin
        or info["issuer"] != origin + "/realms/calorie-dev"
        or info["api_base_url"] != origin + "/api/v1"
        or info["apk_sha256"] != hashes["validation.apk"]
        or info["public_ca_sha256"] != hashes["tls/ca.pem"]
        or info["application_id"] != "pl.roseru.kalorie.validation"
        or info["callback"] != "pl.roseru.kalorie.validation:/oauth2redirect"
    ):
        raise ValueError("Artifact, callback or original identity mismatch")
    return info


def export(source, output):
    original = json.loads((source / "handoff.json").read_text(encoding="utf-8"))
    # Never recurse through the original .tools state or copy its runtime lease/overlay.
    apk = (source / "validation-0.8.10.apk").read_bytes()
    ca = (source / "public-ca.pem").read_bytes()
    certificate(ca)
    if digest(apk) != original["apk_sha256"] or digest(ca) != original["public_ca_sha256"]:
        raise ValueError("Source handoff hash mismatch")
    info = {
        key: original[key]
        for key in (
            "origin",
            "issuer",
            "api_base_url",
            "callback",
            "application_id",
            "apk_source",
            "apk_version",
            "apk_version_code",
            "apk_sha256",
            "public_ca_sha256",
        )
    }
    info.update(
        {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "apk": "validation.apk",
            "public_ca": "tls/ca.pem",
            "schema": "0024_e9_history_graph",
            "peer_transport": "WAITING_FOR_O1_O3_LAN_OR_VPN_CONFIGURATION",
            "browser_apk_acceptance": "NOT_RUN_BY_HANDOFF_EXPORT",
        }
    )
    receipt = json.loads((source / "overlay/overlay.json").read_text(encoding="utf-8"))
    origin = f"https://{receipt['host']}:{receipt['port']}"
    if info["origin"] != origin or receipt["ca_sha256"] != digest(ca):
        raise ValueError("Original overlay disagrees with handoff")
    scripts = Path(__file__).resolve().parent
    data = {
        "handoff.json": (json.dumps(info, indent=2) + "\n").encode(),
        "config.json": (
            json.dumps({"host": receipt["host"], "port": receipt["port"]}) + "\n"
        ).encode(),
        "tls/ca.pem": ca,
        "validation.apk": apk,
        "README.md": (scripts / "ANDROID_HANDOFF.md").read_bytes(),
    }
    for name in FILES:
        if name not in data:
            data[name] = (scripts / name).read_bytes()
    data["SHA256SUMS"] = "".join(
        f"{digest(data[name])}  {name}\n" for name in sorted(FILES)
    ).encode("ascii")
    # Exclusive creation preserves previously delivered packages and evidence.
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in data.items():
            archive.writestr(name, content)
    return {"bundle_sha256": digest(output.read_bytes()), "apk_sha256": digest(apk)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--source", type=Path, required=True)
    exporter.add_argument("--output", type=Path, required=True)
    for action in ("verify", "overlay"):
        command = commands.add_parser(action)
        command.add_argument("--bundle", type=Path, required=True)
        if action == "overlay":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "export":
        print(json.dumps(export(args.source, args.output)))
    else:
        info = verify(args.bundle)
        if args.action == "overlay":
            if __package__:
                from .android_overlay import prepare
            else:
                from android_overlay import prepare

            print(json.dumps(prepare(args.bundle.resolve(), args.output.resolve())))
        else:
            print(json.dumps({"integrity": "PASS", "apk_source": info["apk_source"]}))


if __name__ == "__main__":
    main()
