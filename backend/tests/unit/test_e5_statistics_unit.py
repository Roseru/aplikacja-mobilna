import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.schemas import ResultDecimal, StatisticsQuery
from calorie_app.modules.analytics.service import (
    build_statistics,
    rounded_average,
    statistics_window,
)
from calorie_app.modules.profiles.service import resolve_goal_dates

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/test-vectors/statistics-v1.json").read_text(
        encoding="utf-8"
    )
)


def get_path(value, path):
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


@pytest.mark.parametrize("vector", VECTORS["cases"], ids=lambda case: case["name"])
def test_shared_statistics_vectors(vector):
    start, today = statistics_window(
        datetime.fromisoformat(vector["as_of"]), vector["time_zone"], vector["days"]
    )
    days = [date.fromordinal(start.toordinal() + i) for i in range(vector["days"])]
    versions = [
        SimpleNamespace(
            id=UUID(goal["entity_id"]),
            timeline_revision=goal["timeline_revision"],
            effective_from=date.fromisoformat(goal["effective_from"]),
            energy_kcal=goal["energy_kcal"],
            correction_of=UUID(goal["correction_of"]) if goal["correction_of"] else None,
        )
        for goal in vector["goals"]
    ]
    resolved = resolve_goal_dates(versions, days)
    goals = {
        day: {
            "entity_id": str(goal.id),
            "timeline_revision": goal.timeline_revision,
            "effective_from": goal.effective_from.isoformat(),
            "energy_kcal": goal.energy_kcal,
        }
        if goal
        else None
        for day, goal in resolved.items()
    }
    result = build_statistics(
        start,
        today,
        {date.fromisoformat(day): True for day in vector["declarations"]},
        {
            date.fromisoformat(day): [{"items": items} for items in meals]
            for day, meals in vector["meals"].items()
        },
        {date.fromisoformat(day): points for day, points in vector["weights"].items()},
        goals,
    )
    result.update({"from": start.isoformat(), "to": today.isoformat()})
    assert len(result["daily"]) == vector["days"]
    for path, expected in vector["expected"].items():
        assert get_path(result, path) == expected, path


@pytest.mark.parametrize("days", [7, 30, 90, "7", "30", "90"])
def test_valid_days_query(days):
    assert StatisticsQuery(days=days).days == int(days)


@pytest.mark.parametrize("days", [1, 6, 8, 29, 91, "07", "7.0", True, "", None])
def test_invalid_days_query(days):
    with pytest.raises(ValidationError):
        StatisticsQuery(days=days)


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], None),
        ([Decimal("0")], "0"),
        ([Decimal("0.0000000000005")], "0.000000000001"),
        ([Decimal("1"), Decimal("2"), Decimal("2")], "1.666666666667"),
    ],
)
def test_average_half_up(values, expected):
    assert rounded_average(values) == expected


@pytest.mark.parametrize("value", ["-1.5", "0", "0.00000000000001", "100000000000"])
def test_signed_computed_results_allow_precision(value):
    from pydantic import TypeAdapter

    assert TypeAdapter(ResultDecimal).validate_python(value) == value


@pytest.mark.parametrize("value", ["-0", "NaN", "Infinity", "1.0", 1.5])
def test_invalid_computed_results(value):
    from pydantic import TypeAdapter

    with pytest.raises(ValidationError):
        TypeAdapter(ResultDecimal).validate_python(value)


def test_outside_window_entries_cannot_affect_reducer():
    start, today = statistics_window(datetime(2026, 10, 11, tzinfo=UTC), "UTC", 7)
    result = build_statistics(
        start, today, {date(1900, 1, 1): True}, {date(1900, 1, 1): [{"items": []}]}, {}, {}
    )
    assert result["complete_day_count"] == result["days_with_meals"] == 0


def test_corrupt_unreachable_correction_is_safe_error():
    bad = SimpleNamespace(id=UUID(int=1), correction_of=UUID(int=2), timeline_revision=1)
    with pytest.raises(DomainError) as error:
        resolve_goal_dates([bad], [date(2026, 10, 11)])
    assert error.value.code == "service_unavailable"


def test_unknown_macro_has_null_sum_not_zero():
    from calorie_app.modules.catalog.nutrition import FIELDS

    day = date(2026, 10, 10)
    item = {
        "quantity": {"amount": "100", "unit": "g"},
        "basis_unit": "g",
        "density_g_per_ml": None,
        "nutrition_per_100": dict.fromkeys(FIELDS, None),
    }
    item["nutrition_per_100"]["energy_kcal"] = "100"
    result = build_statistics(
        day, date(2026, 10, 11), {day: True}, {day: [{"items": [item]}]}, {}, {}
    )
    assert result["daily"][0]["effective_complete"]
    assert result["daily"][0]["totals"]["protein_g"] == {
        "known_sum": None,
        "known_count": 0,
        "missing_count": 1,
        "complete": False,
    }
    assert result["averages"]["protein_g"] == {"value": None, "day_count": 0}


@pytest.mark.parametrize("value", ["-0.1", "-1"])
def test_unsigned_nutrient_results_reject_negative_values(value):
    from pydantic import TypeAdapter

    from calorie_app.modules.analytics.schemas import NonnegativeResultDecimal

    with pytest.raises(ValidationError):
        TypeAdapter(NonnegativeResultDecimal).validate_python(value)
