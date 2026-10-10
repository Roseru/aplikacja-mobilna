"""Versioned local-source adapter. Originals never become wire in place."""

import copy
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from calorie_app.modules.catalog.validation import FORMATS
from calorie_app.modules.diary.validation import validate_payload
from calorie_app.modules.profiles.schemas import GoalPayload, ProfilePayload

SCHEMAS = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
BASE = "https://calorie.invalid/schemas/"
MAX_PUSH_BYTES = 1048576
MAX_PUSH_OPERATIONS = 100
DEFINITIONS = {
    "profile": "Profile",
    "goal": "Goal",
    "meal": "Meal",
    "weight": "Weight",
    "diary_day": "DiaryDay",
    "product_draft": "ProductDraft",
}


class AdaptationRequired(ValueError):
    pass


def dumps(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def encode_json(value):
    """The actual HTTP representation, also used to measure the whole envelope."""
    return dumps(value).encode("utf-8", errors="strict")


def loads(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite_json")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def digest(value):
    return hashlib.sha256(encode_json(value)).hexdigest()


@cache
def validator(definition):
    registry = Registry().with_resources(
        (BASE + path.name, Resource.from_contents(loads(path.read_text(encoding="utf-8"))))
        for path in SCHEMAS.glob("*.schema.json")
    )
    return Draft202012Validator(
        {"$ref": BASE + "sync.schema.json#/$defs/" + definition},
        registry=registry,
        format_checker=FORMATS,
    )


def validate(value, definition):
    validator(definition).validate(value)


def exact_decimal(value):
    """Lossless only: legacy floating values use their stored decimal projection."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise AdaptationRequired("decimal_review")
    if isinstance(value, float) and not math.isfinite(value):
        raise AdaptationRequired("decimal_review")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise AdaptationRequired("decimal_review") from None
    if not number.is_finite() or number < 0 or number > Decimal("999999.999999"):
        raise AdaptationRequired("decimal_review")
    # Quantization would lose data (including positive quantities to zero).
    text = (
        format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else str(number)
    )
    if number == 0:
        return "0"
    if "." in text and len(text.split(".")[1]) > 6:
        raise AdaptationRequired("precision_review")
    return text


def decimals(payload, entity_type):
    result = copy.deepcopy(payload)
    fields = {
        "profile": ["height_cm"],
        "goal": ["energy_kcal", "protein_g", "fat_g", "carbs_g"],
        "weight": ["weight_kg"],
        "product_draft": ["density_g_per_ml"],
    }.get(entity_type, [])
    for key in fields:
        if key in result and result[key] is not None:
            result[key] = exact_decimal(result[key])
    rows = (
        result.get("items", [])
        if entity_type == "meal"
        else ([result] if entity_type == "product_draft" else [])
    )
    for row in rows:
        for key in ("quantity", "package_quantity"):
            if row.get(key) is not None:
                row[key]["amount"] = exact_decimal(row[key]["amount"])
        if row.get("density_g_per_ml") is not None:
            row["density_g_per_ml"] = exact_decimal(row["density_g_per_ml"])
        for key in ("energy_kcal", "protein_g", "fat_g", "carbs_g"):
            if row.get("nutrition_per_100", {}).get(key) is not None:
                row["nutrition_per_100"][key] = exact_decimal(row["nutrition_per_100"][key])
    return result


def adapt_source(entity_type, source, *, metadata=None):
    """Android 0.7.1 partial records require explicit missing metadata, never guesses."""
    result = copy.deepcopy(source)
    if "id" in result:
        result.pop("id")
        for key in ("local_revision", "deleted", "diet_aim", "local_timeline_base"):
            result.pop(key, None)
        if "zone_id" in result:
            result["time_zone"] = result.pop("zone_id")
        if entity_type == "profile":
            result["pseudonym"] = result.pop("nickname")
            result["activity_class"] = {
                "STATIONARY": "stationary",
                "LINE": "line",
                "COMMANDO": "commando",
            }.get(result["activity_class"], result["activity_class"])
        elif entity_type == "weight":
            result["weight_kg"] = result.pop("kg")
        elif entity_type == "goal":
            result["effective_from"] = result.pop("valid_from")
            for old, new in (
                ("kcal", "energy_kcal"),
                ("protein", "protein_g"),
                ("fat", "fat_g"),
                ("carbs", "carbs_g"),
            ):
                result[new] = result.pop(old)
        elif entity_type in ("meal", "product_draft"):
            # Exact snapshots/sources need explicit reviewed extraction; source is retained.
            raise AdaptationRequired("snapshot_metadata_review")
    result.update(metadata or {})
    result = decimals(result, entity_type)
    if entity_type == "goal" and not {"decided_at", "time_zone"}.issubset(result):
        raise AdaptationRequired("legacy_goal_metadata_review")
    if entity_type == "profile":
        ProfilePayload.model_validate(result)
    elif entity_type == "goal":
        GoalPayload.model_validate(result)
    else:
        validate_payload(result, DEFINITIONS[entity_type])
    return result
