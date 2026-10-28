"""Offline, multi-source preparation of a local demo bundle; never seals a release."""

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath

# The copied standalone tool runs outside this repository's Python metadata.
if sys.version_info < (3, 13):  # noqa: UP036
    raise RuntimeError("Local demo preparation requires Python 3.13+ with junction guards")

FORMAT = "calorie-local-demo-preparation/v1"
MANIFEST = "manifest-demo.json"
GATES = {"108", "110", "119", "185", "184", "backup_restore", "final120"}
ROLES = {
    "apk_presign",
    "apk_final",
    "public_ca",
    "catalog_manifest",
    "catalog_payload",
    "evidence",
    "instructions",
}
SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in "123456789¹²³"
}
GENERATED = {MANIFEST, "local_demo_package.py", "START.ps1", "STOP.ps1", "RECOVER.ps1", "START.txt"}

ORDER = [
    "108",
    "110:C0/C1/C2",
    "110:released.json",
    "110:separatePULL+closure",
    "119:separateWindow+live+closure",
    "185->184 before final staging",
    "111:finalD+backup+actualRestore+encryptionVerify",
    "120:finalAudit",
]
CLAIMS = {
    "actual_runtime_test": False,
    "final_D_package": False,
    "backup_restore": False,
    "final120": False,
}
FINAL_BLOCKERS = [
    {
        "id": "final_operator_binding",
        "owner": "O1/119",
        "required": (
            "Actual installed signer, final app/test bytes+SHA/cert/config readback "
            "and own matching runtime receipt"
        ),
    },
    {
        "id": "final_seal",
        "owner": "O3-111/120",
        "required": (
            "Qualified actual receipts, final D staging, one backup/restore "
            "and independent final audit; preparation cannot seal"
        ),
    },
]


class InvalidPackage(ValueError):
    """An input or prepared bundle failed an offline integrity check."""


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidPackage("Duplicate JSON field")
        result[key] = value
    return result


def read(path):
    if path.stat().st_size > 2 * 1024**2:
        raise InvalidPackage("Oversized JSON metadata")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def regular(path):
    if any(linked(part) for part in (path, *path.parents)) or not path.is_file():
        raise InvalidPackage("Inputs and bundle members must be regular files without links")
    return path


def name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise InvalidPackage("Unsafe destination path")
    parts = PurePosixPath(value).parts
    if (
        value.startswith("/")
        or value != "/".join(parts)
        or any(
            p in {".", ".."}
            or p[-1:] in {".", " "}
            or p.split(".")[0].rstrip(" ").casefold() in RESERVED
            or any(ord(c) < 32 or c in '<>"|?*' for c in p)
            for p in parts
        )
    ):
        raise InvalidPackage("Unsafe destination path")
    return value


def checksum(path, *, reject_private=False):
    with regular(path).open("rb") as stream:
        digest, previous = hashlib.sha256(), b""
        while chunk := stream.read(1024 * 1024):
            if reject_private and re.search(
                rb"-----BEGIN [A-Z ]*PRIVATE KEY-----", previous + chunk
            ):
                raise InvalidPackage("Private key material is forbidden regardless of role")
            digest.update(chunk)
            previous = chunk[-128:]
        return digest.hexdigest()


def check_ref(entry, base):
    if (
        type(entry.get("bytes")) is not int
        or not 0 < entry["bytes"] <= 8 * 1024**3
        or not isinstance(entry.get("sha256"), str)
        or not SHA.fullmatch(entry["sha256"])
    ):
        raise InvalidPackage("Invalid size or SHA256 reference")
    source = Path(entry["source"])
    if not source.is_absolute():
        source = base / source
    source = regular(source.absolute())
    if source.suffix.lower() in {".key", ".env", ".pfx", ".p12", ".jks", ".keystore"}:
        raise InvalidPackage("Private key/config input is forbidden")
    if (
        source.stat().st_size != entry["bytes"]
        or checksum(source, reject_private=True) != entry["sha256"]
    ):
        raise InvalidPackage("Missing or changed input bytes")
    if entry["role"] in {"public_ca", "instructions", "evidence", "catalog_manifest"}:
        if source.stat().st_size > 2 * 1024**2:
            raise InvalidPackage("Oversized text input")
        data = source.read_bytes()
        if re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----", data):
            raise InvalidPackage("Private key material is forbidden")
        if entry["role"] == "public_ca" and (
            data.count(b"-----BEGIN CERTIFICATE-----") != 1
            or data.count(b"-----END CERTIFICATE-----") != 1
        ):
            raise InvalidPackage("Expected one public CA certificate")
    return source


def bindings(value):
    api, android = value["api"], value["android"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", api["image"]):
        raise InvalidPackage("Expected immutable API image")
    if not isinstance(api["schema"], str) or not api["schema"]:
        raise InvalidPackage("Expected API schema")
    if api["full_git_source"] is not None and not COMMIT.fullmatch(api["full_git_source"]):
        raise InvalidPackage("API source must be a full commit or explicit null/UNKNOWN")
    if (
        not COMMIT.fullmatch(android["source_commit"])
        or not COMMIT.fullmatch(android["android_tree"])
        or type(android["room"]) is not int
        or android["room"] < 1
        or android["stage"] not in {"PRE_SIGN_INPUT", "FINAL_OPERATOR_ACCEPTED"}
    ):
        raise InvalidPackage("Invalid independent Android binding")
    return value


def prepare(recipe_path, output):
    """Copy explicitly selected, verified inputs to a fresh PREPARATION_ONLY directory."""
    recipe_path, output = Path(recipe_path).absolute(), Path(output).absolute()
    recipe = read(regular(recipe_path))
    if recipe.get("format") != 1 or type(recipe["format"]) is not int:
        raise InvalidPackage("Unsupported recipe format")
    identity = bindings(recipe["bindings"])
    gates = recipe["gates"]
    if len(gates) != len(GATES) or {gate["id"] for gate in gates} != GATES:
        raise InvalidPackage("Required gate inventory is incomplete or duplicated")
    entries = [dict(entry) for entry in recipe["inputs"]]
    gate_inventory, missing = [], []
    for gate in gates:
        if not all(
            isinstance(gate.get(key), str) and gate[key].strip() for key in ("owner", "required")
        ):
            raise InvalidPackage("Every gate requires a concrete owner and artifact")
        row = {key: gate[key] for key in ("id", "owner", "required")}
        row["qualification"] = "NOT_QUALIFIED_BY_PREPARATION"
        row["receipt"] = None
        if gate.get("receipt") is None:
            missing.append({key: row[key] for key in ("id", "owner", "required")})
        else:
            destination = f"evidence/gate-{gate['id']}.json"
            entries.append(
                dict(
                    gate["receipt"],
                    id=f"gate-{gate['id']}",
                    role="evidence",
                    destination=destination,
                )
            )
            row["receipt"] = destination
        gate_inventory.append(row)
    missing.extend(FINAL_BLOCKERS)
    seen = {value.casefold() for value in GENERATED}
    ids, sources = set(), []
    for entry in entries:
        destination = name(entry["destination"])
        folded = destination.casefold()
        if folded in seen or any(
            folded.startswith(old + "/") or old.startswith(folded + "/") for old in seen
        ):
            raise InvalidPackage("Duplicate or conflicting destination path")
        if not isinstance(entry.get("id"), str) or not entry["id"] or entry["id"] in ids:
            raise InvalidPackage("Duplicate or missing input id")
        if entry.get("role") not in ROLES:
            raise InvalidPackage("Unsupported explicit input role")
        if (
            entry["role"] == "apk_final"
            and identity["android"]["stage"] != "FINAL_OPERATOR_ACCEPTED"
        ):
            raise InvalidPackage("Pre-sign binding cannot contain a final APK role")
        seen.add(folded)
        ids.add(entry["id"])
        sources.append((entry, check_ref(entry, recipe_path.parent)))
    # Validate all sources and packaged controls before creating any output.
    tool = regular(Path(__file__).absolute())
    controls = [("local_demo_package.py", tool)]
    controls.extend(
        (item, regular(tool.parent / "local_demo" / item))
        for item in ("START.ps1", "STOP.ps1", "RECOVER.ps1", "START.txt")
    )
    if output.exists():
        raise FileExistsError("Output already exists; older preparation is preserved")
    if any(linked(part) for part in output.parents):
        raise InvalidPackage("Output parent cannot be a link")
    output.mkdir(parents=False)
    inventory = {}
    for entry, source in sources:
        target = output / entry["destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_stream, target.open("xb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
        if (
            target.stat().st_size != entry["bytes"]
            or checksum(target, reject_private=True) != entry["sha256"]
        ):
            raise InvalidPackage(
                "Input changed during copy; incomplete output retained without manifest"
            )
        inventory[entry["destination"]] = {
            key: entry[key] for key in ("bytes", "sha256", "role", "id")
        }
    for destination, source in controls:
        target = output / destination
        with source.open("rb") as source_stream, target.open("xb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
        inventory[destination] = {
            "bytes": target.stat().st_size,
            "sha256": checksum(target),
            "role": "control",
        }
    manifest = {
        "format": FORMAT,
        "state": "PREPARATION_ONLY",
        "sealed": False,
        "runtime_authorized": False,
        "bindings": identity,
        "files": inventory,
        "gates": gate_inventory,
        "missing_inputs": missing,
        "unqualified_gates": [
            {key: gate[key] for key in ("id", "owner", "required")} for gate in gates
        ],
        "required_order": ORDER,
        "claims": CLAIMS,
    }
    with (output / MANIFEST).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    verify(output)
    return manifest


def verify(bundle):
    """Verify exact immutable file inventory, without Docker, ADB, network or imports."""
    bundle = Path(bundle).absolute()
    manifest = read(regular(bundle / MANIFEST))
    if (
        manifest.get("format") != FORMAT
        or manifest.get("state") != "PREPARATION_ONLY"
        or manifest.get("sealed") is not False
        or manifest.get("runtime_authorized") is not False
    ):
        raise InvalidPackage(
            "This tool verifies preparation only; cannot certify a sealed/runtime package"
        )
    bindings(manifest["bindings"])
    files = manifest["files"]
    if not isinstance(files, dict) or not set(GENERATED - {MANIFEST}) <= set(files):
        raise InvalidPackage("Incomplete control inventory")
    expected, folded, ids = {MANIFEST}, set(), set()
    for relative, ref in files.items():
        name(relative)
        if relative.casefold() in folded or relative == MANIFEST:
            raise InvalidPackage("Duplicate member")
        folded.add(relative.casefold())
        expected.add(relative)
        if relative in GENERATED:
            if ref.get("role") != "control":
                raise InvalidPackage("Invalid control role")
        elif (
            ref.get("role") not in ROLES
            or not isinstance(ref.get("id"), str)
            or not ref["id"]
            or ref["id"] in ids
        ):
            raise InvalidPackage("Invalid or duplicate input role/id")
        else:
            ids.add(ref["id"])
        if (
            ref["role"] == "apk_final"
            and manifest["bindings"]["android"]["stage"] != "FINAL_OPERATOR_ACCEPTED"
        ):
            raise InvalidPackage("Pre-sign binding cannot contain final APK role")
        member = bundle / relative
        if type(ref["bytes"]) is not int or not SHA.fullmatch(ref["sha256"]):
            raise InvalidPackage("Invalid member reference")
        if (
            regular(member).stat().st_size != ref["bytes"]
            or checksum(member, reject_private=ref["role"] != "control") != ref["sha256"]
        ):
            raise InvalidPackage("Missing or changed bundle member")
    actual = set()
    for member in bundle.rglob("*"):
        if linked(member):
            raise InvalidPackage("Bundle links are forbidden")
        if member.is_file():
            actual.add(member.relative_to(bundle).as_posix())
    if actual != expected:
        raise InvalidPackage("Unexpected or missing bundle members")
    if {gate["id"] for gate in manifest["gates"]} != GATES or len(manifest["gates"]) != len(GATES):
        raise InvalidPackage("Incomplete gate inventory")
    missing, unqualified = [], []
    for gate in manifest["gates"]:
        if gate.get("qualification") != "NOT_QUALIFIED_BY_PREPARATION" or not all(
            isinstance(gate.get(k), str) and gate[k].strip() for k in ("owner", "required")
        ):
            raise InvalidPackage("Preparation gate cannot claim acceptance")
        row = {key: gate[key] for key in ("id", "owner", "required")}
        unqualified.append(row)
        if gate.get("receipt") is None:
            missing.append(row)
        else:
            receipt = f"evidence/gate-{gate['id']}.json"
            if (
                gate["receipt"] != receipt
                or receipt not in files
                or files[receipt]["role"] != "evidence"
                or files[receipt]["id"] != f"gate-{gate['id']}"
            ):
                raise InvalidPackage("Gate receipt must bind its own evidence member")
    if (
        manifest.get("missing_inputs") != missing + FINAL_BLOCKERS
        or manifest.get("unqualified_gates") != unqualified
        or manifest.get("required_order") != ORDER
        or manifest.get("claims") != CLAIMS
        or any(value is not False for value in manifest["claims"].values())
    ):
        raise InvalidPackage("Preparation claims, blockers or gate order are inconsistent")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("prepare")
    builder.add_argument("--recipe", type=Path, required=True)
    builder.add_argument("--output", type=Path, required=True)
    checker = commands.add_parser("verify")
    checker.add_argument("--bundle", type=Path, required=True)
    checker.add_argument("--action", choices=("start", "stop", "recover"))
    checker.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        manifest = (
            prepare(args.recipe, args.output) if args.command == "prepare" else verify(args.bundle)
        )
        print(
            json.dumps(
                {
                    "integrity": "PASS",
                    "state": manifest["state"],
                    "action_authorized": False,
                    "missing_inputs": manifest["missing_inputs"],
                    "unqualified_gates": manifest["unqualified_gates"],
                },
                ensure_ascii=False,
            )
        )
        if args.command == "verify" and args.action and not args.check_only:
            return 3
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"integrity": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
