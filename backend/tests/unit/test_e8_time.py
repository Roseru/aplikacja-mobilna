"""Controlled UTC oracles: no test waits for a real midnight."""

from datetime import UTC, date, datetime, timedelta

import pytest

from calorie_app.modules.analytics.motivation.time import day_is_closed, day_matures_at


@pytest.mark.parametrize(
    "day,zone,expected",
    [
        ("2026-03-29", "Europe/Warsaw", "2026-03-29T22:00:00+00:00"),
        ("2026-10-25", "Europe/Warsaw", "2026-10-25T23:00:00+00:00"),
        ("2018-11-03", "America/Sao_Paulo", "2018-11-04T03:00:00+00:00"),
        ("2026-10-31", "America/Havana", "2026-11-01T04:00:00+00:00"),
        ("2011-12-29", "Pacific/Apia", "2011-12-30T10:00:00+00:00"),
        ("2011-12-30", "Pacific/Apia", "2011-12-30T10:00:00+00:00"),
        ("1905-12-31", "Asia/Kolkata", "1905-12-31T18:38:50+00:00"),
        ("2026-10-11", "Asia/Kathmandu", "2026-10-11T18:15:00+00:00"),
        ("2026-10-11", "UTC", "2026-10-12T00:00:00+00:00"),
        ("1919-03-30", "America/Toronto", "1919-03-31T04:30:00+00:00"),
    ],
)
def test_real_boundary_independent_utc_oracle(day, zone, expected):
    local_date = date.fromisoformat(day)
    oracle = datetime.fromisoformat(expected)
    assert day_matures_at(local_date, zone) == oracle
    assert not day_is_closed(local_date, zone, oracle - timedelta(microseconds=1))
    assert day_is_closed(local_date, zone, oracle)
    assert day_is_closed(local_date, zone, oracle + timedelta(microseconds=1))


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_warsaw_civil_day_not_utc_24_hours(day, hours):
    previous_end = day_matures_at(day - timedelta(days=1), "Europe/Warsaw")
    end = day_matures_at(day, "Europe/Warsaw")
    assert end - previous_end == timedelta(hours=hours)


@pytest.mark.parametrize("zone", ["UTC", "Pacific/Kiritimati", "America/Los_Angeles"])
def test_supported_civil_date_boundaries_are_safe(zone):
    assert day_matures_at(date.min, zone) is not None
    assert day_matures_at(date.max - timedelta(days=1), zone) is not None
    assert day_matures_at(date.max, zone) is None
    assert not day_is_closed(date.max, zone, datetime.max.replace(tzinfo=UTC))


def test_as_of_requires_aware_server_clock():
    with pytest.raises(ValueError, match="aware_as_of_required"):
        day_is_closed(date(2026, 10, 11), "UTC", datetime(2026, 10, 12))
