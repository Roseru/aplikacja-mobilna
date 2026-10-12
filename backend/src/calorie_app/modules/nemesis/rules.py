"""Pure civil-time lifecycle rules, independent of motivation and its mutable runtime."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

INVITE_TTL = timedelta(days=7)
SHARE_CODE_TTL = timedelta(days=1)
RESPONSE_RETENTION = timedelta(days=60)
FINALIZATION_GRACE = timedelta(days=30)


@dataclass(frozen=True)
class ChallengePeriod:
    start_date: date
    end_date: date  # Exclusive date boundary.
    start_at: datetime
    end_at: datetime
    deadline: datetime


def first_real_day_start(day: date, time_zone: str) -> datetime:
    """Earliest valid midnight, or gap transition; never invent a wholly skipped date."""
    zone = ZoneInfo(time_zone)
    try:
        midnight = datetime.combine(day, time.min)
        candidates = [midnight.replace(tzinfo=zone, fold=fold).astimezone(UTC) for fold in (0, 1)]
        real = [
            instant
            for instant in candidates
            if instant.astimezone(zone).replace(tzinfo=None) == midnight
        ]
        if real:
            return min(real)
        lower, upper = min(candidates), max(candidates)
        if not (
            lower.astimezone(zone).replace(tzinfo=None)
            < midnight
            <= upper.astimezone(zone).replace(tzinfo=None)
        ):
            raise ValueError("nemesis_day_boundary_unresolvable")
        # Both fold projections straddle a gap. UTC integer-microsecond search
        # finds its real transition even for non-hour changes and skipped dates.
        while upper - lower > timedelta(microseconds=1):
            middle = lower + (upper - lower) // 2
            if middle.astimezone(zone).replace(tzinfo=None) >= midnight:
                upper = middle
            else:
                lower = middle
        if upper.astimezone(zone).date() != day:
            raise ValueError("period_calendar_date_unavailable")
        return upper
    except OverflowError:
        raise ValueError("nemesis_period_out_of_range") from None


def next_local_day_start(as_of: datetime, time_zone: str) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("aware_lifecycle_clock_required")
    zone = ZoneInfo(time_zone)
    try:
        now = as_of.astimezone(UTC)
        day = as_of.astimezone(zone).date() + timedelta(days=1)
        # Whole-day gaps occur in IANA history. A bounded search skips them only
        # before the period starts, then the N consecutive dates must all exist.
        for _ in range(366):
            try:
                instant = first_real_day_start(day, time_zone)
            except ValueError as error:
                if str(error) != "period_calendar_date_unavailable":
                    raise
                day += timedelta(days=1)
                continue
            if instant <= now:
                raise ValueError("nemesis_day_boundary_unresolvable")
            return instant
    except OverflowError:
        raise ValueError("nemesis_period_out_of_range") from None
    raise ValueError("nemesis_day_boundary_unresolvable")


def challenge_period(accepted_at: datetime, duration_days: int, time_zone: str) -> ChallengePeriod:
    if type(duration_days) is not int or duration_days not in (7, 30, 90):
        raise ValueError("invalid_nemesis_duration")
    try:
        zone = ZoneInfo(time_zone)
        start_at = next_local_day_start(accepted_at, time_zone)
        start_date = start_at.astimezone(zone).date()
        end_date = start_date + timedelta(days=duration_days)
        previous = start_at
        for offset in range(1, duration_days):
            boundary = first_real_day_start(start_date + timedelta(days=offset), time_zone)
            if boundary <= previous:
                raise ValueError("nemesis_day_boundary_unresolvable")
            previous = boundary
        # The exclusive boundary itself need not be an existing civil date.
        # A skipped date after the final included day resolves to the next real
        # date boundary, while end_date remains start_date + N.
        end_at = next_local_day_start(previous, time_zone)
        deadline = end_at + FINALIZATION_GRACE
        # Verify roundtrips of the end and deadline also fit the shared civil contract.
        end_at.astimezone(zone)
        deadline.astimezone(zone)
        return ChallengePeriod(start_date, end_date, start_at, end_at, deadline)
    except OverflowError:
        raise ValueError("nemesis_period_out_of_range") from None
