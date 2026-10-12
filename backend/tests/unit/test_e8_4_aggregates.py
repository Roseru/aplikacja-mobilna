"""Projection-only numerical oracles; no current diary, profile, worker or DB."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from calorie_app.modules.nemesis.aggregates import (
    DayProjectionFact,
    aggregate_projection_days,
    outcome_for_points,
)

START = date(2026, 10, 13)
END = START + timedelta(days=7)
AS_OF = datetime(2026, 10, 20, tzinfo=UTC)


def seed(duration=7):
    return [
        DayProjectionFact(
            START + timedelta(days=i),
            datetime(2026, 10, 14, tzinfo=UTC) + timedelta(days=i),
            0,
            False,
            None,
        )
        for i in range(duration)
    ]


def fact(day, *, intake="2000", maintenance=None, weight=None, in_goal=None):
    return replace(
        day,
        effective_complete=intake is not None,
        candidate_points=int(intake is not None) + int(intake is not None and in_goal is True),
        in_goal=in_goal,
        intake_kcal=Decimal(intake) if intake else None,
        maintenance_kcal=Decimal(maintenance) if maintenance else None,
        weight_kg=Decimal(weight) if weight else None,
    )


def aggregate(days, **changes):
    return aggregate_projection_days(
        days,
        start_date=START,
        end_date=START + timedelta(days=len(days)),
        as_of=changes.pop("as_of", AS_OF),
        share_weight_change=changes.pop("share_weight_change", True),
        share_mean_deficit=changes.pop("share_mean_deficit", True),
        **changes,
    )


def test_pending_until_accepted_maturity_and_empty_closed_valid_zero():
    days = seed()
    assert aggregate(days, as_of=days[0].matures_at - timedelta(microseconds=1)) is None
    ready = aggregate(days, as_of=days[0].matures_at)
    assert ready == {
        "regularity": {"points": 0, "closed_days": 1, "complete_days": 0, "days_in_goal": 0},
        "weight_change": {"state": "insufficient_data", "value": None, "observed_days": 0},
        "mean_deficit": {"state": "insufficient_data", "value": None, "eligible_days": 0},
    }


def test_regularities_use_mature_candidate_without_materialization_worker():
    days = seed()
    days[0] = fact(days[0], in_goal=True)
    days[1] = fact(days[1])  # No goal still earns one base point.
    days[2] = fact(days[2], in_goal=False)
    assert aggregate(days)["regularity"] == {
        "points": 4,
        "closed_days": 7,
        "complete_days": 3,
        "days_in_goal": 1,
    }
    assert aggregate(days, as_of=days[1].matures_at)["regularity"]["points"] == 3


def test_deficit_daily_percent_mean_twenty_minus_fifty_equals_minus_fifteen():
    days = seed()
    days[0] = fact(days[0], intake="2000", maintenance="2500")
    days[1] = fact(days[1], intake="3000", maintenance="2000")
    assert aggregate(days)["mean_deficit"] == {
        "state": "available",
        "value": "-15",
        "eligible_days": 2,
    }


def test_missing_maintenance_intake_or_completeness_not_fabricated_zero():
    days = seed()
    days[0] = fact(days[0], intake="1234")
    days[1] = fact(days[1], intake=None, maintenance="2500")
    assert aggregate(days)["regularity"]["points"] == 1
    assert aggregate(days)["mean_deficit"] == {
        "state": "insufficient_data",
        "value": None,
        "eligible_days": 0,
    }
    days[2] = fact(days[2], intake="2500", maintenance="2500")
    assert aggregate(days)["mean_deficit"] == {
        "state": "available",
        "value": "0",
        "eligible_days": 1,
    }


def test_positive_and_negative_zero_rounded_to_canonical_zero():
    days = seed()
    days[0] = fact(days[0], intake="1.000000000000001", maintenance="1")
    assert aggregate(days)["mean_deficit"]["value"] == "0"
    days[0] = fact(days[0], intake="0.999999999999999", maintenance="1")
    assert aggregate(days)["mean_deficit"]["value"] == "0"


def test_round_only_final_average_and_half_up_both_signs():
    days = seed()
    # Daily +/- 0.0000000000005. HALF_UP independently would lose the average.
    days[0] = fact(days[0], intake="0.999999999999995", maintenance="1")
    days[1] = fact(days[1], intake="1.000000000000005", maintenance="1")
    assert aggregate(days)["mean_deficit"]["value"] == "0"
    assert aggregate(days, as_of=days[0].matures_at)["mean_deficit"]["value"] == "0.000000000001"
    days[0], days[1] = days[1], days[0]
    days[0] = replace(days[0], local_date=START, matures_at=datetime(2026, 10, 14, tzinfo=UTC))
    days[1] = replace(
        days[1], local_date=START + timedelta(days=1), matures_at=datetime(2026, 10, 15, tzinfo=UTC)
    )
    assert aggregate(days, as_of=days[0].matures_at)["mean_deficit"]["value"] == "-0.000000000001"


def exact_half_up(value: Fraction):
    scaled = value * 10**12
    absolute = abs(scaled)
    quotient, remainder = divmod(absolute.numerator, absolute.denominator)
    rounded = quotient + int(2 * remainder >= absolute.denominator)
    if not rounded:
        return "0"
    integer, fraction = divmod(rounded, 10**12)
    text = f"{integer}.{fraction:012d}".rstrip("0").rstrip(".")
    return ("-" if value < 0 else "") + text


def test_many_varying_denominators_matches_exact_rational_oracle_under_low_global_context():
    days = seed(90)
    for i, day in enumerate(days):
        days[i] = fact(day, intake=str(100003 + i * 179), maintenance=str(100019 + i * 181))
    exact = (
        sum(
            (
                100
                * (Fraction(day.maintenance_kcal) - Fraction(day.intake_kcal))
                / Fraction(day.maintenance_kcal)
                for day in days
            ),
            Fraction(),
        )
        / 90
    )
    with localcontext() as context:
        context.prec = 6
        result = aggregate(days, as_of=datetime(2027, 2, 1, tzinfo=UTC))
    assert result["mean_deficit"]["value"] == exact_half_up(exact)
    assert result["mean_deficit"]["eligible_days"] == 90


def test_negative_deficit_unbounded_percent_does_not_change_score():
    days = seed()
    days[0] = fact(days[0], intake="999999999999999999999999999999", maintenance="0.000000000001")
    exact = (
        100
        * (Fraction(days[0].maintenance_kcal) - Fraction(days[0].intake_kcal))
        / Fraction(days[0].maintenance_kcal)
    )
    result = aggregate(days)
    assert result["mean_deficit"]["value"] == exact_half_up(exact)
    assert result["regularity"]["points"] == 1


def test_weight_uses_first_last_available_mature_dates_not_raw_measurement_count():
    days = seed()
    days[1] = fact(days[1], intake=None, weight="80")
    days[3] = fact(days[3], intake=None, weight="90")
    days[5] = fact(days[5], intake=None, weight="72")
    assert aggregate(days)["weight_change"] == {
        "state": "available",
        "value": "-10",
        "observed_days": 3,
        "first_date": "2026-10-14",
        "last_date": "2026-10-18",
    }
    assert aggregate(days)["regularity"]["points"] == 0
    assert aggregate(days, as_of=days[1].matures_at)["weight_change"] == {
        "state": "insufficient_data",
        "value": None,
        "observed_days": 1,
    }


def test_hidden_exact_state_despite_available_private_facts():
    days = seed()
    days[0] = fact(days[0], maintenance="2500", weight="80")
    days[1] = fact(days[1], maintenance="2000", weight="85")
    result = aggregate(days, share_weight_change=False, share_mean_deficit=False)
    assert result["weight_change"] == result["mean_deficit"] == {"state": "hidden"}


@pytest.mark.parametrize("duration", [7, 30, 90])
def test_exact_number_accepted_calendar_dates(duration):
    assert (
        aggregate(seed(duration), as_of=datetime(2027, 2, 1, tzinfo=UTC))["regularity"][
            "closed_days"
        ]
        == duration
    )


def test_accepted_boundary_remains_authority_without_current_profile_zone():
    days = seed()
    # Warsaw 2026-10-14 midnight is 2026-10-13 22:00Z; no New York fallback.
    days[0] = fact(replace(days[0], matures_at=datetime(2026, 10, 13, 22, tzinfo=UTC)))
    assert (
        aggregate(days, as_of=datetime(2026, 10, 13, 22, tzinfo=UTC))["regularity"]["points"] == 1
    )
    assert aggregate(days, as_of=datetime(2026, 10, 13, 21, 59, 59, tzinfo=UTC)) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda days: [],
        lambda days: days[:-1],
        lambda days: days[::-1],
        lambda days: days[:1] + days[:1] + days[2:],
    ],
)
def test_missing_corrupt_seed_is_unavailable_not_pending_or_empty_zero(mutation):
    days = mutation(seed())
    with pytest.raises(ValueError, match="seed_incomplete"):
        aggregate_projection_days(
            days,
            start_date=START,
            end_date=END,
            as_of=AS_OF,
            share_weight_change=True,
            share_mean_deficit=True,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate_points": 2},
        {"candidate_points": True},
        {"effective_complete": 1},
        {"weight_kg": Decimal("0")},
        {"maintenance_kcal": Decimal("NaN")},
        {"intake_kcal": 1.0},
        {"effective_complete": True, "candidate_points": 1},
        {"in_goal": True},
        {"matures_at": datetime(2026, 10, 14)},
    ],
)
def test_invalid_durable_facts_fail_closed(changes):
    with pytest.raises(ValueError):
        replace(seed()[0], **changes)


@pytest.mark.parametrize(
    "self_points,peer_points,outcome",
    [(0, 0, "tie"), (1, 0, "self_wins"), (0, 1, "opponent_wins"), (180, 180, "tie")],
)
def test_outcome_only_points(self_points, peer_points, outcome):
    assert outcome_for_points(self_points, peer_points) == outcome


@pytest.mark.parametrize("points", [-1, 181, True, "1", 1.0])
def test_outcome_rejects_nonauthoritative_points(points):
    with pytest.raises(ValueError):
        outcome_for_points(points, 0)


def test_known_zero_incomplete_intake_is_not_deficit_data():
    days = seed()
    days[0] = replace(days[0], intake_kcal=Decimal("0"), maintenance_kcal=Decimal("2000"))
    result = aggregate(days)
    assert result["regularity"]["points"] == 0
    assert result["mean_deficit"] == {
        "state": "insufficient_data",
        "value": None,
        "eligible_days": 0,
    }
    with pytest.raises(ValueError, match="positive_intake"):
        replace(days[0], effective_complete=True, candidate_points=1)


@pytest.mark.parametrize(
    "intakes,expected",
    [
        (["1800", "1800", "4500", "2699.999999999946"], "0.000000000001"),
        (["3600", "3600", "900", "2700.000000000054"], "-0.000000000001"),
    ],
    ids=["positive", "negative"],
)
@pytest.mark.parametrize("order", [(0, 1, 2, 3), (3, 2, 1, 0)], ids=["forward", "reverse"])
def test_exact_mean_half_tie_after_recurring_daily_percent_cancellation(intakes, expected, order):
    # The first three daily thirds cancel exactly. The fourth contributes
    # +/-2e-12%, so the four-day mean is exactly +/-0.5e-12%.
    # Three valid empty dates stay excluded rather than diluting that mean.
    days = seed()
    for index, source in enumerate(order):
        days[index] = fact(days[index], intake=intakes[source], maintenance="2700", in_goal=False)
    result = aggregate(days)
    assert result["mean_deficit"] == {
        "state": "available",
        "value": expected,
        "eligible_days": 4,
    }
    assert result["regularity"] == {
        "points": 4,
        "closed_days": 7,
        "complete_days": 4,
        "days_in_goal": 0,
    }
