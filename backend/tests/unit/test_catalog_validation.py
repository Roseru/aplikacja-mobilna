import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from calorie_app.modules.catalog.schemas import ManifestDTO, ProductDTO, RationDTO, RationPage
from calorie_app.modules.catalog.validation import (
    CatalogValidationError,
    canonical,
    canonical_json,
    parse_json,
    validate_manifest,
    validate_package,
)

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


@pytest.fixture
def package():
    return json.loads((CONTRACTS / "examples/valid/catalog-demo.json").read_text("utf-8"))


@pytest.fixture
def manifest():
    return json.loads((CONTRACTS / "examples/valid/catalog-manifest.json").read_text("utf-8"))


def rejected(code, function, value):
    with pytest.raises(CatalogValidationError) as error:
        function(value)
    assert error.value.code == code


def test_normalized_demo_and_dto_preserve_wire(package):
    validate_package(package)
    product = package["products"][0]
    product_dto = ProductDTO.model_validate(product)
    assert isinstance(product_dto.package_quantity.amount, Decimal)
    assert product_dto.model_dump(mode="json") == product
    ration = package["rations"][0]
    assert RationDTO.model_validate(ration).model_dump(mode="json") == ration
    page = RationPage(items=[ration], next_page_token=None)
    assert set(page.model_dump(mode="json")) == {"items", "next_page_token"}


def test_manifest_matches_schema_and_release(manifest):
    validate_manifest(manifest)
    assert ManifestDTO.model_validate(manifest).model_dump(mode="json") == manifest
    manifest["path"] = "base-pl.99.json.gz"
    rejected("catalog_manifest", validate_manifest, manifest)


@pytest.mark.parametrize("field", ["schema_version", "min_reader_version"])
@pytest.mark.parametrize("value", [2, True, "1"])
def test_unsupported_versions(package, field, value):
    package[field] = value
    rejected(
        "catalog_schema_version" if field == "schema_version" else "catalog_reader_version",
        validate_package,
        package,
    )


@pytest.mark.parametrize(
    "raw,code",
    [
        (b'{"x":1,"x":2}', "catalog_json_duplicate"),
        (b'{"nested":{"x":1,"x":2}}', "catalog_json_duplicate"),
        (b'{"x":NaN}', "catalog_decimal"),
        (b'{"x":Infinity}', "catalog_decimal"),
        (b'{"x":-Infinity}', "catalog_decimal"),
        (b'{"x":1e999999}', "catalog_decimal"),
        (b'{"x":1.0}', "catalog_decimal"),
        (b'{"x":"\xff"}', "catalog_json"),
        (b'{"x":', "catalog_json"),
        (b"[]", "catalog_schema"),
    ],
)
def test_strict_json(raw, code):
    rejected(code, parse_json, raw)


def test_json_limit_checked_before_parsing(monkeypatch):
    monkeypatch.setattr("calorie_app.modules.catalog.validation.MAX_UNCOMPRESSED_BYTES", 8)
    rejected("catalog_size", parse_json, b'{"name":"value"}')


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1.0", "1e2", "-1", "0.0000001", 1, 1.2])
def test_decimal_wire_rejections(package, value):
    package["products"][0]["nutrition_per_100"]["energy_kcal"] = value
    rejected("catalog_schema", validate_package, package)
    with pytest.raises(ValidationError):
        ProductDTO.model_validate(package["products"][0])


@pytest.mark.parametrize("collection", ["products", "rations", "sources"])
def test_duplicate_versions(package, collection):
    package[collection].append(deepcopy(package[collection][0]))
    rejected("catalog_duplicate", validate_package, package)


def test_revision_pins_are_exact(package):
    package["rations"][0]["components"][0]["product"]["revision"] += 1
    rejected("catalog_reference", validate_package, package)


def test_same_identity_can_have_another_revision(package):
    product = deepcopy(package["products"][0])
    product["revision"] += 1
    package["products"].append(product)
    package["counts"]["products"] += 1
    validate_package(package)


def test_counts_order_and_missing_source(package):
    original = deepcopy(package)
    package["counts"]["components"] += 1
    rejected("catalog_counts", validate_package, package)
    package = deepcopy(original)
    package["rations"][0]["components"][0]["position"] = 2
    rejected("catalog_order", validate_package, package)
    package = deepcopy(original)
    package["products"][0]["source_id"] = "00000000-0000-0000-0000-000000000000"
    rejected("catalog_reference", validate_package, package)


def test_conversion_requires_density_with_existing_source(package):
    product = package["products"][0]
    product["package_quantity"]["unit"] = "ml"
    rejected("catalog_unit", validate_package, package)
    product["density_g_per_ml"] = {
        "amount": "1.2",
        "source_id": "00000000-0000-0000-0000-000000000000",
    }
    rejected("catalog_reference", validate_package, package)
    product["density_g_per_ml"]["source_id"] = package["sources"][0]["source_id"]
    validate_package(package)


def test_complete_ration_cannot_have_unknown_food(package):
    package["rations"][0]["complete"] = True
    rejected("catalog_completeness", validate_package, package)


def test_verified_complete_synthetic_official(package):
    package["kind"] = "official"
    rejected("catalog_official", validate_package, package)
    for source in package["sources"]:
        source.update(status="verified", basis="per_100_g", missing_data=[])
    for product in package["products"]:
        product["status"] = "verified"
    for ration in package["rations"]:
        ration.update(status="verified", complete=True, manufacturer="Synthetic test fixture")
        ration["excluded_items"] = [
            item for item in ration["excluded_items"] if item["classification"] == "equipment"
        ]
    validate_package(package)
    package["sources"][0]["missing_data"] = ["missing label"]
    rejected("catalog_official", validate_package, package)


@pytest.mark.parametrize("timestamp", ["2026-10-09T12:00:00+00:00", "2026-02-30T12:00:00Z"])
def test_timestamp_format_checker(package, timestamp):
    package["published_at"] = timestamp
    rejected("catalog_schema", validate_package, package)


@pytest.mark.parametrize("invalid", ["2026-02-30", "20261009", "2026-13-01"])
def test_source_calendar_without_optional_format_dependencies(package, invalid):
    package["sources"][0]["checked_on"] = invalid
    rejected("catalog_schema", validate_package, package)


@pytest.mark.parametrize(
    "invalid",
    [
        "https://",
        "https://host with spaces",
        "https://example.com/%GG",
        "https://example.com:invalid/path",
        "https://example.com:65536/path",
        "https://example.com/\npath",
    ],
)
def test_source_uri_without_optional_format_dependencies(package, invalid):
    package["sources"][0]["url"] = invalid
    rejected("catalog_schema", validate_package, package)


def test_https_source_uri_is_metadata_only(package):
    package["sources"][0]["url"] = "https://example.invalid/etykieta%20testowa?q=1#part"
    validate_package(package)


def test_required_nullable_fields_are_not_defaults(package):
    product = package["products"][0]
    assert product["brand"] is None
    del product["brand"]
    with pytest.raises(ValidationError):
        ProductDTO.model_validate(product)


def test_database_scale_serializes_canonically(package):
    product = package["products"][0]
    product["package_quantity"]["amount"] = Decimal("300.000000")
    assert ProductDTO.model_validate(product).model_dump(mode="json")["package_quantity"] == {
        "amount": "300",
        "unit": "g",
    }
    assert canonical(Decimal("-0.000000")) == "0"
    assert canonical_json({"b": Decimal("1.000000"), "a": "ą"}) == '{"a":"ą","b":"1"}\n'.encode()


def test_nonfinite_canonical_output():
    rejected("catalog_decimal", canonical, Decimal("NaN"))
    rejected("catalog_json", canonical_json, {"bad": float("inf")})
