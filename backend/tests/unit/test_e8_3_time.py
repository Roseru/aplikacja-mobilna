"""Independent UTC oracle vectors for real calendar lifecycle boundaries."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from calorie_app.modules.nemesis.rules import (
    FINALIZATION_GRACE,
    INVITE_TTL,
    SHARE_CODE_TTL,
    challenge_period,
    first_real_day_start,
    next_local_day_start,
)


@pytest.mark.parametrize("duration", [7, 30, 90])
@pytest.mark.parametrize("accepted", ["2026-03-27T12:00:00Z", "2026-10-23T12:00:00Z"])
def test_warsaw_period_uses_dates_and_23_or_25_hour_days(accepted, duration):
    period = challenge_period(datetime.fromisoformat(accepted), duration, "Europe/Warsaw")
    spring = accepted.startswith("2026-03")
    expected_start = date(2026, 3, 28) if spring else date(2026, 10, 24)
    assert period.start_date == expected_start
    assert period.end_date - period.start_date == timedelta(days=duration)
    assert period.end_at - period.start_at == timedelta(hours=duration * 24 + (-1 if spring else 1))
    assert period.deadline - period.end_at == timedelta(hours=30 * 24)
    assert period.start_at.tzinfo == UTC
    assert period.deadline.tzinfo == UTC


def test_accept_exactly_midnight_always_starts_following_date():
    accepted = datetime(2026, 10, 11, 22, tzinfo=UTC)  # Warsaw12Oct00:00.
    period = challenge_period(accepted, 7, "Europe/Warsaw")
    assert period.start_date == date(2026, 10, 13)
    assert period.start_at == datetime(2026, 10, 12, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    "day,zone,expected",
    [
        (date(2018, 11, 4), "America/Sao_Paulo", datetime(2018, 11, 4, 3, tzinfo=UTC)),
        (date(2024, 4, 26), "Africa/Cairo", datetime(2024, 4, 25, 22, tzinfo=UTC)),
        (date(2020, 11, 1), "America/Havana", datetime(2020, 11, 1, 4, tzinfo=UTC)),
        (date(1986, 1, 1), "Asia/Kathmandu", datetime(1985, 12, 31, 18, 30, tzinfo=UTC)),
    ],
)
def test_gap_ambiguous_and_non_hour_midnight_independent_vectors(day, zone, expected):
    actual = first_real_day_start(day, zone)
    assert actual == expected
    # Independent immediate-neighbour oracle proves the first valid instant.
    assert (actual - timedelta(microseconds=1)).astimezone(ZoneInfo(zone)).date() < day
    assert actual.astimezone(ZoneInfo(zone)).date() == day


def test_whole_date_skip_before_start_is_omitted():
    accepted = datetime(2011, 12, 29, 12, tzinfo=UTC)  # Apia29Dec02:00.
    period = challenge_period(accepted, 7, "Pacific/Apia")
    assert period.start_date == date(2011, 12, 31)
    assert period.start_at == datetime(2011, 12, 30, 10, tzinfo=UTC)
    assert period.end_date == date(2012, 1, 7)
    assert period.end_at == datetime(2012, 1, 6, 10, tzinfo=UTC)


def test_whole_date_skip_inside_period_refuses_before_mutation():
    with pytest.raises(ValueError, match="period_calendar_date_unavailable"):
        challenge_period(datetime(2011, 12, 25, 12, tzinfo=UTC), 7, "Pacific/Apia")
    with pytest.raises(ValueError, match="period_calendar_date_unavailable"):
        first_real_day_start(date(2011, 12, 30), "Pacific/Apia")


@pytest.mark.parametrize("duration", [7, 30, 90])
def test_utc_earliest_and_latest_supported_dates(duration):
    earliest = challenge_period(datetime(1, 1, 1, tzinfo=UTC), duration, "UTC")
    assert earliest.start_date == date(1, 1, 2)
    with pytest.raises(ValueError, match="nemesis_period_out_of_range"):
        challenge_period(datetime(9999, 12, 31, tzinfo=UTC), duration, "UTC")
    with pytest.raises(ValueError, match="nemesis_period_out_of_range"):
        challenge_period(datetime(9999, 12, 1, tzinfo=UTC), duration, "UTC")


@pytest.mark.parametrize(
    "accepted,zone",
    [
        (datetime(1, 1, 1, tzinfo=UTC), "America/New_York"),
        (datetime(9999, 12, 31, 23, tzinfo=UTC), "Pacific/Kiritimati"),
    ],
)
def test_local_roundtrip_overflow_is_explicit(accepted, zone):
    with pytest.raises(ValueError, match="nemesis_period_out_of_range"):
        challenge_period(accepted, 7, zone)


def test_naive_client_clock_and_bad_duration_cannot_decide_lifecycle():
    with pytest.raises(ValueError, match="aware_lifecycle_clock_required"):
        next_local_day_start(datetime(2026, 1, 1), "UTC")
    for duration in [True, "7", 7.0, 1]:
        with pytest.raises(ValueError, match="invalid_nemesis_duration"):
            challenge_period(datetime(2026, 1, 1, tzinfo=UTC), duration, "UTC")


def test_expiry_and_code_ttl_are_elapsed_utc_time():
    assert INVITE_TTL == timedelta(hours=7 * 24)
    assert SHARE_CODE_TTL == timedelta(hours=24)
    assert FINALIZATION_GRACE == timedelta(hours=30 * 24)


def test_skipped_exclusive_end_is_not_an_included_fabricated_date():
    period = challenge_period(datetime(2011, 12, 22, 12, tzinfo=UTC), 7, "Pacific/Apia")
    assert period.start_date == date(2011, 12, 23)
    assert period.end_date == date(2011, 12, 30)
    assert period.end_at == datetime(2011, 12, 30, 10, tzinfo=UTC)
    assert period.end_at.astimezone(ZoneInfo("Pacific/Apia")).date() == date(2011, 12, 31)
    assert period.end_at - period.start_at == timedelta(days=7)
