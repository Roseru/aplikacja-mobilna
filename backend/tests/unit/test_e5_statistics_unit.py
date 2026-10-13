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


@pytest.mark.parametrize(
    "historical_zone,as_of,closed",
    [
        ("America/Los_Angeles", datetime(2026, 10, 11, 1, tzinfo=UTC), False),
        ("Europe/Warsaw", datetime(2026, 10, 10, 23, tzinfo=UTC), True),
    ],
)
def test_preserved_diary_zone_closure_independent_from_profile_window(
    historical_zone, as_of, closed
):
    day = date(2026, 10, 10)
    item = {
        "quantity": {"amount": "100", "unit": "g"},
        "basis_unit": "g",
        "density_g_per_ml": None,
        "nutrition_per_100": {
            "energy_kcal": "100",
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
        },
    }
    result = build_statistics(
        day,
        date(2026, 10, 11),
        {day: True},
        {day: [{"items": [item]}]},
        {},
        {day: {"energy_kcal": "100"}},
        as_of=as_of,
        day_time_zones={day: historical_zone},
    )
    first = result["daily"][0]
    assert first["closed"] is closed
    assert first["in_goal"] is (True if closed else None)
    assert first["preliminary_in_goal"] is (None if closed else True)
    assert result["complete_day_count"] == int(closed)
    assert result["averages"]["energy_kcal"]["day_count"] == int(closed)


def test_statistics_max_date_window_does_not_increment_past_supported_contract():
    result = build_statistics(date.max, date.max, {}, {}, {}, {})
    assert len(result["daily"]) == 1
    assert not result["daily"][0]["closed"]


def test_runtime_shared_facts_are_authoritative_and_python_is_only_oracle(monkeypatch):
    import calorie_app.modules.analytics.service as service

    day = date(2026, 10, 10)
    as_of = datetime(2026, 10, 11, tzinfo=UTC)
    item = {
        "quantity": {"amount": "100", "unit": "g"},
        "basis_unit": "g",
        "density_g_per_ml": None,
        "nutrition_per_100": {
            "energy_kcal": "100",
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
        },
    }

    def forbidden(*args):
        raise AssertionError("second runtime eligibility formula")

    monkeypatch.setattr(service, "evaluate_day", forbidden)
    result = build_statistics(
        day,
        day,
        {day: True},
        {day: [{"items": [item]}]},
        {},
        {day: {"energy_kcal": "100"}},
        as_of=as_of,
        day_facts={
            day: {
                "matures_at": datetime(2026, 10, 10, 22, tzinfo=UTC),
                "effective_complete": False,
                "in_goal": None,
            }
        },
    )
    assert not result["daily"][0]["effective_complete"]
    assert result["daily"][0]["closed"]
    assert result["complete_day_count"] == 0
    assert result["averages"]["energy_kcal"]["value"] is None


@pytest.mark.parametrize(
    "matures_at,closed",
    [
        (None, False),
        (datetime(2026, 10, 11, 1, tzinfo=UTC), False),
        (datetime(2026, 10, 11, tzinfo=UTC), True),
    ],
)
def test_runtime_shared_facts_closure_uses_same_source_boundary(matures_at, closed):
    day = date(2026, 10, 10)
    result = build_statistics(
        day,
        day,
        {},
        {},
        {},
        {},
        as_of=datetime(2026, 10, 11, tzinfo=UTC),
        day_time_zones={day: "UTC"},
        day_facts={day: {"matures_at": matures_at, "effective_complete": False, "in_goal": None}},
    )
    assert result["daily"][0]["closed"] is closed


def test_runtime_missing_fact_is_error_not_silent_partial_snapshot():
    day = date(2026, 10, 10)
    with pytest.raises(DomainError) as error:
        build_statistics(
            day, day, {}, {}, {}, {}, as_of=datetime(2026, 10, 11, tzinfo=UTC), day_facts={}
        )
    assert error.value.status == 503


def test_missing_diary_calendar_rows_keep_past_closed_without_inventing_data(monkeypatch):
    import calorie_app.modules.analytics.service as service

    today = date(2026, 10, 11)
    days = [date.fromordinal(today.toordinal() - offset) for offset in range(6, -1, -1)]

    def forbidden(*args):
        raise AssertionError("calendar metadata must not recompute SQL eligibility")

    monkeypatch.setattr(service, "evaluate_day", forbidden)
    result = build_statistics(
        days[0],
        today,
        {},
        {},
        {},
        {},
        as_of=datetime(2026, 10, 11, 10, tzinfo=UTC),
        day_time_zones={},
        day_facts={
            day: {"matures_at": None, "effective_complete": False, "in_goal": None} for day in days
        },
    )
    assert [row["closed"] for row in result["daily"]] == [True] * 6 + [False]
    assert result["complete_day_count"] == result["in_goal_day_count"] == 0
    for row in result["daily"]:
        assert row["status"] == "no_data" and not row["effective_complete"]
        assert row["in_goal"] is None and row["preliminary_in_goal"] is None
        assert all(field["known_sum"] is None for field in row["totals"].values())
    assert all(
        average == {"value": None, "day_count": 0} for average in result["averages"].values()
    )


def test_known_diary_without_representable_maturity_does_not_use_calendar_fallback():
    day = date(2026, 10, 10)
    result = build_statistics(
        day,
        date(2026, 10, 11),
        {day: False},
        {},
        {},
        {},
        as_of=datetime(2026, 10, 11, 10, tzinfo=UTC),
        day_time_zones={day: "UTC"},
        day_facts={
            date(2026, 10, 10): {"matures_at": None, "effective_complete": False, "in_goal": None},
            date(2026, 10, 11): {"matures_at": None, "effective_complete": False, "in_goal": None},
        },
    )
    assert not result["daily"][0]["closed"]
