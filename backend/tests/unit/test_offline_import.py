"""Reference SQLite evidence; these tests do not claim Android/Room coverage."""

import copy
import gzip
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from calorie_app.modules.catalog import offline_import
from calorie_app.modules.catalog.offline_import import OfflineCatalog, OfflineImportError
from calorie_app.modules.catalog.validation import CatalogValidationError, canonical_json

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "valid"
PACKAGE_ID = "47bdff67-e58b-5437-919b-ec00159afbc5"


@pytest.fixture
def package():
    return json.loads((EXAMPLES / "catalog-demo.json").read_bytes())


@pytest.fixture
def catalog(tmp_path):
    return OfflineCatalog(tmp_path / "catalog.sqlite", PACKAGE_ID, "demo")


def artifacts(tmp_path, package, *, raw=None, compressed=None, manifest_changes=None):
    """Build actual gzip bytes with a matching manifest, including malformed fixtures."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(package) if raw is None else raw
    compressed = gzip.compress(raw, mtime=0) if compressed is None else compressed
    manifest = {key: package[key] for key in offline_import._HEADERS}
    manifest.update(
        path=f"base-pl.{package['release']}.json.gz",
        compressed_bytes=len(compressed),
        uncompressed_bytes=len(raw),
        sha256=hashlib.sha256(compressed).hexdigest(),
        source_ids=[source["source_id"] for source in package["sources"]],
    )
    manifest.update(manifest_changes or {})
    manifest_path = tmp_path / "manifest.json"
    package_path = tmp_path / manifest["path"]
    manifest_path.write_bytes(canonical_json(manifest))
    package_path.write_bytes(compressed)
    return manifest_path, package_path


def test_exact_e0_gzip_roundtrip_and_repeat(catalog):
    inputs = EXAMPLES / "catalog-manifest.json", EXAMPLES / "base-pl.1.json.gz"
    assert catalog.import_package(*inputs)
    expected = json.loads((EXAMPLES / "catalog-demo.json").read_bytes())
    assert catalog.read_active_package() == expected
    generation = catalog.stage(*inputs)
    assert catalog.stage(*inputs) == generation
    assert not catalog.activate(generation)
    with sqlite3.connect(catalog.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM catalog_generations").fetchone() == (1,)
        stored = db.execute(
            "SELECT energy_kcal, typeof(energy_kcal), package_amount, typeof(package_amount) "
            "FROM catalog_product_versions WHERE energy_kcal='385.555556'"
        ).fetchone()
        assert stored == ("385.555556", "text", "90", "text")


def test_unknown_zero_and_density_are_preserved_exactly(tmp_path, package, catalog):
    product = package["products"][0]
    product["nutrition_per_100"].update(energy_kcal=None, protein_g="0")
    product["density_g_per_ml"] = {
        "amount": "1.234567",
        "source_id": package["sources"][0]["source_id"],
    }
    product["package_quantity"]["unit"] = "ml"
    assert catalog.import_package(*artifacts(tmp_path, package))
    assert catalog.read_active_package() == package
    with sqlite3.connect(catalog.database_path) as db:
        assert db.execute(
            "SELECT energy_kcal, protein_g, density_amount, typeof(density_amount) "
            "FROM catalog_product_versions WHERE product_id=?",
            (product["product_id"],),
        ).fetchone() == (None, "0", "1.234567", "text")


def test_stage_restart_and_reverse_activation(tmp_path, package, catalog):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    package["release"] = 2
    older = catalog.stage(*artifacts(tmp_path / "two", package))
    package["release"] = 3
    newer = catalog.stage(*artifacts(tmp_path / "three", package))
    restarted = OfflineCatalog(catalog.database_path, PACKAGE_ID, "demo")
    assert restarted.read_active_package()["release"] == 1
    assert restarted.activate(newer)
    assert not restarted.activate(older)
    assert restarted.read_active_package()["release"] == 3


def test_concurrent_activation_never_goes_back(tmp_path, package, catalog):
    inputs = []
    for release in (1, 2, 3):
        package["release"] = release
        inputs.append(catalog.stage(*artifacts(tmp_path / str(release), package)))
    barrier = Barrier(3)

    def activate(generation):
        separate = OfflineCatalog(catalog.database_path, PACKAGE_ID, "demo")
        barrier.wait(timeout=10)
        return separate.activate(generation)

    with ThreadPoolExecutor(max_workers=3) as workers:
        results = list(workers.map(activate, inputs))
    assert any(results)
    assert catalog.read_active_package()["release"] == 3


def test_concurrent_identical_staging_has_one_generation(tmp_path, package, catalog):
    inputs = artifacts(tmp_path, package)
    barrier = Barrier(2)

    def stage(_):
        separate = OfflineCatalog(catalog.database_path, PACKAGE_ID, "demo")
        barrier.wait(timeout=10)
        return separate.stage(*inputs)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.map(stage, (1, 2))
    assert first == second


def test_same_release_changed_gzip_rejected(tmp_path, package, catalog):
    assert catalog.import_package(*artifacts(tmp_path / "original", package))
    raw = canonical_json(package)
    changed_gzip = gzip.compress(raw, mtime=123)
    with pytest.raises(OfflineImportError, match="different bytes"):
        catalog.stage(*artifacts(tmp_path / "changed", package, compressed=changed_gzip))
    assert catalog.read_active_package() == package


@pytest.mark.parametrize("entity", ["product", "ration", "source"])
@pytest.mark.parametrize("other_package", [False, True])
def test_uuid_version_immutable_globally(tmp_path, package, catalog, entity, other_package):
    original = copy.deepcopy(package)
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    package["release"] = 2
    if entity == "source":
        package["sources"][0]["notes"].append("New content under the old source snapshot")
    else:
        package[entity + "s"][0]["name"] += " changed"
    importer = catalog
    if other_package:
        package["package_id"] = str(uuid4())
        importer = OfflineCatalog(catalog.database_path, package["package_id"], "demo")
    with pytest.raises(OfflineImportError) as failure:
        importer.stage(*artifacts(tmp_path / "two", package))
    assert failure.value.code == "version_conflict"
    assert catalog.read_active_package() == original
    with sqlite3.connect(catalog.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM catalog_generations").fetchone() == (1,)


def test_history_outbox_and_pinned_versions_survive(tmp_path, package, catalog):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    product_id = package["products"][0]["product_id"]
    with sqlite3.connect(catalog.database_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY, product_id TEXT, revision INTEGER, "
            "snapshot TEXT, FOREIGN KEY(product_id, revision) "
            "REFERENCES catalog_product_versions(product_id, revision))"
        )
        db.execute("CREATE TABLE outbox (id INTEGER PRIMARY KEY, payload BLOB)")
        db.execute("INSERT INTO history VALUES (1, ?, 1, 'original snapshot')", (product_id,))
        db.execute("INSERT INTO outbox VALUES (1, ?)", (b"immutable pending operation",))
    package["release"] = 2
    package["products"][0]["revision"] = 2
    package["products"][0]["nutrition_per_100"]["energy_kcal"] = "88"
    package["rations"][0]["revision"] = 2
    package["rations"][0]["components"][0]["product"]["revision"] = 2
    assert catalog.import_package(*artifacts(tmp_path / "two", package))
    assert catalog.read_active_package() == package
    with sqlite3.connect(catalog.database_path) as db:
        assert db.execute("SELECT * FROM history").fetchall() == [
            (1, product_id, 1, "original snapshot")
        ]
        assert db.execute("SELECT * FROM outbox").fetchall() == [
            (1, b"immutable pending operation")
        ]
        assert db.execute(
            "SELECT revision, energy_kcal FROM catalog_product_versions "
            "WHERE product_id=? ORDER BY revision",
            (product_id,),
        ).fetchall() == [(1, "87"), (2, "88")]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("hook", ["_before_stage_commit", "_before_activate_commit"])
def test_full_disk_before_commit_preserves_active(tmp_path, package, catalog, monkeypatch, hook):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    original = copy.deepcopy(package)
    package["release"] = 2

    def full_disk(connection):
        # SQLite's real page budget makes a write fail with SQLITE_FULL.
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={page_count}")
        connection.execute("CREATE TABLE catalog_failure_probe (payload BLOB)")
        connection.execute("INSERT INTO catalog_failure_probe VALUES (zeroblob(1048576))")

    monkeypatch.setattr(catalog, hook, full_disk)
    with pytest.raises(sqlite3.OperationalError, match="full"):
        catalog.import_package(*artifacts(tmp_path / "two", package))
    assert (
        OfflineCatalog(catalog.database_path, PACKAGE_ID, "demo").read_active_package() == original
    )
    with sqlite3.connect(catalog.database_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='catalog_failure_probe'"
        ).fetchone() == (0,)


@pytest.mark.parametrize("hook", ["_before_stage_commit", "_before_activate_commit"])
def test_interruption_before_commit_preserves_active(tmp_path, package, catalog, monkeypatch, hook):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    original = copy.deepcopy(package)
    package["release"] = 2

    def interrupt(_):
        raise KeyboardInterrupt("process interrupted")

    monkeypatch.setattr(catalog, hook, interrupt)
    with pytest.raises(KeyboardInterrupt):
        catalog.import_package(*artifacts(tmp_path / "two", package))
    assert (
        OfflineCatalog(catalog.database_path, PACKAGE_ID, "demo").read_active_package() == original
    )


@pytest.mark.parametrize(
    "mutation", ["hash", "compressed_size", "uncompressed_size", "header", "source_ids", "path"]
)
def test_manifest_mismatches_preserve_active(tmp_path, package, catalog, mutation):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    original = copy.deepcopy(package)
    package["release"] = 2
    changes = {
        "hash": {"sha256": "0" * 64},
        "compressed_size": {"compressed_bytes": 1},
        "uncompressed_size": {"uncompressed_bytes": 1},
        "header": {"published_at": "2026-10-10T12:00:00Z"},
        "source_ids": {"source_ids": [str(uuid4())]},
        "path": {"path": "base-pl.3.json.gz"},
    }
    with pytest.raises((OfflineImportError, CatalogValidationError)):
        catalog.stage(*artifacts(tmp_path / "two", package, manifest_changes=changes[mutation]))
    assert catalog.read_active_package() == original


@pytest.mark.parametrize(
    "mutation", ["truncated", "crc", "concatenated", "trailing", "flags", "header"]
)
def test_invalid_gzip_rejected(tmp_path, package, catalog, mutation):
    raw = canonical_json(package)
    data = bytearray(gzip.compress(raw, mtime=0))
    if mutation == "truncated":
        data = data[:-1]
    elif mutation == "crc":
        data[-8] ^= 1
    elif mutation == "concatenated":
        data += gzip.compress(b"{}", mtime=0)
    elif mutation == "trailing":
        data += b"garbage"
    elif mutation == "flags":
        data[3] |= 0x20
    else:
        data[0] = 0
    with pytest.raises(OfflineImportError) as failure:
        catalog.stage(*artifacts(tmp_path, package, raw=raw, compressed=bytes(data)))
    assert failure.value.code == "invalid_gzip"


def test_decompression_bomb_bounded_before_parse(tmp_path, package, catalog, monkeypatch):
    raw = b" " * (offline_import.MAX_UNCOMPRESSED_BYTES + 1)
    compressed = gzip.compress(raw, mtime=0)
    inputs = artifacts(
        tmp_path,
        package,
        raw=raw,
        compressed=compressed,
        manifest_changes={"uncompressed_bytes": offline_import.MAX_UNCOMPRESSED_BYTES},
    )
    # The read_manifest parser must still execute; count only the subsequent package parse.
    parse = offline_import.parse_json
    calls = []

    def record_parse(data):
        calls.append(len(data))
        return parse(data)

    monkeypatch.setattr(offline_import, "parse_json", record_parse)
    with pytest.raises(OfflineImportError) as failure:
        catalog.stage(*inputs)
    assert failure.value.code == "uncompressed_size"
    assert len(calls) == 1


def test_oversize_compressed_input_bounded(tmp_path, package, catalog, monkeypatch):
    inputs = artifacts(tmp_path, package)
    monkeypatch.setattr(offline_import, "MAX_COMPRESSED_BYTES", 1024)
    with pytest.raises(OfflineImportError) as failure:
        catalog.stage(*inputs)
    assert failure.value.code == "compressed_size"


def test_oversize_manifest_rejected_before_parse(tmp_path, catalog):
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b" " * (offline_import.MAX_MANIFEST_BYTES + 1))
    with pytest.raises(OfflineImportError) as failure:
        catalog.stage(manifest, tmp_path / "absent.gz")
    assert failure.value.code == "manifest_too_large"


@pytest.mark.parametrize(
    "field,value",
    [
        ("energy_kcal", "1.0"),
        ("energy_kcal", "01"),
        ("energy_kcal", "NaN"),
        ("energy_kcal", "Infinity"),
        ("energy_kcal", 42),
        ("protein_g", -1),
    ],
)
def test_decimal_wire_errors(tmp_path, package, catalog, field, value):
    package["products"][0]["nutrition_per_100"][field] = value
    with pytest.raises(CatalogValidationError):
        catalog.stage(*artifacts(tmp_path, package))


@pytest.mark.parametrize("mutation", ["key", "nan", "infinity", "utf8"])
def test_strict_json_parser_used(tmp_path, package, catalog, mutation):
    raw = canonical_json(package)
    if mutation == "key":
        raw = raw.replace(b'"release":1', b'"release":1,"release":1')
    elif mutation == "utf8":
        raw = raw.replace(b'"name":"', b'"name":"\xff', 1)
    else:
        raw = raw.replace(
            b'"energy_kcal":"87"',
            b'"energy_kcal":' + (b"NaN" if mutation == "nan" else b"Infinity"),
        )
    with pytest.raises(CatalogValidationError):
        catalog.stage(*artifacts(tmp_path, package, raw=raw))


@pytest.mark.parametrize(
    "mutation",
    [
        "product_duplicate",
        "ration_duplicate",
        "source_duplicate",
        "missing_product",
        "source",
        "counts",
        "schema",
        "reader",
        "unit",
        "density",
        "official",
        "component_position",
        "product_limit",
        "ration_limit",
        "component_limit",
    ],
)
def test_graph_schema_limits_and_official_rejections(tmp_path, package, catalog, mutation):
    if mutation == "product_duplicate":
        package["products"].append(copy.deepcopy(package["products"][0]))
    elif mutation == "ration_duplicate":
        package["rations"].append(copy.deepcopy(package["rations"][0]))
    elif mutation == "source_duplicate":
        package["sources"].append(copy.deepcopy(package["sources"][0]))
    elif mutation == "missing_product":
        package["rations"][0]["components"][0]["product"]["revision"] = 99
    elif mutation == "source":
        package["products"][0]["source_id"] = str(uuid4())
    elif mutation == "counts":
        package["counts"]["products"] += 1
    elif mutation == "schema":
        package["schema_version"] = 2
    elif mutation == "reader":
        package["min_reader_version"] = 2
    elif mutation == "unit":
        package["products"][0]["basis_unit"] = "pcs"
    elif mutation == "density":
        package["rations"][0]["components"][0]["quantity"]["unit"] = "ml"
    elif mutation == "official":
        package["kind"] = "official"
        catalog = OfflineCatalog(catalog.database_path, PACKAGE_ID, "official")
    elif mutation == "component_position":
        package["rations"][0]["components"][0]["position"] = 100
    else:
        key, amount = {
            "product_limit": ("products", 10001),
            "ration_limit": ("rations", 1001),
            "component_limit": ("components", 100001),
        }[mutation]
        package["counts"][key] = amount
    with pytest.raises(CatalogValidationError):
        catalog.stage(*artifacts(tmp_path, package))


def test_trusted_identity_checked_before_package_read(tmp_path, package, catalog):
    package["package_id"] = str(uuid4())
    manifest, compressed = artifacts(tmp_path, package)
    compressed.unlink()
    with pytest.raises(OfflineImportError) as failure:
        catalog.stage(manifest, compressed)
    assert failure.value.code == "identity_mismatch"


def test_unknown_and_foreign_generation_cannot_activate(tmp_path, package, catalog):
    with pytest.raises(OfflineImportError) as failure:
        catalog.activate(str(uuid4()))
    assert failure.value.code == "unknown_generation"
    foreign = OfflineCatalog(catalog.database_path, str(uuid4()), "demo")
    generation = catalog.stage(*artifacts(tmp_path, package))
    with pytest.raises(OfflineImportError) as failure:
        foreign.activate(generation)
    assert failure.value.code == "identity_mismatch"


def test_incomplete_generation_cannot_activate(tmp_path, package, catalog):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    package["release"] = 2
    generation = catalog.stage(*artifacts(tmp_path / "two", package))
    with sqlite3.connect(catalog.database_path) as db:
        db.execute("UPDATE catalog_generations SET complete=0 WHERE generation_id=?", (generation,))
    with pytest.raises(OfflineImportError) as failure:
        catalog.activate(generation)
    assert failure.value.code == "unknown_generation"
    assert catalog.read_active_package()["release"] == 1


def test_duplicate_manifest_keys_and_missing_file_keep_active(tmp_path, package, catalog):
    assert catalog.import_package(*artifacts(tmp_path / "one", package))
    package["release"] = 2
    manifest, compressed = artifacts(tmp_path / "two", package)
    valid_manifest = manifest.read_bytes()
    manifest.write_bytes(valid_manifest.replace(b'"release":2', b'"release":2,"release":2'))
    with pytest.raises(CatalogValidationError):
        catalog.stage(manifest, compressed)
    manifest.write_bytes(valid_manifest)
    compressed.unlink()
    with pytest.raises(FileNotFoundError):
        catalog.stage(manifest, compressed)
    assert catalog.read_active_package()["release"] == 1


def synthetic_official(package):
    result = copy.deepcopy(package)
    result["kind"] = "official"
    for source in result["sources"]:
        source.update(status="verified", basis="per_100_g", missing_data=[], notes=[])
    for product in result["products"]:
        product["status"] = "verified"
    for ration in result["rations"]:
        ration.update(status="verified", complete=True, manufacturer="Synthetic test manufacturer")
        ration["excluded_items"] = []
    return result


def test_versions_immutable_between_demo_and_official(tmp_path, package, catalog):
    official = synthetic_official(package)
    official["package_id"] = str(uuid4())
    official_catalog = OfflineCatalog(catalog.database_path, official["package_id"], "official")
    assert official_catalog.import_package(*artifacts(tmp_path / "official", official))
    demo = copy.deepcopy(official)
    demo.update(kind="demo", package_id=PACKAGE_ID)
    assert catalog.import_package(*artifacts(tmp_path / "demo", demo))
    changed = copy.deepcopy(official)
    changed["release"] = 2
    changed["products"][0]["name"] += " changed"
    with pytest.raises(OfflineImportError) as failure:
        official_catalog.stage(*artifacts(tmp_path / "changed", changed))
    assert failure.value.code == "version_conflict"
    assert catalog.read_active_package() == demo
    assert official_catalog.read_active_package() == official


def test_package_id_cannot_change_channel(tmp_path, package, catalog):
    assert catalog.import_package(*artifacts(tmp_path / "demo", package))
    official = synthetic_official(package)
    separate = OfflineCatalog(catalog.database_path, PACKAGE_ID, "official")
    with pytest.raises(OfflineImportError) as failure:
        separate.stage(*artifacts(tmp_path / "official", official))
    assert failure.value.code == "identity_mismatch"
    assert catalog.read_active_package() == package


def test_cli_works_without_database_url_or_application_imports(tmp_path):
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    script = (
        "import sys; from calorie_app.modules.catalog.offline_import import main; "
        "assert 'calorie_app.core.config' not in sys.modules; "
        "assert 'sqlalchemy' not in sys.modules; raise SystemExit(main())"
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--database",
            str(tmp_path / "cli.sqlite"),
            "--manifest",
            str(EXAMPLES / "catalog-manifest.json"),
            "--package",
            str(EXAMPLES / "base-pl.1.json.gz"),
            "--expected-package-id",
            PACKAGE_ID,
            "--expected-kind",
            "demo",
        ],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "activated": True,
        "package_id": PACKAGE_ID,
        "kind": "demo",
        "release": 1,
    }
