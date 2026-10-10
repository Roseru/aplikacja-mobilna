"""Deterministic PostgreSQL export and write-before-commit publication."""

import gzip
import hashlib
import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from calorie_app.modules.catalog.models import OfflineChannel, OfflinePackage
from calorie_app.modules.catalog.repository import package_header, read_package
from calorie_app.modules.catalog.service import content_hash
from calorie_app.modules.catalog.validation import (
    MAX_COMPRESSED_BYTES,
    MAX_UNCOMPRESSED_BYTES,
    CatalogValidationError,
    canonical_json,
    validate_manifest,
    validate_package,
)


@dataclass(frozen=True)
class ExportArtifact:
    raw: bytes
    compressed: bytes
    manifest: dict


def export_package(engine, package_id: UUID, release: int) -> ExportArtifact:
    """One repeatable-read snapshot of the actual relational catalog."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, session.begin():
            value = read_package(session, package_id, release)
            validate_package(value)
            row = session.get(OfflinePackage, (package_id, release))
            if content_hash(value) != row.content_hash:
                raise CatalogValidationError("catalog_snapshot_conflict")
            raw = canonical_json(value)
            if len(raw) > MAX_UNCOMPRESSED_BYTES:
                raise CatalogValidationError("catalog_size")
            output = io.BytesIO()
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0
            ) as gz:
                gz.write(raw)
            compressed = output.getvalue()
            if len(compressed) > MAX_COMPRESSED_BYTES:
                raise CatalogValidationError("catalog_size")
            manifest = package_header(row, value["kind"], value["published_at"]) | {
                "path": f"base-pl.{release}.json.gz",
                "compressed_bytes": len(compressed),
                "uncompressed_bytes": len(raw),
                "sha256": hashlib.sha256(compressed).hexdigest(),
                "source_ids": [s["source_id"] for s in value["sources"]],
            }
            validate_manifest(manifest)
    return ExportArtifact(raw, compressed, manifest)


def artifact_relative_path(package_id: UUID, kind: str, release: int) -> str:
    if (
        kind not in {"demo", "official"}
        or type(release) is not int
        or not 1 <= release <= 2147483647
    ):
        raise CatalogValidationError("catalog_artifact_path")
    return f"{kind}/{package_id}/base-pl.{release}.json.gz"


def artifact_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise CatalogValidationError("catalog_artifact_path")
    return path


def write_immutable(path: Path, data: bytes) -> None:
    """Atomic no-clobber install of a fully written file on the same filesystem.

    A hard link makes the final name visible only after flush/fsync. The only
    removable file is our random temporary file; existing releases are compared.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            with path.open("rb") as stream:
                existing = stream.read(len(data) + 1)
            if existing != data:
                raise CatalogValidationError("catalog_artifact_conflict") from None
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def read_published_artifact(root: Path, row: OfflinePackage, kind: str) -> bytes:
    expected = artifact_relative_path(row.package_id, kind, row.release)
    if row.state != "published" or row.artifact_path != expected:
        raise CatalogValidationError("catalog_artifact_path")
    with artifact_path(root, expected).open("rb") as stream:
        raw = stream.read(MAX_COMPRESSED_BYTES + 1)
    if len(raw) != row.compressed_bytes or hashlib.sha256(raw).hexdigest() != row.sha256:
        raise CatalogValidationError("catalog_artifact_conflict")
    return raw


def publish_package(
    engine,
    package_id: UUID,
    release: int,
    artifact_root: Path,
    *,
    fault_hook: Callable[[str], None] | None = None,
) -> dict:
    """Publish immutable bytes, then serialize final metadata and active pointer.

    The hook is an injection point for failure tests, never a validation bypass.
    Files left by a failed DB commit remain unregistered and cannot be downloaded.
    """
    artifact = export_package(engine, package_id, release)
    relative = artifact_relative_path(package_id, artifact.manifest["kind"], release)
    if fault_hook is not None:
        fault_hook("before_write")
    write_immutable(artifact_path(artifact_root, relative), artifact.compressed)
    if fault_hook is not None:
        fault_hook("after_write")
    with Session(engine) as session, session.begin():
        channel = session.scalar(
            select(OfflineChannel).where(OfflineChannel.package_id == package_id).with_for_update()
        )
        row = session.scalar(
            select(OfflinePackage)
            .where(OfflinePackage.package_id == package_id, OfflinePackage.release == release)
            .with_for_update()
        )
        if (
            row is None
            or channel is None
            or row.content_hash != hashlib.sha256(artifact.raw).hexdigest()
        ):
            raise CatalogValidationError("catalog_snapshot_conflict")
        if row.state == "published":
            if (
                row.sha256 != artifact.manifest["sha256"]
                or row.compressed_bytes != len(artifact.compressed)
                or row.uncompressed_bytes != len(artifact.raw)
                or row.artifact_path != relative
            ):
                raise CatalogValidationError("catalog_release_conflict")
            read_published_artifact(artifact_root, row, channel.kind)
            return artifact.manifest
        row.sha256 = artifact.manifest["sha256"]
        row.compressed_bytes = artifact.manifest["compressed_bytes"]
        row.uncompressed_bytes = artifact.manifest["uncompressed_bytes"]
        row.artifact_path = relative
        row.state = "published"
        session.flush()
        if channel.active_release is None or channel.active_release < release:
            channel.active_release = release
        session.flush()
        if fault_hook is not None:
            fault_hook("before_commit")
    return artifact.manifest
