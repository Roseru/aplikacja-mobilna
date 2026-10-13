"""Deterministic oracle over durable Nemesis facts, without source or DB access.

The DB orchestrator owns provenance, locking and qualification. This reducer
never substitutes current diary/profile facts or a new time-zone resolution.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

from calorie_app.modules.analytics.motivation.rules import day_candidate_points
from calorie_app.modules.nemesis.schemas import canonical_percent


@dataclass(frozen=True)
class DayProjectionFact:
    local_date: date
    matures_at: datetime
    candidate_points: int
    effective_complete: bool
    in_goal: bool | None
    intake_kcal: Decimal | None = None
    maintenance_kcal: Decimal | None = None
    weight_kg: Decimal | None = None

    def __post_init__(self):
        _utc(self.matures_at)
        if type(self.local_date) is not date:
            raise ValueError("invalid_projection_date")
        if type(self.effective_complete) is not bool or (
            self.in_goal is not None and type(self.in_goal) is not bool
        ):
            raise ValueError("invalid_projection_complete")
        if type(self.candidate_points) is not int or self.candidate_points != day_candidate_points(
            self.effective_complete, self.in_goal
        ):
            raise ValueError("invalid_projection_candidate")
        if self.in_goal is True and not self.effective_complete:
            raise ValueError("invalid_projection_in_goal")
        for value, zero_allowed in (
            (self.intake_kcal, True),
            (self.maintenance_kcal, False),
            (self.weight_kg, False),
        ):
            if value is not None and (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
                or (value == 0 and not zero_allowed)
            ):
                raise ValueError("invalid_projection_numeric")
        if self.effective_complete and (self.intake_kcal is None or self.intake_kcal <= 0):
            raise ValueError("complete_projection_requires_positive_intake")


def _utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("projection_time_must_be_utc")


def _precision(values: Iterable[Decimal]) -> int:
    # Decimal precision for the unchanged first/last weight ratio. The mean
    # deficit uses exact fractions so recurring daily ratios cannot bias a tie.
    return max(
        80,
        50 + sum(len(value.as_tuple().digits) + abs(value.as_tuple().exponent) for value in values),
    )


def _rounded_percent(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
    return canonical_percent(rounded)


def _rounded_fraction_percent(value: Fraction) -> str:
    """Round the exact aggregate once, HALF_UP, without a Decimal context."""
    units, remainder = divmod(abs(value.numerator) * 10**12, value.denominator)
    units += int(2 * remainder >= value.denominator)
    if units == 0:
        return "0"
    digits = Decimal(units).as_tuple().digits
    return canonical_percent(Decimal((int(value.numerator < 0), digits, -12)))


def aggregate_projection_days(
    days: Iterable[DayProjectionFact],
    *,
    start_date: date,
    end_date: date,
    as_of: datetime,
    share_weight_change: bool,
    share_mean_deficit: bool,
) -> dict | None:
    """Return one participant's ready aggregates, or None before first maturity.

    Exactly all N accepted dates are required, including valid empty dates.
    Missing/duplicate facts raise rather than masquerade as zero or pending.
    Seed proof, qualification and privacy fences are verified by the caller;
    the two scope flags represent its already revalidated current sharing.
    """
    _utc(as_of)
    if type(share_weight_change) is not bool or type(share_mean_deficit) is not bool:
        raise ValueError("invalid_projection_sharing")
    duration = (end_date - start_date).days
    if duration not in (7, 30, 90):
        raise ValueError("invalid_projection_period")
    facts = tuple(days)
    expected = tuple(start_date + timedelta(days=i) for i in range(duration))
    if tuple(fact.local_date for fact in facts) != expected:
        raise ValueError("projection_seed_incomplete_or_unordered")
    closed = [fact for fact in facts if fact.matures_at <= as_of]
    if not closed:
        return None
    regularity = {
        "points": sum(fact.candidate_points for fact in closed),
        "closed_days": len(closed),
        "complete_days": sum(fact.effective_complete for fact in closed),
        "days_in_goal": sum(fact.effective_complete and fact.in_goal is True for fact in closed),
    }
    weight = {"state": "hidden"}
    if share_weight_change:
        observed = [fact for fact in closed if fact.weight_kg is not None]
        if len(observed) < 2:
            weight = {"state": "insufficient_data", "value": None, "observed_days": len(observed)}
        else:
            first, last = observed[0], observed[-1]
            with localcontext() as context:
                context.prec = _precision((first.weight_kg, last.weight_kg))
                value = _rounded_percent((last.weight_kg - first.weight_kg) / first.weight_kg * 100)
            weight = {
                "state": "available",
                "value": value,
                "observed_days": len(observed),
                "first_date": first.local_date.isoformat(),
                "last_date": last.local_date.isoformat(),
            }
    deficit = {"state": "hidden"}
    if share_mean_deficit:
        eligible = [
            fact for fact in closed if fact.effective_complete and fact.maintenance_kcal is not None
        ]
        if not eligible:
            deficit = {"state": "insufficient_data", "value": None, "eligible_days": 0}
        else:
            total = sum(
                (
                    100
                    * (Fraction(fact.maintenance_kcal) - Fraction(fact.intake_kcal))
                    / Fraction(fact.maintenance_kcal)
                    for fact in eligible
                ),
                Fraction(),
            )
            value = _rounded_fraction_percent(total / len(eligible))
            deficit = {"state": "available", "value": value, "eligible_days": len(eligible)}
    return {"regularity": regularity, "weight_change": weight, "mean_deficit": deficit}


def outcome_for_points(self_points: int, opponent_points: int) -> str:
    if any(
        type(value) is not int or not 0 <= value <= 180 for value in (self_points, opponent_points)
    ):
        raise ValueError("invalid_nemesis_points")
    return (
        "self_wins"
        if self_points > opponent_points
        else "opponent_wins"
        if self_points < opponent_points
        else "tie"
    )
