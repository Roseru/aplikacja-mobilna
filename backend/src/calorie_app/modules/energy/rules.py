"""Exact, provider-independent energy_adjustment_v1; dates are source civil dates."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from zoneinfo import ZoneInfo

RULE_VERSION = "energy_adjustment_v1"
SCALE = 10**12


def exact(value):
    if isinstance(value, float) or isinstance(value, bool):
        raise ValueError("exact energy input required")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("finite input required")
    return Fraction(value)


def median(values):
    ordered = sorted(exact(value) for value in values)
    if not ordered:
        raise ValueError("missing median")
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def closed_dates(now: datetime, zone: str):
    if now.tzinfo is None:
        raise ValueError("database instant required")
    today = now.astimezone(ZoneInfo(zone)).date()
    return tuple(today - timedelta(days=14 - i) for i in range(14))


def wire(value, lower=None, upper=None):
    """HALF_UP once; a boundary rounded outwards moves one wire quantum inward."""
    if lower is not None and upper is not None and not wire_interval(lower, upper):
        raise ValueError("empty wire interval")
    value = exact(value)
    scaled = value * SCALE
    units = scaled.numerator // scaled.denominator
    if (scaled.numerator % scaled.denominator) * 2 >= scaled.denominator:
        units += 1
    if lower is not None and Fraction(units, SCALE) < lower:
        units = -((-exact(lower) * SCALE).numerator // (-exact(lower) * SCALE).denominator)
    if upper is not None and Fraction(units, SCALE) > upper:
        scaled_upper = exact(upper) * SCALE
        units = scaled_upper.numerator // scaled_upper.denominator
    result = format(Decimal(units).scaleb(-12), "f").rstrip("0").rstrip(".")
    return result or "0"


def wire_interval(lower, upper):
    lo, hi = exact(lower) * SCALE, exact(upper) * SCALE
    ceil_lo = -((-lo).numerator // (-lo).denominator)
    return ceil_lo <= hi.numerator // hi.denominator


@dataclass(frozen=True)
class Result:
    state: str
    complete_days: int
    weight_days: int
    first_median: Fraction | None = None
    second_median: Fraction | None = None
    candidate: Fraction | None = None
    proposed: str | None = None
    lower: Fraction | None = None
    upper: Fraction | None = None


def evaluate(days, *, current, baseline=None, automatic=False):
    """Fourteen ordered records: complete, kcal, weights, energy_version.

    Completeness comes from E5/E8. Deleted measurements never enter weights.
    Missing E/history makes a numeric decision unavailable, even if weight is stable.
    """
    if len(days) != 14:
        raise ValueError("exactly fourteen source dates required")
    complete = [
        day
        for day in days
        if day["complete"] and day["kcal"] is not None and exact(day["kcal"]) > 0
    ]
    daily = [median(day["weights"]) if day["weights"] else None for day in days]
    halves = [[v for v in daily[start : start + 7] if v is not None] for start in (0, 7)]
    observed = sum(v is not None for v in daily)
    if len(complete) < 10 or any(len(part) < 2 for part in halves):
        return Result("insufficient_data", len(complete), observed)
    m1, m2 = (median(part) for part in halves)
    if m1 <= 0 or m2 <= 0:
        return Result("insufficient_data", len(complete), observed)
    versions = {day["energy_version"] for day in days}
    if None in versions or len(versions) != 1 or current is None or exact(current) <= 0:
        return Result("energy_history_unavailable", len(complete), observed, m1, m2)
    if len(complete) != 14 or abs(m2 - m1) * 200 > m1:
        return Result("manual_review_required", len(complete), observed, m1, m2)
    current = exact(current)
    lower, upper = current * Fraction(95, 100), current * Fraction(105, 100)
    if automatic:
        if baseline is None or exact(baseline) <= 0:
            return Result("baseline_required", len(complete), observed, m1, m2)
        lower = max(lower, exact(baseline) * Fraction(9, 10))
        upper = min(upper, exact(baseline) * Fraction(11, 10))
        if lower > upper:
            return Result("baseline_range_conflict", len(complete), observed, m1, m2)
    if not wire_interval(lower, upper):
        return Result("baseline_range_conflict", len(complete), observed, m1, m2)
    candidate = sum(exact(day["kcal"]) for day in complete) / 14
    clamped = min(upper, max(lower, candidate))
    state = "no_change" if abs(clamped - current) * 100 < current else "ready"
    return Result(
        state,
        14,
        observed,
        m1,
        m2,
        candidate,
        wire(clamped, lower, upper) if state == "ready" else None,
        lower,
        upper,
    )
