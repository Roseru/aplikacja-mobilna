"""E0 nutrition_v1 arithmetic: exact totals, HALF_UP only at defined boundaries."""

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from calorie_app.modules.catalog.validation import CatalogValidationError, canonical, wire_decimal

FIELDS = ("energy_kcal", "protein_g", "fat_g", "carbs_g")


def _number(
    value: Any,
    code: str,
    *,
    positive: bool = False,
    computed: bool = False,
    maximum: Decimal = Decimal("999999.999999"),
) -> Decimal:
    try:
        result = value if computed and isinstance(value, Decimal) else wire_decimal(value)
    except (ValueError, InvalidOperation) as error:
        raise CatalogValidationError(code) from error
    if not result.is_finite() or result > maximum or (result <= 0 if positive else result < 0):
        raise CatalogValidationError(code)
    return result


def calculate(items: Iterable[Mapping[str, Any]]) -> dict:
    """Calculate E0 vector items; density is exact text or a catalog density object."""
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_UP
        sums = {key: Decimal(0) for key in FIELDS}
        missing = dict.fromkeys(FIELDS, 0)
        for item in items:
            amount = _number(
                item["amount"],
                "quantity_range",
                positive=True,
                maximum=Decimal(10000),
                computed=True,
            )
            if item["unit"] not in ("g", "ml") or item["basis_unit"] not in ("g", "ml"):
                raise CatalogValidationError("quantity_unit")
            if item["unit"] != item["basis_unit"]:
                density = item.get("density_g_per_ml")
                if density is None:
                    raise CatalogValidationError("density_required")
                if isinstance(density, Mapping):
                    if not density.get("source_id"):
                        raise CatalogValidationError("density_required")
                    density = density.get("amount")
                density = _number(density, "density_range", positive=True)
                amount = (
                    amount * density
                    if item["unit"] == "ml"
                    else (amount / density).quantize(Decimal("0.000000000001"))
                )
            for key in FIELDS:
                raw = item["nutrition_per_100"][key]
                if raw is None:
                    missing[key] += 1
                else:
                    sums[key] += _number(raw, "nutrition_range") * amount / Decimal(100)
        return {
            key: {
                "known_sum": canonical(sums[key]),
                "missing_count": missing[key],
                "complete": missing[key] == 0,
                "display": format(
                    sums[key].quantize(Decimal("1") if key == "energy_kcal" else Decimal("0.1")),
                    "f",
                ),
            }
            for key in FIELDS
        }


def ration_items(
    ration: Mapping[str, Any],
    products: Iterable[Mapping[str, Any]],
    selections: Mapping[int, str | Decimal],
) -> list[dict]:
    """Select explicit component fractions in (0,1], including optional items only on selection.

    Fractions multiply component quantities exactly. They never select an unrequested
    component or silently clamp consumption above the component's package quantity.
    """
    versions = {(p["product_id"], p["revision"]): p for p in products}
    components = {c["position"]: c for c in ration["components"]}
    if any(type(position) is not int or position not in components for position in selections):
        raise CatalogValidationError("catalog_reference")
    result = []
    with localcontext() as context:
        context.prec = 50
        for position in sorted(selections):
            fraction = _number(
                selections[position], "ration_fraction", positive=True, maximum=Decimal(1)
            )
            component = components[position]
            reference = component["product"]
            product = versions.get((reference["product_id"], reference["revision"]))
            if product is None:
                raise CatalogValidationError("catalog_reference")
            amount = wire_decimal(component["quantity"]["amount"]) * fraction
            # Computed portions may have 12 places; do not round them back to input scale.
            result.append(
                {
                    "amount": amount,
                    "unit": component["quantity"]["unit"],
                    "basis_unit": product["basis_unit"],
                    "nutrition_per_100": product["nutrition_per_100"],
                    "density_g_per_ml": product["density_g_per_ml"],
                }
            )
    return result
