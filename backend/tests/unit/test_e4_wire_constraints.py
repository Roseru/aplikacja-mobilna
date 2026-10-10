"""Normative and DTO validators agree on canonical numbers, Unicode and time bounds."""

import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import RootModel, ValidationError
from referencing import Registry, Resource

from calorie_app.core.wire import local_day
from calorie_app.modules.catalog.schemas import DecimalValue, PositiveDecimal
from calorie_app.modules.catalog.validation import DECIMAL_PATTERN, FORMATS
from calorie_app.modules.profiles.schemas import COMPUTED_PATTERN, ComputedDecimal, GoalPayload

ROOT = Path(__file__).resolve().parents[3]
COMMON = json.loads((ROOT / "contracts/schemas/common.schema.json").read_text(encoding="utf-8"))
BASE = "https://calorie.invalid/schemas/common.schema.json"


def normative(definition, value):
    registry = Registry().with_resource(BASE, Resource.from_contents(COMMON))
    return Draft202012Validator(
        {"$ref": BASE + "#/$defs/" + definition}, registry=registry, format_checker=FORMATS
    ).is_valid(value)


@pytest.mark.parametrize(
    "scalar,definition",
    [
        (DecimalValue, "Decimal"),
        (PositiveDecimal, "PositiveDecimal"),
        (ComputedDecimal, "PositiveComputedDecimal"),
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        "0",
        "0.000001",
        "1",
        "1.25",
        "999999.999999",
        "0\n",
        "1\n",
        "1\r\n",
        " 1",
        "1 ",
        "1\t",
        "+1",
        "-0",
        "1.0",
        "01",
        "1e1",
        "NaN",
        "Infinity",
        "١",
        "1\x00",
        "1\ud800",
    ],
)
def test_normative_decimal_and_pydantic_dto_have_identical_acceptance(scalar, definition, value):
    expected = normative(definition, value)
    dto = RootModel[scalar]
    try:
        dto.model_validate(value)
        actual = True
    except (ValidationError, ValueError):
        actual = False
    assert actual == expected
    if any(char.isspace() for char in value) or "\x00" in value or "\ud800" in value:
        assert not actual


def test_decimal_patterns_come_from_the_normative_bundled_schema():
    assert DECIMAL_PATTERN == COMMON["$defs"]["Decimal"]["pattern"]
    assert COMPUTED_PATTERN == COMMON["$defs"]["ComputedDecimal"]["pattern"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Zażółć 😀", True),
        ("\U00010000", True),
        ("\ud800", False),
        ("\udfff", False),
        ("\x00", False),
        ("valid\ntext", True),
        (json.loads('"\\ud83d\\ude00"'), True),
    ],
)
def test_normative_unicode_scalar_text(value, expected):
    assert normative("UnicodeText", value) == expected


@pytest.mark.parametrize(
    "instant,zone",
    [("0001-01-01T00:00:00Z", "Etc/GMT+12"), ("9999-12-31T23:00:00Z", "Pacific/Kiritimati")],
)
def test_civil_time_overflow_is_a_controlled_validation_error(instant, zone):
    with pytest.raises(ValueError, match="local_time_out_of_range"):
        local_day(instant, zone)
    goal = json.loads((ROOT / "contracts/examples/valid/goal.json").read_text(encoding="utf-8"))
    goal.update(decided_at=instant, effective_from=instant[:10], time_zone=zone)
    with pytest.raises(ValidationError):
        GoalPayload.model_validate(goal)


@pytest.mark.parametrize(
    "instant,expected",
    [("0001-01-01T00:00:00Z", date(1, 1, 1)), ("9999-12-31T23:00:00Z", date(9999, 12, 31))],
)
def test_representable_boundary_years_are_supported_without_clamping(instant, expected):
    assert local_day(instant, "UTC") == expected
