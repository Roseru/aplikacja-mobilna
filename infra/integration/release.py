"""Validate a versioned release candidate against real local artifacts; never deploy."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
EVIDENCE = {"android_acceptance", "backend_acceptance", "migration", "rollback", "restore"}


class InvalidCandidate(ValueError):
    pass


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCandidate("Duplicate JSON field")
        result[key] = value
    return result


def read(path):
    if path.stat().st_size > 1024**2:
        raise InvalidCandidate("JSON exceeds 1MiB")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(root, relative):
    if not isinstance(relative, str):
        raise InvalidCandidate("Artifact path must be a relative string")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise InvalidCandidate("Artifact escaped candidate directory")
    path = root / candidate
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p != root.parent):
        raise InvalidCandidate("Redirected candidate artifacts are not accepted")
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise InvalidCandidate("Artifact escaped candidate directory")
    return resolved


def command(arguments, *, cwd=None):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(
        arguments, cwd=cwd, capture_output=True, text=True, timeout=60, **options
    )
    if result.returncode or len(result.stdout) > 1024**2:
        raise InvalidCandidate("Artifact inspection failed")
    return result.stdout


class Inspector:
    def __init__(self, *, docker, aapt, java, apksigner):
        self.docker = docker
        # Resolve package-virtualized SDK locations before invoking external Java.
        self.aapt = str(Path(aapt).resolve(strict=True)) if Path(aapt).exists() else aapt
        self.java = str(Path(java).resolve(strict=True)) if Path(java).exists() else java
        self.apksigner = (
            str(Path(apksigner).resolve(strict=True)) if Path(apksigner).exists() else apksigner
        )

    def apk(self, path):
        # Legacy aapt on Windows cannot open an absolute path with Polish characters.
        # A Unicode working directory and the original filename avoid lossy conversion.
        badging = command([self.aapt, "dump", "badging", path.name], cwd=path.parent)
        package = re.search(
            r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'",
            badging,
            re.MULTILINE,
        )
        signature = command(
            [self.java, "-jar", self.apksigner, "verify", "--verbose", "--print-certs", path.name],
            cwd=path.parent,
        )
        certificates = re.findall(
            r"^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-f]{64})$", signature, re.MULTILINE
        )
        if package is None or len(certificates) != 1:
            raise InvalidCandidate("APK package or verified signer is ambiguous")
        return {
            "application_id": package[1],
            "version_code": int(package[2]),
            "version_name": package[3],
            "debuggable": "application-debuggable" in badging,
            "signer_sha256": certificates[0],
        }

    def image(self, reference):
        if not re.fullmatch(r"(?:[a-z0-9][a-z0-9._:/-]*@)?sha256:[0-9a-f]{64}", reference):
            raise InvalidCandidate(
                "Backend image must have an immutable local ID or registry digest"
            )
        info = json.loads(command([self.docker, "image", "inspect", reference]))[0]
        return info

    def schema(self, reference):
        # No pull, mounts, credentials, network, writable root or service start.
        return command(
            [
                self.docker,
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--user",
                "10001:10001",
                "--entrypoint",
                ".venv/bin/python",
                reference,
                "-I",
                "-c",
                "from calorie_app.health import EXPECTED_REVISION; print(EXPECTED_REVISION)",
            ]
        ).strip()


def validate_android(root, spec, commit, inspector, production):
    metadata = read(artifact(root, spec["manifest"]))
    apk = artifact(root, spec["apk"])
    if metadata["commit"] != commit or metadata["sha256"] != file_digest(apk):
        raise InvalidCandidate("APK commit or checksum mismatch")
    if Path(metadata["apk"]).name != apk.name:
        raise InvalidCandidate("APK filename differs from build manifest")
    actual = inspector.apk(apk)
    if actual["application_id"] != "pl.roseru.kalorie":
        raise InvalidCandidate("Validation application cannot be a regular release candidate")
    for key in ("application_id", "version_name", "version_code"):
        if metadata[key] != actual[key]:
            raise InvalidCandidate("APK version differs from build manifest")
    expected = spec["signer_sha256"]
    if (
        not isinstance(expected, str)
        or not SHA.fullmatch(expected)
        or actual["signer_sha256"] != expected
    ):
        raise InvalidCandidate("APK signer differs from the expected public certificate")
    if production and (actual["debuggable"] or metadata["variant"] != "release"):
        raise InvalidCandidate("Production requires a release APK without debug flags")
    if type(spec["catalog_reader_version"]) is not int or spec["catalog_reader_version"] < 1:
        raise InvalidCandidate("Explicit supported catalog reader required from O1")
    return actual | {"sha256": file_digest(apk), "commit": commit}


def archive_config(root, spec, image):
    """Bind a containerd manifest ID to the original Docker config digest receipt."""
    source = spec["image_archive"]
    if set(source) != {"path", "sha256", "config_digest"}:
        raise InvalidCandidate("Incomplete image archive identity")
    archive = artifact(root, source["path"])
    if archive.stat().st_size > 2 * 1024**3 or file_digest(archive) != source["sha256"]:
        raise InvalidCandidate("Image archive checksum mismatch")

    with tarfile.open(archive, mode="r:") as stream:
        names = [member.name for member in stream]
        if len(names) > 4096 or len(names) != len(set(names)):
            raise InvalidCandidate("Ambiguous image archive")

        def metadata(name, digest=None):
            member = stream.getmember(name)
            if not member.isfile() or member.size > 1024**2:
                raise InvalidCandidate("Invalid image metadata")
            raw = stream.extractfile(member).read(1024**2 + 1)
            if digest is not None and "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
                raise InvalidCandidate("Image metadata digest mismatch")
            return json.loads(raw, object_pairs_hook=unique)

        def blob(digest):
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise InvalidCandidate("Invalid image descriptor digest")
            return metadata("blobs/sha256/" + digest.split(":")[1], digest)

        index = metadata("index.json")
        descriptors = index["manifests"]
        if len(descriptors) != 1 or descriptors[0]["digest"] != spec["image"]:
            raise InvalidCandidate("Imported runtime ID differs from archived manifest")
        manifest = blob(descriptors[0]["digest"])
        digest = manifest["config"]["digest"]
        if digest != source["config_digest"]:
            raise InvalidCandidate("Image config differs from receipt identity")
        config = blob(digest)
        if (
            config["rootfs"]["diff_ids"] != image["RootFS"]["Layers"]
            or config["config"].get("Labels") != image["Config"].get("Labels")
            or config["os"] != image["Os"]
            or config["architecture"] != image["Architecture"]
        ):
            raise InvalidCandidate("Imported runtime differs from archived config")
    return digest


def validate_backend(spec, commit, inspector, production, *, root=None):
    reference = spec["image"]
    image = inspector.image(reference)
    if (image["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") != commit:
        raise InvalidCandidate("Backend image lacks matching source revision")
    if reference.startswith("sha256:"):
        if image["Id"] != reference or production:
            raise InvalidCandidate("Production requires a published registry digest")
    elif reference not in image.get("RepoDigests", []):
        raise InvalidCandidate("Registry digest does not identify this local image")
    config_digest = archive_config(root, spec, image) if "image_archive" in spec else None
    if inspector.schema(reference) != spec["schema_revision"]:
        raise InvalidCandidate("Backend schema differs from release specification")
    return {
        "image": reference,
        "commit": commit,
        "schema_revision": spec["schema_revision"],
        "receipt_config_digest": config_digest,
    }


def validate_catalog(root, spec, reader, production):
    from calorie_app.modules.catalog.offline_import import OfflineCatalog

    manifest_path = artifact(root, spec["manifest"])
    package = artifact(root, spec["package"])
    manifest = read(manifest_path)
    if production and manifest["kind"] != "official":
        raise InvalidCandidate("Demo catalog cannot be labeled as production official")
    if manifest["min_reader_version"] > reader:
        raise InvalidCandidate("Catalog requires a newer Android reader")
    if manifest["path"] != package.name:
        raise InvalidCandidate("Catalog filename differs from manifest")
    with tempfile.TemporaryDirectory(prefix="calorie-release-catalog-") as directory:
        catalog = OfflineCatalog(
            Path(directory) / "catalog.sqlite", manifest["package_id"], manifest["kind"]
        )
        catalog.import_package(manifest_path, package)
        active = catalog.read_active_package()
        if active["release"] != manifest["release"]:
            raise InvalidCandidate("Catalog active release mismatch")
    return {key: manifest[key] for key in ("package_id", "kind", "release", "sha256")}


def validate_evidence(root, entries, spec, production):
    commit = spec["commit"]
    revision = spec["backend"]["schema_revision"]
    if set(entries) != EVIDENCE:
        raise InvalidCandidate("Complete O1/O2 migration, rollback and recovery evidence required")
    result = {}
    for name, entry in entries.items():
        path = artifact(root, entry["path"])
        if entry["sha256"] != file_digest(path):
            raise InvalidCandidate("Acceptance evidence checksum mismatch")
        receipt = read(path)
        if receipt.get("result") != "PASS" or receipt.get("commit") != commit:
            raise InvalidCandidate("Acceptance evidence does not cover the candidate commit")
        if name == "android_acceptance" and (
            receipt.get("apk_sha256") != file_digest(artifact(root, spec["android"]["apk"]))
            or receipt.get("catalog_reader_version") != spec["android"]["catalog_reader_version"]
            or type(receipt.get("room_version")) is not int
            or receipt["room_version"] < 1
        ):
            raise InvalidCandidate("Android acceptance does not identify APK/Room/catalog reader")
        if name == "backend_acceptance" and (
            receipt.get("image")
            not in {
                spec["backend"]["image"],
                spec["backend"]
                .get("image_archive", {})
                .get("config_digest", spec["backend"]["image"]),
            }
            or receipt.get("schema_revision") != revision
        ):
            raise InvalidCandidate("Backend acceptance does not identify image/schema")
        if name == "migration" and (
            receipt.get("to_revision") != revision
            or not receipt.get("from_revision")
            or receipt.get("data_preserved") is not True
        ):
            raise InvalidCandidate("Migration evidence lacks matching schema/data preservation")
        if name == "rollback":
            if (
                receipt.get("strategy") not in {"compatible_image", "restore"}
                or receipt.get("for_revision") != revision
            ):
                raise InvalidCandidate("Explicit accepted rollback strategy/schema required")
            if receipt["strategy"] == "compatible_image" and (
                not isinstance(receipt.get("image"), str)
                or not re.fullmatch(
                    r"(?:[a-z0-9][a-z0-9._:/-]*@)?sha256:[0-9a-f]{64}", receipt["image"]
                )
                or receipt.get("schema_compatible") is not True
            ):
                raise InvalidCandidate(
                    "Rollback image needs immutable identity and schema acceptance"
                )
        if (
            name == "restore"
            and production
            and (
                receipt.get("offsite_verified") is not True
                or receipt.get("client_recovery") is not True
            )
        ):
            raise InvalidCandidate("Production requires offsite and client recovery acceptance")
        result[name] = entry["sha256"]
    return result


def validate(manifest, inspector):
    root = manifest.resolve(strict=True).parent
    spec = read(manifest)
    if (
        set(spec) != {"format", "channel", "commit", "android", "backend", "catalog", "evidence"}
        or spec["format"] != 1
        or spec["channel"] not in {"integration", "production"}
        or not isinstance(spec["commit"], str)
        or not COMMIT.fullmatch(spec["commit"])
    ):
        raise InvalidCandidate("Invalid release specification")
    production = spec["channel"] == "production"
    checks, failures = {}, []
    operations = {
        "android": lambda: validate_android(
            root, spec["android"], spec["commit"], inspector, production
        ),
        "backend": lambda: validate_backend(
            spec["backend"], spec["commit"], inspector, production, root=root
        ),
        "catalog": lambda: validate_catalog(
            root, spec["catalog"], spec["android"]["catalog_reader_version"], production
        ),
        "evidence": lambda: validate_evidence(root, spec["evidence"], spec, production),
    }
    for name, operation in operations.items():
        try:
            checks[name] = operation()
        except InvalidCandidate as error:
            failures.append({"component": name, "reason": str(error)})
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            tarfile.TarError,
            subprocess.SubprocessError,
        ):
            failures.append(
                {"component": name, "reason": "Missing, invalid or inconsistent artifact"}
            )
    return {
        "result": "BLOCKED" if failures else "CANDIDATE_VALIDATED",
        "commit": spec["commit"],
        "channel": spec["channel"],
        "checked_at": datetime.now(UTC).isoformat(),
        "components": checks,
        "blockers": failures,
        "deployment_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--aapt", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--apksigner-jar", required=True)
    args = parser.parse_args()
    try:
        result = validate(
            args.manifest,
            Inspector(
                docker=args.docker, aapt=args.aapt, java=args.java, apksigner=args.apksigner_jar
            ),
        )
    except (OSError, ValueError, KeyError, TypeError):
        result = {
            "result": "BLOCKED",
            "blockers": [
                {"component": "specification", "reason": "Missing or invalid release specification"}
            ],
            "deployment_authorized": False,
        }
    if args.output.resolve() == args.manifest.resolve():
        raise ValueError("Report must not overwrite the release specification")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["result"] == "CANDIDATE_VALIDATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
