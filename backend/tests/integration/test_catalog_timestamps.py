"""UTC spelling, original-input recovery and immutable publication on PostgreSQL."""

import copy
import gzip
import hashlib
import json

import pytest
import test_catalog_delivery as delivery
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID, repository, service
from calorie_app.modules.catalog.cli import main as catalog_command
from calorie_app.modules.catalog.export import (
    artifact_path,
    artifact_relative_path,
    export_package,
    publish_package,
)
from calorie_app.modules.catalog.models import OfflinePackage
from calorie_app.modules.catalog.offline_import import OfflineCatalog
from calorie_app.modules.catalog.repository import manifest_data, read_package
from calorie_app.modules.catalog.service import (
    content_hash,
    import_catalog,
    ordered_package,
    recover_timestamp,
)
from calorie_app.modules.catalog.timestamps import normalize_timestamp
from calorie_app.modules.catalog.validation import CatalogValidationError, canonical_json

pytestmark = pytest.mark.integration
PREFIX = "2026-10-09T12:00:00"
catalog_db = delivery.catalog_db
synthetic_official = delivery.synthetic_official


def legacy_import(engine, value, monkeypatch):
    """The exact pre-fix behavior: hash input spelling, persist timestamptz."""
    with monkeypatch.context() as patch:
        patch.setattr(service, "normalize_timestamp", lambda package: package)
        patch.setattr(repository, "recovered_timestamp", lambda *args: None)
        return import_catalog(engine, value)


def package_record(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT to_jsonb(p) FROM app.offline_packages p"))


@pytest.mark.parametrize(
    "suffix", ["Z", ".000000Z", ".1Z", ".12Z", ".123Z", ".1234Z", ".12345Z", ".123456Z", ".100000Z"]
)
def test_all_e0_timestamps_roundtrip_repeat_and_publish(catalog_db, tmp_path, suffix):
    engine, _, url = catalog_db
    value = synthetic_official(count=1)
    value["published_at"] = PREFIX + suffix
    expected = normalize_timestamp(ordered_package(value))
    assert import_catalog(engine, value).created
    assert not import_catalog(engine, value).created
    with pytest.raises(CatalogValidationError, match="catalog_recovery_not_required"):
        recover_timestamp(engine, expected)
    equivalent = value | {"published_at": expected["published_at"]}
    assert not import_catalog(engine, equivalent).created
    artifact = export_package(engine, OFFICIAL_PACKAGE_ID, 1)
    assert json.loads(artifact.raw) == expected
    assert gzip.decompress(artifact.compressed) == artifact.raw
    assert hashlib.sha256(artifact.compressed).hexdigest() == artifact.manifest["sha256"]
    assert artifact.manifest["published_at"] == expected["published_at"]
    with Session(engine) as session:
        row = session.get(OfflinePackage, (OFFICIAL_PACKAGE_ID, 1))
        assert row.content_hash == hashlib.sha256(artifact.raw).hexdigest()
        assert read_package(session, OFFICIAL_PACKAGE_ID, 1) == expected
    assert publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path) == artifact.manifest
    before = package_record(engine)
    assert not import_catalog(engine, value).created
    assert not import_catalog(engine, equivalent).created
    assert publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path) == artifact.manifest
    assert package_record(engine) == before
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        assert client.get("/api/v1/offline-package/manifest").json() == artifact.manifest
        assert (
            client.get("/api/v1/offline-package/base-pl.1.json.gz").content == artifact.compressed
        )
    for changed in (PREFIX + ".000001Z", "2026-10-09T12:00:01Z"):
        if changed != expected["published_at"]:
            with pytest.raises(CatalogValidationError, match="catalog_release_conflict"):
                import_catalog(engine, value | {"published_at": changed})


@pytest.mark.parametrize("suffix", [".000000Z", ".1Z", ".12Z", ".123Z", ".1234Z", ".12345Z"])
def test_legacy_draft_explicit_proof_recovery(catalog_db, tmp_path, monkeypatch, suffix):
    engine, _, url = catalog_db
    original = synthetic_official(count=1)
    original["published_at"] = PREFIX + suffix
    legacy_import(engine, original, monkeypatch)
    before = package_record(engine)
    with pytest.raises(CatalogValidationError, match="catalog_release_conflict"):
        import_catalog(engine, original)
    with pytest.raises(CatalogValidationError, match="catalog_snapshot_conflict"):
        export_package(engine, OFFICIAL_PACKAGE_ID, 1)
    wrong_proof = copy.deepcopy(original)
    wrong_proof["sources"][0]["notes"].append("unproven evidence")
    with pytest.raises(CatalogValidationError, match="catalog_recovery_input_conflict"):
        recover_timestamp(engine, wrong_proof)
    with pytest.raises(CatalogValidationError, match="catalog_recovery_input_conflict"):
        recover_timestamp(engine, normalize_timestamp(original))
    assert recover_timestamp(engine, original).created
    assert not recover_timestamp(engine, original).created
    assert package_record(engine) == before
    assert not import_catalog(engine, original).created
    assert not import_catalog(engine, normalize_timestamp(original)).created
    artifact = export_package(engine, OFFICIAL_PACKAGE_ID, 1)
    assert artifact.raw == canonical_json(ordered_package(original))
    assert content_hash(json.loads(artifact.raw)) == before["content_hash"]
    assert artifact.manifest["published_at"] == original["published_at"]
    with engine.connect() as connection:
        audit = connection.execute(text("SELECT * FROM app.catalog_timestamp_recoveries")).one()
        assert audit.original_input.encode("utf-8") == artifact.raw
        assert audit.original_content_hash == hashlib.sha256(artifact.raw).hexdigest()
        assert audit.recovered_by and audit.recovered_at
    with Session(engine) as session:
        row = session.get(OfflinePackage, (OFFICIAL_PACKAGE_ID, 1))
        assert read_package(session, OFFICIAL_PACKAGE_ID, 1) == ordered_package(original)
        # Publication metadata is populated only by publish_package.
        assert row.state == "draft" and row.sha256 is None
    assert publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path) == artifact.manifest
    assert publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path) == artifact.manifest
    assert not import_catalog(engine, original).created
    assert not import_catalog(engine, normalize_timestamp(original)).created
    with Session(engine) as session:
        row = session.get(OfflinePackage, (OFFICIAL_PACKAGE_ID, 1))
        assert manifest_data(session, row, "official") == artifact.manifest
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        manifest = client.get("/api/v1/offline-package/manifest").json()
        downloaded = client.get("/api/v1/offline-package/base-pl.1.json.gz").content
        assert manifest == artifact.manifest
        assert downloaded == artifact.compressed
        assert hashlib.sha256(downloaded).hexdigest() == manifest["sha256"]
    reader = OfflineCatalog(tmp_path / "offline.sqlite", str(OFFICIAL_PACKAGE_ID), "official")
    manifest_path, package_path = tmp_path / "manifest.json", tmp_path / "package.gz"
    manifest_path.write_bytes(canonical_json(artifact.manifest))
    package_path.write_bytes(artifact.compressed)
    assert reader.import_package(manifest_path, package_path)
    assert reader.read_active_package() == ordered_package(original)
    with pytest.raises(CatalogValidationError, match="catalog_recovery_requires_draft"):
        recover_timestamp(engine, original)


@pytest.mark.parametrize("suffix", ["Z", ".100000Z", ".123456Z"])
def test_upgrade_keeps_old_publication_bytes_and_hash(catalog_db, tmp_path, monkeypatch, suffix):
    engine, migrate, url = catalog_db
    migrate("downgrade", "0003_catalog_offline")
    try:
        original = synthetic_official(count=1)
        original["published_at"] = PREFIX + suffix
        legacy_import(engine, original, monkeypatch)
        with monkeypatch.context() as patch:
            patch.setattr(repository, "recovered_timestamp", lambda *args: None)
            manifest = publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
        before = package_record(engine)
        path = artifact_path(tmp_path, artifact_relative_path(OFFICIAL_PACKAGE_ID, "official", 1))
        stored_bytes = path.read_bytes()
        migrate("upgrade", "head")
        assert package_record(engine) == before
        assert not import_catalog(engine, original).created
        assert export_package(engine, OFFICIAL_PACKAGE_ID, 1).compressed == stored_bytes
        assert publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path) == manifest
        with TestClient(
            create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
        ) as client:
            assert client.get("/api/v1/offline-package/manifest").json() == manifest
            assert client.get("/api/v1/offline-package/base-pl.1.json.gz").content == stored_bytes
    finally:
        migrate("upgrade", "head")


@pytest.mark.parametrize("defect", ["graph", "source_hash", "product_hash", "ration_hash"])
def test_recovery_checks_entire_graph_and_child_hash(catalog_db, monkeypatch, defect):
    engine, _, _ = catalog_db
    original = synthetic_official(count=1) | {"published_at": PREFIX + ".1Z"}
    stored = copy.deepcopy(original)
    real_hash = service.content_hash
    if defect == "graph":
        stored["products"][0]["name"] += " changed graph"

    def corrupted_hash(value):
        if defect == "graph" and "package_id" in value:
            return real_hash(ordered_package(original))
        identifying_field = {
            "source_hash": "document_id",
            "product_hash": "nutrition_per_100",
            "ration_hash": "components",
        }.get(defect)
        if identifying_field is not None and identifying_field in value:
            return "f" * 64
        return real_hash(value)

    with monkeypatch.context() as patch:
        patch.setattr(service, "content_hash", corrupted_hash)
        legacy_import(engine, stored, patch)
    before = package_record(engine)
    code = "catalog_recovery_graph_conflict" if defect == "graph" else "catalog_version_conflict"
    with pytest.raises(CatalogValidationError, match=code):
        recover_timestamp(engine, original)
    assert package_record(engine) == before
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app.catalog_timestamp_recoveries")) == 0


def test_recovery_audit_permissions_guards_and_downgrade(catalog_db, monkeypatch):
    engine, migrate, _ = catalog_db
    original = synthetic_official(count=1) | {"published_at": PREFIX + ".1Z"}
    legacy_import(engine, original, monkeypatch)
    for role in ("calorie_app_api", "calorie_app_worker"):
        with pytest.raises(ProgrammingError), engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
            connection.exec_driver_sql(
                "INSERT INTO app.catalog_timestamp_recoveries "
                "SELECT * FROM app.catalog_timestamp_recoveries"
            )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.catalog_timestamp_recoveries "
                "(package_id, release, published_at_text, original_content_hash, "
                "original_input) VALUES (:id,1,:stamp,:hash,:proof)"
            ),
            {
                "id": OFFICIAL_PACKAGE_ID,
                "stamp": original["published_at"],
                "hash": content_hash(ordered_package(original)),
                "proof": canonical_json(ordered_package(original | {"kind": "demo"})).decode(
                    "utf-8"
                ),
            },
        )
    recover_timestamp(engine, original)
    for statement in (
        "UPDATE app.catalog_timestamp_recoveries SET published_at_text='bad'",
        "DELETE FROM app.catalog_timestamp_recoveries",
        "UPDATE app.offline_packages SET content_hash=repeat('a',64)",
        "UPDATE app.offline_packages SET published_at=published_at + interval '1 sec'",
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql(statement)
    with pytest.raises(IntegrityError):
        migrate("downgrade", "0003_catalog_offline")
    migrate("upgrade", "head")
    assert not import_catalog(engine, original).created


def test_operator_cli_requires_original_proof(catalog_db, tmp_path, monkeypatch, capsys):
    engine, _, _ = catalog_db
    original = synthetic_official(count=1) | {"published_at": PREFIX + ".1Z"}
    legacy_import(engine, original, monkeypatch)
    proof = tmp_path / "original.json"
    proof.write_bytes(canonical_json(normalize_timestamp(original)))
    with pytest.raises(SystemExit) as rejection:
        catalog_command(["recover-timestamp", "--input", str(proof)])
    assert rejection.value.code == 1
    assert capsys.readouterr().err == "Catalog rejected: catalog_recovery_input_conflict\n"
    proof.write_bytes(canonical_json(original))
    assert catalog_command(["recover-timestamp", "--input", str(proof)]) == 0
    assert json.loads(capsys.readouterr().out)["created"] is True
    assert catalog_command(["recover-timestamp", "--input", str(proof)]) == 0
    assert json.loads(capsys.readouterr().out)["created"] is False
    assert export_package(engine, OFFICIAL_PACKAGE_ID, 1).raw == canonical_json(
        ordered_package(original)
    )
