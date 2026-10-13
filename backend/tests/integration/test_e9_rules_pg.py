"""Independent exact SQL rule boundaries, against the same production function."""

import json

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def context(kcal="2200", complete=14, second="80"):
    return {
        "current": "2000",
        "baseline": "1900",
        "days": [
            {
                "complete": i < complete,
                "kcal": kcal,
                "energy_version": "v1",
                "weights": ["80" if i < 7 else second] if i in (0, 6, 7, 13) else [],
            }
            for i in range(14)
        ],
    }


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
def test_sql_completeness_boundary(database, complete, state):
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),false)"),
            {"v": json.dumps(context(complete=complete))},
        )
    assert result["state"] == state


@pytest.mark.parametrize(
    "second,state",
    [("80.399999", "ready"), ("80.4", "ready"), ("80.400001", "manual_review_required")],
)
def test_sql_stability_boundary(database, second, state):
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),false)"),
            {"v": json.dumps(context(second=second))},
        )
    assert result["state"] == state


@pytest.mark.parametrize(
    "kcal,state,expected",
    [
        ("2019.999999", "no_change", None),
        ("2020", "ready", "2020"),
        ("2020.000001", "ready", "2020.000001"),
        ("1980.000001", "no_change", None),
        ("1980", "ready", "1980"),
        ("1979.999999", "ready", "1979.999999"),
        ("2100", "ready", "2100"),
        ("2100.000001", "ready", "2100"),
        ("1900", "ready", "1900"),
        ("1899.999999", "ready", "1900"),
    ],
)
def test_sql_one_and_five_percent_boundaries(database, kcal, state, expected):
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),false)"),
            {"v": json.dumps(context(kcal=kcal))},
        )
    assert (result["state"], result["proposed"]) == (state, expected)


def test_sql_ten_percent_and_daily_median_not_last_measurement(database):
    value = context(kcal="5000")
    value["days"][0]["weights"] = ["79", "81"]
    value["days"][6]["weights"] = ["80"]
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),true)"), {"v": json.dumps(value)}
        )
    assert result["first_median"] == "80" and result["proposed"] == "2090"


def test_sql_mean_rounds_once_and_wire_boundary_stays_inside(database):
    value = context(kcal="2020")
    value["days"][0]["kcal"] = "2020.000001"
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),false)"), {"v": json.dumps(value)}
        )
        assert result["proposed"] == "2020.000000071429"
        assert c.scalar(text("SELECT app.e9_wire(0.0000000000005)")) == "0.000000000001"


def test_sql_exact_wire_clamp_bound_rounding(database):
    value = context(kcal="9999")
    value["current"] = "2000.000000000001"
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),false)"), {"v": json.dumps(value)}
        )
    assert result["proposed"] == "2100.000000000001"
    assert result["upper"] == "2100.00000000000105"


def test_sql_empty_wire_quantum_intersection_has_no_proposal(database):
    value = context() | {"current": "2200.000000000022", "baseline": "1900.000000000019"}
    with database[0].connect() as c:
        result = c.scalar(
            text("SELECT app.e9_rules(CAST(:v AS jsonb),true)"), {"v": json.dumps(value)}
        )
    assert result["state"] == "baseline_range_conflict"
    assert result["proposed"] is None
