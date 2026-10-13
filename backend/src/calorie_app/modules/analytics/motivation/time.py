"""Resolve preserved civil dates to real UTC closure instants."""

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


@lru_cache(maxsize=4096)
def day_matures_at(local_date: date, time_zone: str) -> datetime | None:
    """First real instant after a date, validating both IANA midnight folds.

    A nonexistent midnight resolves to the offset-transition boundary, not a
    synthetic wall time. A wholly skipped next date resolves the same way.
    date.max stays preliminary: its successor cannot be represented by Python's
    civil-time contract. The bounded cache stores only public zone/date pairs.
    """
    zone = ZoneInfo(time_zone)
    if local_date == date.max:
        return None
    midnight = datetime.combine(local_date + timedelta(days=1), time.min)
    candidates = [midnight.replace(tzinfo=zone, fold=fold).astimezone(UTC) for fold in (0, 1)]
    real = [
        instant
        for instant in candidates
        if instant.astimezone(zone).replace(tzinfo=None) == midnight
    ]
    if real:
        return min(real)
    # For an offset gap the two fold projections straddle the transition.
    # Search integer microseconds in UTC, so skipped dates and sub-hour offsets
    # need neither local arithmetic nor a fixed-length day assumption.
    lower, upper = min(candidates), max(candidates)
    if lower.astimezone(zone).date() > local_date or upper.astimezone(zone).date() <= local_date:
        raise ValueError("unresolvable_day_closure")
    while upper - lower > timedelta(microseconds=1):
        middle = lower + (upper - lower) // 2
        if middle.astimezone(zone).date() > local_date:
            upper = middle
        else:
            lower = middle
    return upper


def day_is_closed(local_date: date, time_zone: str, as_of: datetime) -> bool:
    """No profile zone, client clock, or UTC+24h participates in closure."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("aware_as_of_required")
    matures_at = day_matures_at(local_date, time_zone)
    return matures_at is not None and as_of.astimezone(UTC) >= matures_at
