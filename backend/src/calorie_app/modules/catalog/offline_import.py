"""Persistent, network-free reference importer for the E0 offline catalogue.

This module intentionally imports neither the application settings nor SQLAlchemy.
Only a validated, fully committed generation can become active. Historical versions
are retained, including versions no longer present in the active package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from calorie_app.modules.catalog.validation import (
    CatalogValidationError,
    canonical_json,
    parse_json,
    validate_manifest,
    validate_package,
)

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_COMPRESSED_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
_HEADERS = (
    "package_id",
    "kind",
    "release",
    "schema_version",
    "min_reader_version",
    "published_at",
    "counts",
)


class OfflineImportError(ValueError):
    """An artifact, identity or immutable version failed offline import checks."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _read_manifest(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise OfflineImportError("manifest_too_large", "Manifest exceeds 1 MiB")
    result = parse_json(data)
    validate_manifest(result)
    return result


def _read_package(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Bound both input and output before JSON parsing; accept one gzip member.

    zlib validates the gzip header, DEFLATE, CRC32 and ISIZE. Explicit EOF and
    unused-data checks reject truncation, appended bytes and concatenated members.
    The output limit is enforced inside decompress(), not after allocating a bomb.
    """
    decoder = zlib.decompressobj(wbits=31)
    digest = hashlib.sha256()
    compressed_size = 0
    output = bytearray()
    compressed_limit = min(MAX_COMPRESSED_BYTES, manifest["compressed_bytes"])
    output_limit = min(MAX_UNCOMPRESSED_BYTES, manifest["uncompressed_bytes"])
    with path.open("rb") as stream:
        first = True
        while chunk := stream.read(min(READ_CHUNK_BYTES, compressed_limit - compressed_size + 1)):
            compressed_size += len(chunk)
            if compressed_size > compressed_limit:
                raise OfflineImportError("compressed_size", "Compressed package exceeds its limit")
            if first:
                # Reserved gzip flags must be zero (RFC 1952); zlib accepts some.
                if len(chunk) < 10 or chunk[:3] != b"\x1f\x8b\x08" or chunk[3] & 0xE0:
                    raise OfflineImportError("invalid_gzip", "Invalid gzip header")
                first = False
            digest.update(chunk)
            if decoder.eof:
                raise OfflineImportError("invalid_gzip", "Trailing data or multiple gzip members")
            try:
                decoded = decoder.decompress(chunk, output_limit - len(output) + 1)
            except zlib.error as exc:
                raise OfflineImportError("invalid_gzip", "Invalid gzip stream or CRC") from exc
            output.extend(decoded)
            if len(output) > output_limit:
                raise OfflineImportError("uncompressed_size", "JSON package exceeds its limit")
            if decoder.unused_data:
                raise OfflineImportError("invalid_gzip", "Trailing data or multiple gzip members")
    if not decoder.eof:
        raise OfflineImportError("invalid_gzip", "Truncated gzip stream")
    if compressed_size != manifest["compressed_bytes"]:
        raise OfflineImportError("compressed_size", "Compressed size differs from manifest")
    if len(output) != manifest["uncompressed_bytes"]:
        raise OfflineImportError("uncompressed_size", "JSON size differs from manifest")
    if digest.hexdigest() != manifest["sha256"]:
        raise OfflineImportError("hash_mismatch", "SHA-256 differs from manifest")
    package = parse_json(bytes(output))
    validate_package(package)
    for key in _HEADERS:
        if package[key] != manifest[key]:
            raise OfflineImportError("header_mismatch", f"Manifest/package mismatch: {key}")
    source_ids = [source["source_id"] for source in package["sources"]]
    if len(set(manifest["source_ids"])) != len(manifest["source_ids"]) or set(source_ids) != set(
        manifest["source_ids"]
    ):
        raise OfflineImportError("source_ids_mismatch", "Manifest source IDs differ from package")
    if manifest["path"] != f"base-pl.{manifest['release']}.json.gz":
        raise OfflineImportError("path_mismatch", "Manifest path does not match release")
    return package


_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_sources (
    source_id TEXT PRIMARY KEY, payload BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog_product_versions (
    product_id TEXT NOT NULL, revision INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES catalog_sources(source_id),
    name TEXT NOT NULL, basis_unit TEXT NOT NULL CHECK(basis_unit IN ('g','ml')),
    energy_kcal TEXT, protein_g TEXT, fat_g TEXT, carbs_g TEXT,
    package_amount TEXT NOT NULL,
    package_unit TEXT NOT NULL CHECK(package_unit IN ('g','ml')),
    density_amount TEXT, density_source_id TEXT REFERENCES catalog_sources(source_id),
    payload BLOB NOT NULL, PRIMARY KEY(product_id, revision)
);
CREATE TABLE IF NOT EXISTS catalog_ration_versions (
    ration_id TEXT NOT NULL, revision INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES catalog_sources(source_id),
    name TEXT NOT NULL, complete INTEGER NOT NULL CHECK(complete IN (0,1)),
    payload BLOB NOT NULL, PRIMARY KEY(ration_id, revision)
);
CREATE TABLE IF NOT EXISTS catalog_components (
    ration_id TEXT NOT NULL, ration_revision INTEGER NOT NULL, position INTEGER NOT NULL,
    product_id TEXT NOT NULL, product_revision INTEGER NOT NULL,
    group_name TEXT NOT NULL, amount TEXT NOT NULL, unit TEXT NOT NULL CHECK(unit IN ('g','ml')),
    optional INTEGER NOT NULL CHECK(optional IN (0,1)),
    PRIMARY KEY(ration_id, ration_revision, position),
    FOREIGN KEY(ration_id, ration_revision) REFERENCES catalog_ration_versions(ration_id, revision),
    FOREIGN KEY(product_id, product_revision)
        REFERENCES catalog_product_versions(product_id, revision)
);
CREATE TABLE IF NOT EXISTS catalog_generations (
    generation_id TEXT PRIMARY KEY, package_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('demo','official')), release INTEGER NOT NULL,
    manifest BLOB NOT NULL, header BLOB NOT NULL,
    complete INTEGER NOT NULL CHECK(complete IN (0,1)),
    UNIQUE(package_id, kind, release)
);
CREATE TABLE IF NOT EXISTS catalog_generation_sources (
    generation_id TEXT NOT NULL REFERENCES catalog_generations(generation_id),
    position INTEGER NOT NULL, source_id TEXT NOT NULL REFERENCES catalog_sources(source_id),
    PRIMARY KEY(generation_id, source_id), UNIQUE(generation_id, position)
);
CREATE TABLE IF NOT EXISTS catalog_generation_products (
    generation_id TEXT NOT NULL REFERENCES catalog_generations(generation_id),
    position INTEGER NOT NULL, product_id TEXT NOT NULL, revision INTEGER NOT NULL,
    PRIMARY KEY(generation_id, product_id, revision), UNIQUE(generation_id, position),
    FOREIGN KEY(product_id, revision) REFERENCES catalog_product_versions(product_id, revision)
);
CREATE TABLE IF NOT EXISTS catalog_generation_rations (
    generation_id TEXT NOT NULL REFERENCES catalog_generations(generation_id),
    position INTEGER NOT NULL, ration_id TEXT NOT NULL, revision INTEGER NOT NULL,
    PRIMARY KEY(generation_id, ration_id, revision), UNIQUE(generation_id, position),
    FOREIGN KEY(ration_id, revision) REFERENCES catalog_ration_versions(ration_id, revision)
);
CREATE TABLE IF NOT EXISTS catalog_active (
    package_id TEXT NOT NULL, kind TEXT NOT NULL,
    generation_id TEXT NOT NULL REFERENCES catalog_generations(generation_id),
    PRIMARY KEY(package_id, kind)
);
"""


class OfflineCatalog:
    """One trusted package/channel in a durable SQLite database.

    stage() returns a committed generation UUID; activate() returns True only
    when switching the active pointer. Identical or older activation returns False.
    A caller can stop/restart between these steps and keep the same generation ID.
    Separate instances/connections support concurrent staging and activation.
    """

    def __init__(
        self, database_path: str | Path, expected_package_id: str, expected_kind: str
    ) -> None:
        try:
            normalized = str(uuid.UUID(expected_package_id))
        except (ValueError, AttributeError) as exc:
            raise OfflineImportError(
                "invalid_identity", "Expected package ID must be a UUID"
            ) from exc
        if normalized != expected_package_id or expected_kind not in {"demo", "official"}:
            raise OfflineImportError("invalid_identity", "Invalid trusted package/channel")
        self.database_path = Path(database_path)
        if str(database_path) == ":memory:":
            raise OfflineImportError("invalid_database", "A durable database file is required")
        self.expected_package_id = expected_package_id
        self.expected_kind = expected_kind
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def _check_identity(self, data: Any) -> None:
        if data["package_id"] != self.expected_package_id or data["kind"] != self.expected_kind:
            raise OfflineImportError("identity_mismatch", "Package is outside the trusted channel")

    def _before_stage_commit(self, connection: sqlite3.Connection) -> None:
        """Fault-injection seam; exceptions roll back the complete staging write."""

    def _before_activate_commit(self, connection: sqlite3.Connection) -> None:
        """Fault-injection seam; exceptions roll back the active-pointer change."""

    def stage(self, manifest_path: str | Path, package_path: str | Path) -> str:
        manifest = _read_manifest(Path(manifest_path))
        self._check_identity(manifest)
        package = _read_package(Path(package_path), manifest)
        self._check_identity(package)
        manifest_bytes = canonical_json(manifest)
        with self._connect() as connection:
            # A SQLite writer transaction serializes immutable identity checks and inserts.
            # WAL lets readers continue using the previous complete generation.
            connection.execute("BEGIN IMMEDIATE")
            other_channel = connection.execute(
                "SELECT 1 FROM catalog_generations WHERE package_id=? AND kind<>? LIMIT 1",
                (self.expected_package_id, self.expected_kind),
            ).fetchone()
            if other_channel:
                raise OfflineImportError(
                    "identity_mismatch", "Package UUID is bound to another channel"
                )
            previous = connection.execute(
                "SELECT generation_id, manifest FROM catalog_generations "
                "WHERE package_id=? AND kind=? AND release=?",
                (self.expected_package_id, self.expected_kind, package["release"]),
            ).fetchone()
            if previous:
                if previous["manifest"] != manifest_bytes:
                    raise OfflineImportError(
                        "release_conflict", "Release already has different bytes"
                    )
                connection.commit()
                return previous["generation_id"]
            generation = str(uuid.uuid4())
            header = {key: package[key] for key in _HEADERS}
            connection.execute(
                "INSERT INTO catalog_generations VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    generation,
                    package["package_id"],
                    package["kind"],
                    package["release"],
                    manifest_bytes,
                    canonical_json(header),
                ),
            )
            for position, source in enumerate(package["sources"]):
                payload = canonical_json(source)
                if not self._same_version(
                    connection, "catalog_sources", "source_id=?", (source["source_id"],), payload
                ):
                    connection.execute(
                        "INSERT INTO catalog_sources VALUES (?, ?)", (source["source_id"], payload)
                    )
                connection.execute(
                    "INSERT INTO catalog_generation_sources VALUES (?, ?, ?)",
                    (generation, position, source["source_id"]),
                )
            for position, product in enumerate(package["products"]):
                payload = canonical_json(product)
                key = (product["product_id"], product["revision"])
                if not self._same_version(
                    connection,
                    "catalog_product_versions",
                    "product_id=? AND revision=?",
                    key,
                    payload,
                ):
                    nutrition = product["nutrition_per_100"]
                    density = product["density_g_per_ml"]
                    connection.execute(
                        "INSERT INTO catalog_product_versions VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            *key,
                            product["source_id"],
                            product["name"],
                            product["basis_unit"],
                            nutrition["energy_kcal"],
                            nutrition["protein_g"],
                            nutrition["fat_g"],
                            nutrition["carbs_g"],
                            product["package_quantity"]["amount"],
                            product["package_quantity"]["unit"],
                            density["amount"] if density else None,
                            density["source_id"] if density else None,
                            payload,
                        ),
                    )
                connection.execute(
                    "INSERT INTO catalog_generation_products VALUES (?, ?, ?, ?)",
                    (generation, position, *key),
                )
            for position, ration in enumerate(package["rations"]):
                payload = canonical_json(ration)
                key = (ration["ration_id"], ration["revision"])
                if not self._same_version(
                    connection,
                    "catalog_ration_versions",
                    "ration_id=? AND revision=?",
                    key,
                    payload,
                ):
                    connection.execute(
                        "INSERT INTO catalog_ration_versions VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            *key,
                            ration["source_id"],
                            ration["name"],
                            int(ration["complete"]),
                            payload,
                        ),
                    )
                    for component in ration["components"]:
                        connection.execute(
                            "INSERT INTO catalog_components VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                *key,
                                component["position"],
                                component["product"]["product_id"],
                                component["product"]["revision"],
                                component["group"],
                                component["quantity"]["amount"],
                                component["quantity"]["unit"],
                                int(component["optional"]),
                            ),
                        )
                connection.execute(
                    "INSERT INTO catalog_generation_rations VALUES (?, ?, ?, ?)",
                    (generation, position, *key),
                )
            connection.execute(
                "UPDATE catalog_generations SET complete=1 WHERE generation_id=?", (generation,)
            )
            self._before_stage_commit(connection)
            connection.commit()
            return generation

    @staticmethod
    def _same_version(
        connection: sqlite3.Connection, table: str, where: str, key: tuple[Any, ...], payload: bytes
    ) -> bool:
        # Table/where are private literals, never taken from an artifact or CLI input.
        existing = connection.execute(f"SELECT payload FROM {table} WHERE {where}", key).fetchone()
        if not existing:
            return False
        if existing["payload"] != payload:
            raise OfflineImportError("version_conflict", f"Immutable version conflicts in {table}")
        return True

    def activate(self, generation: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                "SELECT * FROM catalog_generations WHERE generation_id=?", (generation,)
            ).fetchone()
            if not candidate or not candidate["complete"]:
                raise OfflineImportError("unknown_generation", "Generation is absent or incomplete")
            self._check_identity(candidate)
            current = connection.execute(
                "SELECT g.release FROM catalog_active a JOIN catalog_generations g "
                "ON g.generation_id=a.generation_id WHERE a.package_id=? AND a.kind=?",
                (self.expected_package_id, self.expected_kind),
            ).fetchone()
            if current and current["release"] >= candidate["release"]:
                connection.commit()
                return False
            connection.execute(
                "INSERT INTO catalog_active VALUES (?, ?, ?) "
                "ON CONFLICT(package_id, kind) DO UPDATE SET generation_id=excluded.generation_id",
                (self.expected_package_id, self.expected_kind, generation),
            )
            self._before_activate_commit(connection)
            connection.commit()
            return True

    def import_package(self, manifest_path: str | Path, package_path: str | Path) -> bool:
        return self.activate(self.stage(manifest_path, package_path))

    def read_active_package(self) -> dict[str, Any]:
        with self._connect() as connection:
            # Pin one snapshot: concurrent activation cannot mix generation membership.
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT g.generation_id, g.header FROM catalog_active a JOIN catalog_generations g "
                "ON g.generation_id=a.generation_id "
                "WHERE a.package_id=? AND a.kind=? AND g.complete=1",
                (self.expected_package_id, self.expected_kind),
            ).fetchone()
            if not row:
                raise OfflineImportError("no_active_package", "No complete package is active")
            result = parse_json(row["header"])
            for plural, entity, keys in (
                ("sources", "sources", "v.source_id=m.source_id"),
                (
                    "products",
                    "product_versions",
                    "v.product_id=m.product_id AND v.revision=m.revision",
                ),
                ("rations", "ration_versions", "v.ration_id=m.ration_id AND v.revision=m.revision"),
            ):
                records = connection.execute(
                    f"SELECT v.payload FROM catalog_generation_{plural} m "
                    f"JOIN catalog_{entity} v ON {keys} "
                    "WHERE m.generation_id=? ORDER BY m.position",
                    (row["generation_id"],),
                )
                result[plural] = [parse_json(record["payload"]) for record in records]
            connection.commit()
            return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and atomically import an offline catalogue"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--expected-package-id", required=True)
    parser.add_argument("--expected-kind", choices=("demo", "official"), required=True)
    args = parser.parse_args(argv)
    try:
        catalog = OfflineCatalog(args.database, args.expected_package_id, args.expected_kind)
        changed = catalog.import_package(args.manifest, args.package)
        active = catalog.read_active_package()
    except (OfflineImportError, CatalogValidationError, OSError, sqlite3.Error) as exc:
        print(f"Offline import failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "activated": changed,
                "package_id": active["package_id"],
                "kind": active["kind"],
                "release": active["release"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
