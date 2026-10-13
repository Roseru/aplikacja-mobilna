"""Independent numeric and calendar oracles for energy_adjustment_v1."""

from datetime import datetime
from decimal import Decimal
from fractions import Fraction

import pytest

from calorie_app.modules.energy.rules import closed_dates, evaluate, median, wire
from calorie_app.modules.energy.schemas import Explanation


def window(*, kcal="2200", complete=14, second="80", version="e1"):
    return [
        {
            "complete": i < complete,
            "kcal": kcal,
            "weights": ["80" if i < 7 else second] if i in (0, 6, 7, 13) else [],
            "energy_version": version,
        }
        for i in range(14)
    ]


@pytest.mark.parametrize(
    "complete,state",
    [
        (0, "insufficient_data"),
        (9, "insufficient_data"),
        (10, "manual_review_required"),
        (13, "manual_review_required"),
        (14, "ready"),
    ],
)
def test_completeness(complete, state):
    assert evaluate(window(complete=complete), current="2000").state == state


@pytest.mark.parametrize("kcal", [None, "0"])
def test_null_and_zero_are_not_complete(kcal):
    assert evaluate(window(kcal=kcal), current="2000").state == "insufficient_data"


@pytest.mark.parametrize(
    "weights,expected",
    [
        (["1"], 1),
        (["1", "5"], 3),
        (["1", "5", "7"], 5),
        (["1", "5", "7", "9"], 6),
    ],
)
def test_exact_daily_medians(weights, expected):
    assert median(weights) == expected


def test_many_measurements_do_not_give_a_day_more_weight():
    days = window()
    days[0]["weights"] = ["79"] * 50 + ["81"] * 50
    assert evaluate(days, current="2000").first_median == 80


def test_two_distinct_days_in_each_half():
    days = window()
    days[6]["weights"] = []
    days[0]["weights"] = ["80"] * 20
    assert evaluate(days, current="2000").state == "insufficient_data"


@pytest.mark.parametrize(
    "second,state",
    [
        ("80.399999", "ready"),
        ("80.4", "ready"),
        ("80.400001", "manual_review_required"),
        ("79.6", "ready"),
        ("79.599999", "manual_review_required"),
    ],
)
def test_stability_boundary(second, state):
    assert evaluate(window(second=second), current="2000").state == state


@pytest.mark.parametrize(
    "kcal,state,number",
    [
        ("2019.999999", "no_change", None),
        ("2020", "ready", "2020"),
        ("2020.000001", "ready", "2020.000001"),
        ("1980.000001", "no_change", None),
        ("1980", "ready", "1980"),
        ("1980.000000", "ready", "1980"),
        ("2100", "ready", "2100"),
        ("2100.000001", "ready", "2100"),
        ("1900", "ready", "1900"),
        ("1899.999999", "ready", "1900"),
    ],
)
def test_one_percent_and_five_percent(kcal, state, number):
    actual = evaluate(window(kcal=kcal), current="2000")
    assert (actual.state, actual.proposed) == (state, number)


def test_mean_is_not_rounded_per_day():
    days = window(kcal="2020")
    days[0]["kcal"] = "2020.000001"
    assert evaluate(days, current="2000").proposed == "2020.000000071429"


@pytest.mark.parametrize(
    "baseline,expected",
    [
        ("1900", "2090"),
        ("2000", "2100"),
        ("2100", "2100"),
    ],
)
def test_automatic_baseline_clamp(baseline, expected):
    actual = evaluate(window(kcal="5000"), current="2000", baseline=baseline, automatic=True)
    assert actual.proposed == expected


def test_automatic_does_not_invent_a_baseline():
    assert evaluate(window(), current="2000", automatic=True).state == "baseline_required"


@pytest.mark.parametrize("change", ["missing", "different"])
def test_history_version_change_blocks_number(change):
    days = window()
    days[0]["energy_version"] = None if change == "missing" else "e2"
    assert evaluate(days, current="2000").state == "energy_history_unavailable"


def test_half_up_and_inward_boundary():
    assert wire(Fraction(1, 2 * 10**12)) == "0.000000000001"
    boundary = Fraction(21000000000000005, 10**13)
    assert wire(boundary, upper=boundary) == "2100"
    assert wire(boundary, lower=boundary) == "2100.000000000001"


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-03-28T23:30:00+00:00", "2026-03-28"),
        ("2026-03-29T22:30:00+00:00", "2026-03-29"),
        ("2026-10-25T23:30:00+00:00", "2026-10-25"),
    ],
)
def test_local_midnight_and_dst(now, expected):
    days = closed_dates(datetime.fromisoformat(now), "Europe/Warsaw")
    assert len(days) == 14 and days[-1].isoformat() == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 80.0, Decimal("NaN")])
def test_float_and_nonfinite_inputs_rejected(value):
    with pytest.raises(ValueError):
        median([value])


def test_provider_has_no_binding_number():
    with pytest.raises(ValueError):
        Explanation.model_validate(
            {
                "explanation": "text",
                "uncertainty": "high",
                "suggested_class": None,
                "maintenance_kcal": "2200",
            }
        )
