"""Validate normative E0 payloads from wheel resources, including time semantics."""

import json
from datetime import datetime
from decimal import Decimal
from functools import cache
from importlib.resources import files
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from calorie_app.modules.catalog.nutrition import calculate
from calorie_app.modules.catalog.validation import FORMATS, CatalogValidationError

BASE = "https://calorie.invalid/schemas/"


class DiaryValidationError(ValueError):
    """Payload rejection without retaining private values in error diagnostics."""


@cache
def _validator(definition: str) -> Draft202012Validator:
    resources = files("calorie_app.modules.catalog.resources")
    registry = Registry().with_resources(
        (BASE + name, Resource.from_contents(json.loads(resources.joinpath(name).read_text())))
        for name in ("common.schema.json", "domain.schema.json")
    )
    return Draft202012Validator(
        {"$ref": BASE + "domain.schema.json#/$defs/" + definition},
        registry=registry,
        format_checker=FORMATS,
    )


def validate_payload(payload: dict, definition: str) -> None:
    def exact_types(value):
        if isinstance(value, (float, Decimal)):
            raise DiaryValidationError("invalid_wire_type")
        if isinstance(value, dict):
            for part in value.values():
                exact_types(part)
        elif isinstance(value, list):
            for part in value:
                exact_types(part)

    exact_types(payload)
    if next(_validator(definition).iter_errors(payload), None) is not None:
        raise DiaryValidationError("invalid_payload")
    if "time_zone" in payload:
        try:
            zone = ZoneInfo(payload["time_zone"])
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise DiaryValidationError("invalid_time_zone") from error
        if "occurred_at" in payload:
            local_date = datetime.fromisoformat(payload["occurred_at"]).astimezone(zone).date()
            if local_date.isoformat() != payload["local_date"]:
                raise DiaryValidationError("local_date_mismatch")
    items = payload["items"] if definition == "Meal" else []
    if definition == "Weight" and Decimal(payload["weight_kg"]) > 1000:
        raise DiaryValidationError("weight_range")
    if len({item["item_id"] for item in items}) != len(items):
        raise DiaryValidationError("duplicate_meal_item")
    for item in items or ([payload] if definition == "ProductDraft" else []):
        density, source = item["density_g_per_ml"], item["density_source"]
        if (density is None) != (source is None):
            raise DiaryValidationError("density_source_required")
        quantity = item.get("quantity", item.get("package_quantity"))
        if quantity is not None:
            if definition == "Meal" and Decimal(quantity["amount"]) > 10000:
                raise DiaryValidationError("quantity_range")
            if quantity["unit"] != item["basis_unit"] and density is None:
                raise DiaryValidationError("density_required")


def meal_totals(items: list[dict]) -> dict:
    try:
        return calculate(
            {**item, "amount": item["quantity"]["amount"], "unit": item["quantity"]["unit"]}
            for item in items
        )
    except CatalogValidationError as error:
        raise DiaryValidationError(error.code) from error


def effective_complete(declared: bool, meals: list[dict]) -> bool:
    """E0 declaration AND live meal AND known energy AND positive exact kcal."""
    if not declared or not meals:
        return False
    totals = meal_totals([item for meal in meals for item in meal["items"]])
    energy = totals["energy_kcal"]
    return energy["complete"] and Decimal(energy["known_sum"]) > 0
