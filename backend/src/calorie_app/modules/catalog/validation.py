"""Strict offline wire validation, shared by the server and reference reader."""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from calorie_app.core.wire import common_pattern, validate_json_strings

MAX_COMPRESSED_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_PRODUCTS = 10000
MAX_RATIONS = 1000
MAX_COMPONENTS = 100000
MAX_SOURCES = 10000
DECIMAL_PATTERN = common_pattern("Decimal")
_BASE = "https://calorie.invalid/schemas/"
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def _timestamp_format(value):
    # jsonschema's date-time check is optional without rfc3339-validator.
    # The installed runtime must always enforce the same E0 calendar/UTC form.
    if not isinstance(value, str):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.[0-9]{1,6})?Z", value) is None:
        return False
    datetime.fromisoformat(value)
    return True


@FORMATS.checks("date", raises=ValueError)
def _date_format(value):
    if not isinstance(value, str):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return False
    date.fromisoformat(value)
    return True


@FORMATS.checks("uri", raises=ValueError)
def _uri_format(value):
    # Source URLs are descriptive HTTPS URIs, never fetched by this module.
    # No optional URI parser or network lookup may silently weaken validation.
    if not isinstance(value, str):
        return True
    if re.fullmatch(r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", value) is None:
        return False
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and (parsed.port is None or 0 <= parsed.port <= 65535)
    )


class CatalogValidationError(ValueError):
    """Stable machine-readable rejection with optional diagnostic detail."""

    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


def canonical(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CatalogValidationError("catalog_decimal")
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def canonical_json(value: Any) -> bytes:
    """Pinned JSON encoding; Decimal values never become JSON numbers."""

    def encode(item: Any) -> str:
        if isinstance(item, Decimal):
            return canonical(item)
        raise TypeError(f"Unsupported JSON value: {type(item).__name__}")

    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
                default=encode,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        if isinstance(error, CatalogValidationError):
            raise
        raise CatalogValidationError("catalog_json") from error


def parse_json(raw: bytes) -> dict:
    """Check byte limits before decoding or allocating a JSON object."""
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise CatalogValidationError("catalog_size")

    def pairs(values: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in values:
            if key in result:
                raise CatalogValidationError("catalog_json_duplicate")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise CatalogValidationError("catalog_decimal")

    def fractional_number(_: str) -> None:
        # Every JSON numeric field in E0 is an integer. Decimal fields are text;
        # rejecting fractional/exponent tokens also prevents overflow to float inf.
        raise CatalogValidationError("catalog_decimal")

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=fractional_number,
        )
    except CatalogValidationError:
        raise
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CatalogValidationError("catalog_json") from error
    if not isinstance(value, dict):
        raise CatalogValidationError("catalog_schema")
    return value


@cache
def _validator(definition: str) -> Draft202012Validator:
    resources = files("calorie_app.modules.catalog.resources")
    schemas = {
        name: json.loads(resources.joinpath(name).read_text(encoding="utf-8"))
        for name in ("common.schema.json", "catalog.schema.json")
    }
    registry = Registry().with_resources(
        (_BASE + name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    # The absolute root keeps all external references within the bundled registry.
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": _BASE + "catalog.schema.json#/$defs/" + definition,
        },
        registry=registry,
        format_checker=FORMATS,
    )


def validate_definition(value: dict, definition: str) -> None:
    """Validate a standalone DTO against the same normative bundled schema."""
    try:
        validate_json_strings(value)
    except ValueError as error:
        raise CatalogValidationError("catalog_schema") from error
    error = next(_validator(definition).iter_errors(value), None)
    if error is not None:
        path = "/".join(str(part) for part in error.absolute_path)
        raise CatalogValidationError("catalog_schema", f"{path}: {error.message}")


def _header(value: dict) -> None:
    if not isinstance(value, dict):
        raise CatalogValidationError("catalog_schema")
    if "schema_version" in value and (
        type(value["schema_version"]) is not int or value["schema_version"] != 1
    ):
        raise CatalogValidationError("catalog_schema_version")
    if "min_reader_version" in value and (
        type(value["min_reader_version"]) is not int or value["min_reader_version"] != 1
    ):
        raise CatalogValidationError("catalog_reader_version")


def validate_manifest(value: dict) -> None:
    _header(value)
    validate_definition(value, "Manifest")
    if len(set(value["source_ids"])) != len(value["source_ids"]):
        raise CatalogValidationError("catalog_duplicate")
    if len(value["source_ids"]) != value["counts"]["sources"]:
        raise CatalogValidationError("catalog_counts")
    if value["path"] != f"base-pl.{value['release']}.json.gz":
        raise CatalogValidationError("catalog_manifest")


def validate_package(value: dict) -> None:
    _header(value)
    validate_definition(value, "Package")
    products = {(p["product_id"], p["revision"]): p for p in value["products"]}
    sources = {s["source_id"]: s for s in value["sources"]}
    rations = {(r["ration_id"], r["revision"]) for r in value["rations"]}
    if (
        len(products) != len(value["products"])
        or len(sources) != len(value["sources"])
        or len(rations) != len(value["rations"])
    ):
        raise CatalogValidationError("catalog_duplicate")
    counts = {
        "products": len(value["products"]),
        "rations": len(value["rations"]),
        "sources": len(value["sources"]),
        "components": sum(len(r["components"]) for r in value["rations"]),
    }
    if counts != value["counts"] or counts["components"] > MAX_COMPONENTS:
        raise CatalogValidationError("catalog_counts")
    for product in value["products"]:
        if product["source_id"] not in sources:
            raise CatalogValidationError("catalog_reference")
        density = product["density_g_per_ml"]
        if density is not None and density["source_id"] not in sources:
            raise CatalogValidationError("catalog_reference")
        if product["package_quantity"]["unit"] != product["basis_unit"] and density is None:
            raise CatalogValidationError("catalog_unit")
    for ration in value["rations"]:
        if ration["source_id"] not in sources:
            raise CatalogValidationError("catalog_reference")
        if [c["position"] for c in ration["components"]] != list(
            range(1, len(ration["components"]) + 1)
        ):
            raise CatalogValidationError("catalog_order")
        if ration["complete"] and any(
            e["classification"] != "equipment" for e in ration["excluded_items"]
        ):
            raise CatalogValidationError("catalog_completeness")
        for component in ration["components"]:
            reference = component["product"]
            product = products.get((reference["product_id"], reference["revision"]))
            if product is None:
                raise CatalogValidationError("catalog_reference")
            if (
                component["quantity"]["unit"] != product["basis_unit"]
                and product["density_g_per_ml"] is None
            ):
                raise CatalogValidationError("catalog_unit")
            if ration["complete"] and any(v is None for v in product["nutrition_per_100"].values()):
                raise CatalogValidationError("catalog_completeness")
    if value["kind"] == "official":
        if any(
            s["status"] != "verified"
            or s["missing_data"]
            or s["basis"] == "assumed_listed_quantity"
            for s in sources.values()
        ):
            raise CatalogValidationError("catalog_official")
        if any(
            p["status"] != "verified" or any(v is None for v in p["nutrition_per_100"].values())
            for p in value["products"]
        ):
            raise CatalogValidationError("catalog_official")
        if any(
            r["status"] != "verified" or not r["complete"] or r["manufacturer"] is None
            for r in value["rations"]
        ):
            raise CatalogValidationError("catalog_official")


def wire_decimal(value: Any) -> Decimal:
    """Accept exact database Decimal or canonical wire text, never float/int."""
    if isinstance(value, Decimal):
        text = canonical(value)
    elif isinstance(value, str):
        text = value
    else:
        raise CatalogValidationError("catalog_decimal")
    if re.fullmatch(DECIMAL_PATTERN, text) is None:
        raise CatalogValidationError("catalog_decimal")
    return Decimal(text)
