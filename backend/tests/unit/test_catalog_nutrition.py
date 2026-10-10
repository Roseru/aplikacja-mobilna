import json
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from calorie_app.modules.catalog.nutrition import calculate, ration_items
from calorie_app.modules.catalog.validation import CatalogValidationError

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
VECTORS = json.loads((CONTRACTS / "test-vectors/nutrition-v1.json").read_text("utf-8"))


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_e0_nutrition_vectors(case):
    if "expected_error" in case:
        with pytest.raises(CatalogValidationError) as error:
            calculate(case["items"])
        assert error.value.code == case["expected_error"]
    else:
        assert calculate(case["items"]) == case["expected"]


def test_whole_demo_preserves_normalization_precision():
    package = json.loads((CONTRACTS / "examples/valid/catalog-demo.json").read_text("utf-8"))
    ration = package["rations"][0]
    items = ration_items(
        ration,
        package["products"],
        {component["position"]: "1" for component in ration["components"]},
    )
    assert calculate(items)["energy_kcal"]["known_sum"] == "3466.00000145"


def test_fraction_selection_excludes_other_components():
    package = json.loads((CONTRACTS / "examples/valid/catalog-demo.json").read_text("utf-8"))
    ration = package["rations"][0]
    items = ration_items(ration, package["products"], {1: "0.5", 3: "0.5"})
    assert len(items) == 2
    assert calculate(items)["energy_kcal"]["known_sum"] == "213"
    assert calculate(ration_items(ration, package["products"], {}))["energy_kcal"] == {
        "known_sum": "0",
        "display": "0",
        "missing_count": 0,
        "complete": True,
    }
    for selection in ({1: "1.000001"}, {1: "0"}, {999: "0.5"}):
        with pytest.raises(CatalogValidationError):
            ration_items(ration, package["products"], selection)


def test_fraction_product_is_not_rounded_to_six_places():
    product = {
        "product_id": "id",
        "revision": 1,
        "basis_unit": "g",
        "nutrition_per_100": dict.fromkeys(
            ("energy_kcal", "protein_g", "fat_g", "carbs_g"), "999999.999999"
        ),
        "density_g_per_ml": None,
    }
    ration = {
        "components": [
            {
                "position": 1,
                "product": {"product_id": "id", "revision": 1},
                "quantity": {"amount": "0.000001", "unit": "g"},
            }
        ]
    }
    items = ration_items(ration, [product], {1: "0.000001"})
    assert items[0]["amount"] == Decimal("0.000000000001")
    assert calculate(items)["energy_kcal"]["known_sum"] == "0.00000000999999999999"


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity", "-Infinity", 1.2, "1.0"])
@pytest.mark.parametrize(
    "field,code", [("amount", "quantity_range"), ("density_g_per_ml", "density_range")]
)
def test_bad_decimal_never_reaches_arithmetic(raw, field, code):
    item = deepcopy(VECTORS["cases"][13]["items"][0])
    item[field] = raw
    with pytest.raises(CatalogValidationError) as error:
        calculate([item])
    assert error.value.code == code


def test_local_decimal_context_is_not_changed():
    with localcontext() as context:
        context.prec = 7
        result = calculate(VECTORS["cases"][-1]["items"])
        assert result["energy_kcal"]["known_sum"] == "347.0000004"
        assert context.prec == 7
