"""Untrusted food proposals: bounded JSON and the unchanged E6 wire primitives."""

import json
import math
from typing import Annotated, Any, Literal, Self

from pydantic import Field, ValidationError, model_validator

from calorie_app.core.wire import validate_json_strings
from calorie_app.modules.catalog.community.schemas import IdentityDTO, Text
from calorie_app.modules.catalog.schemas import CatalogDTO, NutritionDTO, QuantityDTO, Unit

MAX_RESULT_BYTES = 512 * 1024
MAX_PROVIDER_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 20


class ProviderResultError(ValueError):
    """Only the stable code is exposed; never retain a rejected provider payload."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ProviderFoodItem(CatalogDTO):
    name: Text
    quantity: QuantityDTO
    basis_unit: Unit
    nutrition_per_100: NutritionDTO
    identity: IdentityDTO
    density: None = None
    uncertainty: Literal["low", "medium", "high"]
    notes: Annotated[list[Text], Field(max_length=5)]

    @model_validator(mode="after")
    def same_unit(self) -> Self:
        if self.quantity.unit != self.basis_unit:
            raise ValueError("provider cannot document density for cross-unit conversion")
        return self


class ProviderFoodResult(CatalogDTO):
    items: Annotated[list[ProviderFoodItem], Field(min_length=1, max_length=30)]
    notes: Annotated[list[Text], Field(max_length=10)]


class _NoFoodResult(CatalogDTO):
    items: Annotated[list[ProviderFoodItem], Field(max_length=0)]
    notes: Annotated[list[Text], Field(max_length=10)]


def parse_bounded_json(raw: bytes, *, max_bytes: int = MAX_PROVIDER_BYTES) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise ProviderResultError("provider_response_size")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ProviderResultError("provider_json_invalid") from None
    # Bound nesting before json.loads allocates recursive collections. Quoted
    # brackets and escaped quotes are data, including hostile image text.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ProviderResultError("provider_json_depth")
        elif char in "]}":
            depth -= 1

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ProviderResultError("provider_json_duplicate")
            result[key] = value
        return result

    def constant(_):
        raise ProviderResultError("provider_json_invalid")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ProviderResultError("provider_json_invalid")
        return result

    try:
        value = json.loads(
            text, object_pairs_hook=pairs, parse_constant=constant, parse_float=number
        )
        validate_json_strings(value)
    except ProviderResultError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderResultError("provider_json_invalid") from None
    if not isinstance(value, dict):
        raise ProviderResultError("provider_result_invalid")
    return value


def parse_food_result(raw: bytes) -> ProviderFoodResult:
    value = parse_bounded_json(raw, max_bytes=MAX_RESULT_BYTES)
    try:
        if value.get("items") == []:
            _NoFoodResult.model_validate(value)
            raise ProviderResultError("provider_no_food")
        return ProviderFoodResult.model_validate(value)
    except ProviderResultError:
        raise
    except (ValidationError, ValueError):
        raise ProviderResultError("provider_result_invalid") from None
