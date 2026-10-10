"""PostgreSQL -> exported gzip -> persistent reference SQLite and official HTTP."""

import copy
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.export import (
    artifact_path,
    artifact_relative_path,
    export_package,
    publish_package,
    write_immutable,
)
from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    ProductVersion,
)
from calorie_app.modules.catalog.offline_import import OfflineCatalog
from calorie_app.modules.catalog.repository import read_package
from calorie_app.modules.catalog.service import (
    import_catalog,
    ordered_package,
    read_product,
    search_products,
)
from calorie_app.modules.catalog.validation import (
    CatalogValidationError,
    canonical_json,
    validate_definition,
)

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def catalog_db(database):
    engine, migrate, url = database
    # Only the guarded dedicated *_test DB: tests may reset their own catalog,
    # never a user journal or development/prod DB. TRUNCATE bypasses delete guards.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE app.product_sources, app.products, app.rations, app.offline_channels CASCADE"
        )
    try:
        yield engine, migrate, url
    finally:
        # Recovery/expiry evidence must remain immutable in production. This
        # disposable test graph is removed explicitly before older E1 downgrade
        # scenarios, rather than weakening either migration's downgrade guard.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "TRUNCATE app.product_sources, app.products, app.rations, "
                "app.offline_channels CASCADE"
            )


def synthetic_official(*, package_id=OFFICIAL_PACKAGE_ID, release=1, count=2):
    """Complete isolated mechanical fixture; never promoted to the official seed."""
    source_id = str(uuid4())
    product_id = str(uuid4())
    return {
        "package_id": str(package_id),
        "release": release,
        "schema_version": 1,
        "min_reader_version": 1,
        "published_at": "2026-10-09T12:00:00Z",
        "kind": "official",
        "counts": {"products": 1, "rations": count, "components": count, "sources": 1},
        "sources": [
            {
                "source_id": source_id,
                "document_id": "Izolowany syntetyczny fixture testowy E2",
                "url": None,
                "checked_on": "2026-10-09",
                "market": "TEST",
                "manufacturer": "TEST",
                "variant": "fixture",
                "basis": "per_100_ml",
                "status": "verified",
                "missing_data": [],
                "notes": ["Dane służą wyłącznie testom mechanizmu, nie etykiecie."],
            }
        ],
        "products": [
            {
                "product_id": product_id,
                "revision": 1,
                "name": "Napój fixture",
                "aliases": ["Baza testowa"],
                "brand": "Marka fixture",
                "variant": "wersja testowa",
                "basis_unit": "ml",
                "nutrition_per_100": {
                    "energy_kcal": "42",
                    "protein_g": "0",
                    "fat_g": "0",
                    "carbs_g": "10.6",
                },
                "package_quantity": {"amount": "250", "unit": "ml"},
                "density_g_per_ml": None,
                "source_id": source_id,
                "source_locator": "/fixture/1",
                "status": "verified",
                "preparation": None,
            }
        ],
        "rations": [
            {
                "ration_id": str(uuid4()),
                "revision": 1,
                "name": f"Racja testowa {i}",
                "manufacturer": "TEST",
                "variant": None,
                "status": "verified",
                "source_id": source_id,
                "complete": True,
                "excluded_items": [],
                "components": [
                    {
                        "position": 1,
                        "group": "fixture",
                        "product": {"product_id": product_id, "revision": 1},
                        "quantity": {"amount": "250", "unit": "ml"},
                        "optional": False,
                    }
                ],
            }
            for i in range(count)
        ],
    }


def next_release(value, release):
    result = copy.deepcopy(value)
    result["release"] = release
    return result


def table_counts(engine):
    with engine.connect() as connection:
        return {
            table: connection.scalar(text(f"SELECT count(*) FROM app.{table}"))
            for table in (
                "product_sources",
                "product_versions",
                "ration_versions",
                "offline_packages",
                "offline_channels",
            )
        }


def write_artifact(directory, artifact):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "manifest.json"
    package = directory / artifact.manifest["path"]
    manifest.write_bytes(canonical_json(artifact.manifest))
    package.write_bytes(artifact.compressed)
    return manifest, package


def active_release(engine, package_id):
    with Session(engine) as session:
        return session.get(OfflineChannel, package_id).active_release


def test_real_demo_roundtrip_and_repeat(catalog_db, tmp_path):
    engine, _, _ = catalog_db
    demo = json.loads((ROOT / "backend/data/demo/seed.json").read_bytes())
    package_id = UUID(demo["package_id"])
    assert import_catalog(engine, demo).created
    assert not import_catalog(engine, demo).created
    before = table_counts(engine)
    first = export_package(engine, package_id, 1)
    second = export_package(engine, package_id, 1)
    assert first.raw == second.raw and first.compressed == second.compressed
    assert first.compressed == (ROOT / "backend/data/demo/export/base-pl.1.json.gz").read_bytes()
    assert first.manifest == json.loads(
        (ROOT / "backend/data/demo/export/manifest.json").read_bytes()
    )
    assert gzip.decompress(first.compressed) == first.raw
    assert first.compressed[:4] == b"\x1f\x8b\x08\x00"
    assert first.compressed[4:8] == b"\0\0\0\0"
    assert hashlib.sha256(first.compressed).hexdigest() == first.manifest["sha256"]
    reader = OfflineCatalog(tmp_path / "catalog.sqlite", demo["package_id"], "demo")
    artifacts = write_artifact(tmp_path / "export", first)
    assert reader.import_package(*artifacts)
    assert reader.read_active_package() == ordered_package(demo)
    assert not reader.import_package(*artifacts)
    assert publish_package(engine, package_id, 1, tmp_path / "storage") == first.manifest
    assert publish_package(engine, package_id, 1, tmp_path / "storage") == first.manifest
    assert table_counts(engine) == before
    assert active_release(engine, package_id) == 1


@pytest.mark.parametrize("collision", ["source", "product", "ration", "release"])
def test_import_conflicts_are_atomic(catalog_db, collision):
    engine, _, _ = catalog_db
    original = synthetic_official()
    import_catalog(engine, original)
    changed = next_release(original, 2)
    # A new source is written before a later immutable-version conflict.
    extra_source = copy.deepcopy(original["sources"][0])
    extra_source["source_id"] = str(uuid4())
    changed["sources"].append(extra_source)
    changed["counts"]["sources"] += 1
    if collision == "source":
        changed["sources"][0]["notes"].append("different source snapshot")
    elif collision == "release":
        changed["release"] = 1
        changed["published_at"] = "2026-10-09T13:00:00Z"
    else:
        changed[collision + "s"][0]["name"] += " changed"
    before = table_counts(engine)
    with pytest.raises(CatalogValidationError):
        import_catalog(engine, changed)
    assert table_counts(engine) == before
    with Session(engine) as session:
        assert read_package(session, OFFICIAL_PACKAGE_ID, 1) == ordered_package(original)


@pytest.mark.parametrize("invalid", ["fk", "source", "density_source", "unit", "counts"])
def test_bad_graph_is_rejected_before_mutation(catalog_db, invalid):
    engine, _, _ = catalog_db
    bad = synthetic_official()
    if invalid == "fk":
        bad["rations"][0]["components"][0]["product"]["revision"] = 999
    elif invalid == "source":
        bad["products"][0]["source_id"] = str(uuid4())
    elif invalid == "density_source":
        bad["products"][0]["density_g_per_ml"] = {"amount": "1", "source_id": str(uuid4())}
    elif invalid == "unit":
        bad["rations"][0]["components"][0]["quantity"]["unit"] = "g"
    else:
        bad["counts"]["components"] += 1
    before = table_counts(engine)
    with pytest.raises(CatalogValidationError):
        import_catalog(engine, bad)
    assert table_counts(engine) == before


def test_new_revisions_keep_exact_history(catalog_db, tmp_path):
    engine, _, _ = catalog_db
    first = synthetic_official(count=1)
    import_catalog(engine, first)
    old_artifact = export_package(engine, OFFICIAL_PACKAGE_ID, 1)
    newer = next_release(first, 2)
    newer["products"][0]["revision"] = 2
    newer["products"][0]["nutrition_per_100"]["energy_kcal"] = "44"
    newer["rations"][0]["revision"] = 2
    newer["rations"][0]["components"][0]["product"]["revision"] = 2
    import_catalog(engine, newer)
    assert export_package(engine, OFFICIAL_PACKAGE_ID, 1) == old_artifact
    new_artifact = export_package(engine, OFFICIAL_PACKAGE_ID, 2)
    reader = OfflineCatalog(tmp_path / "offline.sqlite", str(OFFICIAL_PACKAGE_ID), "official")
    assert reader.import_package(*write_artifact(tmp_path / "old", old_artifact))
    assert reader.import_package(*write_artifact(tmp_path / "new", new_artifact))
    assert reader.read_active_package() == ordered_package(newer)
    assert not reader.import_package(*write_artifact(tmp_path / "again", old_artifact))
    with Session(engine) as session:
        assert (
            session.get(ProductVersion, (UUID(first["products"][0]["product_id"]), 1)).energy_kcal
            == 42
        )


@pytest.mark.parametrize("phase", ["before_write", "after_write", "before_commit", "commit"])
def test_publication_failure_preserves_old_manifest(catalog_db, tmp_path, phase):
    engine, _, url = catalog_db
    original = synthetic_official()
    import_catalog(engine, original)
    root = tmp_path / "storage"
    old = publish_package(engine, OFFICIAL_PACKAGE_ID, 1, root)
    import_catalog(engine, next_release(original, 2))

    def fail_commit(connection):
        raise OSError("injected database commit failure")

    def fail(stage):
        if phase == "commit" and stage == "before_commit":
            event.listen(engine, "commit", fail_commit, once=True)
        elif stage == phase:
            raise OSError("injected failure")

    try:
        with pytest.raises(OSError):
            publish_package(engine, OFFICIAL_PACKAGE_ID, 2, root, fault_hook=fail)
    finally:
        if event.contains(engine, "commit", fail_commit):
            event.remove(engine, "commit", fail_commit)
    assert active_release(engine, OFFICIAL_PACKAGE_ID) == 1
    with Session(engine) as session:
        assert session.get(OfflinePackage, (OFFICIAL_PACKAGE_ID, 2)).state == "draft"
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=root), engine=engine)
    ) as client:
        assert client.get("/api/v1/offline-package/manifest").json() == old
        assert client.get("/api/v1/offline-package/base-pl.2.json.gz").status_code == 404
        assert client.get("/api/v1/offline-package/base-pl.1.json.gz").status_code == 200


def test_identical_parallel_publications_no_duplicate(catalog_db, tmp_path):
    engine, _, _ = catalog_db
    import_catalog(engine, synthetic_official())
    barrier = Barrier(2)

    def wait_after_write(stage):
        if stage == "after_write":
            barrier.wait(timeout=10)

    def publish(_):
        return publish_package(
            engine, OFFICIAL_PACKAGE_ID, 1, tmp_path, fault_hook=wait_after_write
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.map(publish, (1, 2))
    assert first == second
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(OfflinePackage)) == 1
    assert active_release(engine, OFFICIAL_PACKAGE_ID) == 1


def test_parallel_releases_finishing_backwards_cannot_regress(catalog_db, tmp_path):
    engine, _, _ = catalog_db
    original = synthetic_official()
    import_catalog(engine, original)
    import_catalog(engine, next_release(original, 2))
    written = Event()
    newer_done = Event()

    def delay_old(stage):
        if stage == "after_write":
            written.set()
            assert newer_done.wait(15)

    with ThreadPoolExecutor(max_workers=2) as workers:
        old = workers.submit(
            publish_package, engine, OFFICIAL_PACKAGE_ID, 1, tmp_path, fault_hook=delay_old
        )
        assert written.wait(15)
        newer = workers.submit(publish_package, engine, OFFICIAL_PACKAGE_ID, 2, tmp_path)
        newer.result(timeout=15)
        newer_done.set()
        old.result(timeout=15)
    assert active_release(engine, OFFICIAL_PACKAGE_ID) == 2
    assert (tmp_path / "official" / str(OFFICIAL_PACKAGE_ID) / "base-pl.1.json.gz").exists()


def test_existing_artifact_cannot_be_overwritten(catalog_db, tmp_path):
    engine, _, _ = catalog_db
    import_catalog(engine, synthetic_official())
    relative = artifact_relative_path(OFFICIAL_PACKAGE_ID, "official", 1)
    path = artifact_path(tmp_path, relative)
    write_immutable(path, b"existing bytes")
    with pytest.raises(CatalogValidationError, match="catalog_artifact_conflict"):
        publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    assert path.read_bytes() == b"existing bytes"
    assert active_release(engine, OFFICIAL_PACKAGE_ID) is None


def test_missing_or_corrupted_registered_file_is_unavailable(catalog_db, tmp_path):
    engine, _, url = catalog_db
    import_catalog(engine, synthetic_official())
    manifest = publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    path = artifact_path(tmp_path, artifact_relative_path(OFFICIAL_PACKAGE_ID, "official", 1))
    path.write_bytes(b"corrupted storage")
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        for target in ("manifest", "base-pl.1.json.gz"):
            response = client.get("/api/v1/offline-package/" + target)
            assert response.status_code == 503
            assert response.json()["code"] == "service_unavailable"
        path.unlink()
        assert client.get("/api/v1/offline-package/manifest").status_code == 503
    assert active_release(engine, OFFICIAL_PACKAGE_ID) == manifest["release"]


def test_official_rejects_demo_and_public_does_not_leak(catalog_db, tmp_path):
    engine, _, url = catalog_db
    demo = json.loads((ROOT / "backend/data/demo/seed.json").read_bytes())
    fake_official = copy.deepcopy(demo)
    fake_official.update(kind="official", package_id=str(OFFICIAL_PACKAGE_ID))
    with pytest.raises(CatalogValidationError):
        import_catalog(engine, fake_official)
    package_id = UUID(demo["package_id"])
    import_catalog(engine, demo)
    publish_package(engine, package_id, 1, tmp_path)
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        assert client.get("/api/v1/rations").json() == {"items": [], "next_page_token": None}
        for path in (
            "/api/v1/rations/" + demo["rations"][0]["ration_id"],
            "/api/v1/offline-package/manifest",
            "/api/v1/offline-package/base-pl.1.json.gz",
            "/api/v1/products",
            "/api/v1/products/" + demo["products"][0]["product_id"],
        ):
            response = client.get(path, headers={"Authorization": "Bearer anything"})
            assert response.status_code == 404
            assert response.json()["request_id"] == response.headers["x-request-id"]
        assert client.get("/api/v1/rations?include_demo=true").status_code == 422


@pytest.mark.parametrize("defect", ["source", "nutrition", "ration", "complete", "manufacturer"])
def test_incomplete_official_is_never_imported(catalog_db, defect):
    engine, _, _ = catalog_db
    value = synthetic_official()
    if defect == "source":
        value["sources"][0]["status"] = "unverified"
    elif defect == "nutrition":
        value["products"][0]["nutrition_per_100"]["fat_g"] = None
    elif defect == "ration":
        value["rations"][0]["status"] = "unverified"
    else:
        value["rations"][0][defect] = False if defect == "complete" else None
    with pytest.raises(CatalogValidationError):
        import_catalog(engine, value)
    assert table_counts(engine)["offline_packages"] == 0


def test_channel_and_package_identity_isolate_public_urls(catalog_db, tmp_path):
    engine, _, url = catalog_db
    demo = json.loads((ROOT / "backend/data/demo/seed.json").read_bytes())
    demo_id = UUID(demo["package_id"])
    foreign = synthetic_official(package_id=uuid4())
    import_catalog(engine, foreign)
    publish_package(engine, UUID(foreign["package_id"]), 1, tmp_path)
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        assert client.get("/api/v1/offline-package/manifest").status_code == 404
        assert client.get("/api/v1/rations").json()["items"] == []
        official = synthetic_official()
        import_catalog(engine, official)
        import_catalog(engine, demo)
        publish_package(engine, demo_id, 1, tmp_path)
        expected = publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
        assert client.get("/api/v1/offline-package/manifest").json() == expected
        body = client.get("/api/v1/offline-package/base-pl.1.json.gz").content
        assert hashlib.sha256(body).hexdigest() == expected["sha256"]
        assert (
            client.get("/api/v1/rations/" + foreign["rations"][0]["ration_id"]).status_code == 404
        )
        assert (tmp_path / "demo" / str(demo_id) / "base-pl.1.json.gz").read_bytes() != body


def test_official_http_bytes_pagination_and_versions(catalog_db, tmp_path, monkeypatch):
    engine, _, url = catalog_db
    first = synthetic_official(count=3)
    import_catalog(engine, first)
    # An unpublished verified revision must remain inaccessible.
    newer = next_release(first, 2)
    for ration in newer["rations"]:
        ration["revision"] = 2
        ration["name"] += " new"
    import_catalog(engine, newer)
    manifest = publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    runtime = create_engine(url, hide_parameters=True)

    @event.listens_for(runtime, "connect")
    def runtime_role(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE calorie_app_api")
        connection.commit()

    try:
        with TestClient(
            create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=runtime)
        ) as client:
            assert client.get("/health/ready").status_code == 200
            response = client.get("/api/v1/offline-package/manifest")
            assert response.status_code == 200 and response.json() == manifest
            validate_definition(response.json(), "Manifest")
            response = client.get("/api/v1/offline-package/base-pl.1.json.gz")
            assert response.headers["content-type"] == "application/gzip"
            assert "content-encoding" not in response.headers
            assert (
                int(response.headers["content-length"])
                == manifest["compressed_bytes"]
                == len(response.content)
            )
            assert hashlib.sha256(response.content).hexdigest() == manifest["sha256"]
            page = client.get("/api/v1/rations?limit=1").json()
            assert len(page["items"]) == 1 and page["next_page_token"]
            ration_id = page["items"][0]["ration_id"]
            assert client.get(f"/api/v1/rations/{ration_id}?revision=2").status_code == 404
            publish_package(engine, OFFICIAL_PACKAGE_ID, 2, tmp_path)
            items = page["items"]
            token = page["next_page_token"]
            while token is not None:
                response = client.get("/api/v1/rations", params={"limit": 1, "page_token": token})
                assert response.status_code == 200
                result = response.json()
                items += result["items"]
                token = result["next_page_token"]
            assert [r["ration_id"] for r in items] == sorted(
                r["ration_id"] for r in first["rations"]
            )
            assert all(r["revision"] == 1 for r in items)
            for ration in items:
                validate_definition(ration, "Ration")
            assert client.get(f"/api/v1/rations/{ration_id}").json()["revision"] == 2
            assert client.get(f"/api/v1/rations/{ration_id}?revision=1").json()["revision"] == 1
            assert client.get(
                "/api/v1/offline-package/base-pl.1.json.gz"
            ).content == response_bytes(engine, 1)
            assert (
                client.get(
                    "/api/v1/rations", params={"limit": 2, "page_token": page["next_page_token"]}
                ).status_code
                == 422
            )
            monkeypatch.setattr(
                "calorie_app.modules.catalog.router.database_now",
                lambda session: datetime.now(UTC) + timedelta(hours=2),
            )
            expired = client.get(
                "/api/v1/rations", params={"limit": 1, "page_token": page["next_page_token"]}
            )
            assert expired.status_code == 410 and expired.json()["code"] == "page_expired"
    finally:
        runtime.dispose()


def response_bytes(engine, release):
    return export_package(engine, OFFICIAL_PACKAGE_ID, release).compressed


@pytest.mark.parametrize(
    "suffix",
    [
        "/rations?limit=0",
        "/rations?limit=501",
        "/rations?page_token=broken",
        "/rations/not-uuid",
        "/offline-package/base-pl.0.json.gz",
        "/offline-package/base-pl.999999999999.json.gz",
        "/offline-package/%2e%2e%2fmanifest.json",
        "/offline-package/.temporary.tmp",
    ],
)
def test_http_invalid_and_traversal(catalog_db, tmp_path, suffix):
    engine, _, url = catalog_db
    import_catalog(engine, synthetic_official())
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        response = client.get("/api/v1" + suffix)
        assert response.status_code in {404, 422}
        assert response.json()["request_id"] == response.headers["x-request-id"]
    with pytest.raises(CatalogValidationError, match="catalog_artifact_path"):
        artifact_path(tmp_path, "../../outside.gz")


def test_internal_product_service_search_and_nullable(catalog_db):
    engine, _, _ = catalog_db
    value = synthetic_official()
    value.update(kind="demo", package_id=str(uuid4()))
    value["rations"] = value["rations"][:1]
    value["rations"][0]["complete"] = False
    value["counts"].update(rations=1, components=1)
    value["products"][0]["nutrition_per_100"].update(protein_g=None)
    package_id = UUID(value["package_id"])
    product_id = UUID(value["products"][0]["product_id"])
    import_catalog(engine, value)
    for query in ("NAPÓJ", "baza", "MARKA", "wersja"):
        found = search_products(engine, package_id, 1, query)
        assert len(found) == 1 and found[0]["product_id"] == str(product_id)
    assert search_products(engine, package_id, 1, "missing") == []
    assert read_product(engine, package_id, 1, product_id)["nutrition_per_100"]["protein_g"] is None
    assert read_product(engine, package_id, 1, product_id)["nutrition_per_100"]["fat_g"] == "0"
    assert read_product(engine, package_id, 1, product_id, 2) is None
