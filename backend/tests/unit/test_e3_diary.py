import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from calorie_app.modules.diary.validation import (
    DiaryValidationError,
    effective_complete,
    meal_totals,
    validate_payload,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/examples/valid"


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name,definition",
    [
        ("meal", "Meal"),
        ("weight", "Weight"),
        ("weight-dst-first", "Weight"),
        ("weight-dst-second", "Weight"),
        ("weight-dst-spring", "Weight"),
        ("weight-utc-midnight", "Weight"),
        ("product-draft", "ProductDraft"),
        ("diary-day", "DiaryDay"),
    ],
)
def test_normative_examples(name, definition):
    validate_payload(example(name), definition)


@pytest.mark.parametrize(
    "value", [0, 1.5, "NaN", "Infinity", "-1", "0", "1.0", "01", "1e2", "10001"]
)
def test_reject_quantity(value):
    meal = example("meal")
    meal["items"][0]["quantity"]["amount"] = value
    with pytest.raises(DiaryValidationError):
        validate_payload(meal, "Meal")


@pytest.mark.parametrize(
    "mutation",
    [
        {"time_zone": "Invented/Zone"},
        {"time_zone": "+02:00"},
        {"occurred_at": "2026-02-30T00:00:00Z"},
        {"occurred_at": "2026-10-09T06:00:00+00:00"},
        {"local_date": "2026-10-08"},
        {"local_date": "2026-13-01"},
        {"owner_id": str(uuid4())},
    ],
)
def test_reject_time_semantics_and_extras(mutation):
    with pytest.raises(DiaryValidationError):
        validate_payload(example("meal") | mutation, "Meal")


def test_dst_instants_keep_separate_measurements_same_date():
    first, second = example("weight-dst-first"), example("weight-dst-second")
    assert first["occurred_at"] != second["occurred_at"]
    assert first["local_date"] == second["local_date"]
    for value in (first, second):
        validate_payload(value, "Weight")


@pytest.mark.parametrize("count", [0, 101])
def test_aggregate_item_limit(count):
    meal = example("meal")
    item = meal["items"][0]
    meal["items"] = [deepcopy(item) | {"item_id": str(uuid4())} for _ in range(count)]
    with pytest.raises(DiaryValidationError):
        validate_payload(meal, "Meal")


def test_duplicate_item_and_revision_float_are_rejected():
    meal = example("meal")
    meal["items"].append(deepcopy(meal["items"][0]))
    with pytest.raises(DiaryValidationError):
        validate_payload(meal, "Meal")
    meal = example("meal")
    meal["items"][0]["product"] = {"product_id": str(uuid4()), "revision": 1.0}
    with pytest.raises(DiaryValidationError):
        validate_payload(meal, "Meal")


@pytest.mark.parametrize(
    "definition,name,field",
    [("Meal", "meal", "quantity"), ("ProductDraft", "product-draft", "package_quantity")],
)
def test_density_and_source_required_for_conversion(definition, name, field):
    payload = example(name)
    item = payload["items"][0] if definition == "Meal" else payload
    item[field] = {"amount": "10", "unit": "ml"}
    with pytest.raises(DiaryValidationError):
        validate_payload(payload, definition)
    item["density_g_per_ml"] = "1.25"
    with pytest.raises(DiaryValidationError):
        validate_payload(payload, definition)
    item["density_source"] = "label"
    validate_payload(payload, definition)


@pytest.mark.parametrize(
    "declared,energy,expected",
    [
        (False, "1", False),
        (True, None, False),
        (True, "0", False),
        (True, "0.000001", True),
        (True, "100", True),
    ],
)
def test_effective_complete_uses_energy_not_macros(declared, energy, expected):
    meal = example("meal")
    meal["items"][0]["nutrition_per_100"] = dict.fromkeys(
        ("energy_kcal", "protein_g", "fat_g", "carbs_g")
    ) | {"energy_kcal": energy}
    assert effective_complete(declared, [meal]) is expected
    totals = meal_totals(meal["items"])
    assert totals["protein_g"]["missing_count"] == 1
    assert totals["protein_g"]["complete"] is False


def test_empty_day_not_complete_and_mixed_null_energy_not_zero():
    assert effective_complete(True, []) is False
    known, unknown = example("meal"), example("meal")
    unknown["items"][0]["nutrition_per_100"]["energy_kcal"] = None
    assert effective_complete(True, [known, unknown]) is False
    assert meal_totals(unknown["items"])["energy_kcal"]["known_sum"] == "0"
    assert meal_totals(unknown["items"])["energy_kcal"]["missing_count"] == 1


def test_unrounded_intermediate_density_arithmetic():
    meal = example("meal")
    item = meal["items"][0]
    item["quantity"] = {"amount": "1", "unit": "g"}
    item["basis_unit"] = "ml"
    item["density_g_per_ml"] = "3"
    item["density_source"] = "label"
    item["nutrition_per_100"]["energy_kcal"] = "1"
    validate_payload(meal, "Meal")
    assert meal_totals(meal["items"])["energy_kcal"]["known_sum"] == "0.00333333333333"


def test_weight_technical_limit_and_package_not_consumption():
    validate_payload(example("weight") | {"weight_kg": "1000"}, "Weight")
    with pytest.raises(DiaryValidationError):
        validate_payload(example("weight") | {"weight_kg": "1000.000001"}, "Weight")
    draft = example("product-draft")
    draft["package_quantity"] = {"amount": "999999.999999", "unit": "g"}
    validate_payload(draft, "ProductDraft")
