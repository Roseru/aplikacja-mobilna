import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from calorie_app.core.errors import DomainError
from calorie_app.modules.identity.router import idempotency_key
from calorie_app.modules.profiles.pagination import parse_goal_cursor, sign_goal_cursor
from calorie_app.modules.profiles.router import if_match_revision
from calorie_app.modules.profiles.schemas import (
    ConsentInput,
    Estimate,
    EstimateInput,
    GoalPayload,
    ProfilePayload,
)
from calorie_app.modules.profiles.service import estimate_energy

ROOT = Path(__file__).resolve().parents[3]


def example(name):
    return json.loads((ROOT / "contracts" / "examples" / "valid" / name).read_text())


@pytest.mark.parametrize("name", ["estimate.json", "estimate-submicro.json"])
def test_independent_e0_calculator_vectors(name):
    vector = example(name)
    result = estimate_energy(
        EstimateInput.model_validate(vector["input"]),
        datetime.fromisoformat(vector["estimated_at"]),
    )
    assert result == vector
    assert Estimate.model_validate(result).model_dump(mode="json") == result


@pytest.mark.parametrize(
    "change", [{"resting_kcal": "1781"}, {"maintenance_kcal": "3205"}, {"pal": "1.5"}]
)
def test_estimate_snapshot_must_match_exact_calculator(change):
    with pytest.raises(ValidationError):
        Estimate.model_validate(example("estimate.json") | change)


@pytest.mark.parametrize(
    ("variant", "activity", "resting", "maintenance"),
    [
        ("plus_5", "stationary", "1780", "2670"),
        ("plus_5", "line", "1780", "3204"),
        ("plus_5", "commando", "1780", "3916"),
        ("minus_161", "stationary", "1614", "2421"),
        ("minus_161", "line", "1614", "2905.2"),
        ("minus_161", "commando", "1614", "3550.8"),
    ],
)
def test_exact_pal_and_variants(variant, activity, resting, maintenance):
    data = EstimateInput(
        age_years=30,
        height_cm="180",
        weight_kg="80",
        equation_variant=variant,
        activity_class=activity,
    )
    result = estimate_energy(data, datetime(2026, 10, 9, tzinfo=UTC))
    assert result["resting_kcal"] == resting
    assert result["maintenance_kcal"] == maintenance


@pytest.mark.parametrize(
    "bad",
    [
        0,
        1.5,
        True,
        "0",
        "180.0",
        "0180",
        " 180",
        "+180",
        "NaN",
        "Infinity",
        "1e2",
        "180.0000001",
        "300.000001",
    ],
)
def test_strict_canonical_input(bad):
    data = example("estimate-input.json") | {"height_cm": bad}
    with pytest.raises(ValidationError):
        EstimateInput.model_validate(data)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("age_years", True),
        ("age_years", 17),
        ("age_years", 121),
        ("age_years", "30"),
        ("weight_kg", "1000.000001"),
        ("activity_class", "soldier"),
    ],
)
def test_calculator_input_ranges(field, bad):
    with pytest.raises(ValidationError):
        EstimateInput.model_validate(example("estimate-input.json") | {field: bad})


def test_nonpositive_result_rejected():
    data = EstimateInput(
        age_years=120,
        height_cm="1",
        weight_kg="1",
        equation_variant="minus_161",
        activity_class="line",
    )
    with pytest.raises(DomainError) as error:
        estimate_energy(data)
    assert error.value.status == 422


@pytest.mark.parametrize("bad", ["", "Europe/Imaginary", "../../Etc/UTC", "UTC+2"])
def test_semantic_time_zone(bad):
    with pytest.raises(ValidationError):
        ProfilePayload(pseudonym="A", height_cm=None, activity_class="line", time_zone=bad)


@pytest.mark.parametrize(
    "bad", ["2026-02-30T10:00:00Z", "2026-10-09T10:00:00+00:00", "2026-10-09T25:00:00Z"]
)
def test_real_calendar_and_utc_spelling(bad):
    with pytest.raises(ValidationError):
        GoalPayload.model_validate(example("goal.json") | {"decided_at": bad})


def test_dst_local_day_controls_goal_decision():
    goal = example("goal.json") | {
        "decided_at": "2026-10-25T23:30:00Z",
        "effective_from": "2026-10-26",
    }
    assert GoalPayload.model_validate(goal).effective_from.isoformat() == "2026-10-26"
    with pytest.raises(ValidationError):
        GoalPayload.model_validate(goal | {"effective_from": "2026-10-25"})


@pytest.mark.parametrize(
    "changes",
    [
        {"energy_kcal": "20000.000001"},
        {"protein_g": "5000.000001"},
        {"reason": "history_correction"},
        {"correction_of": str(uuid4())},
        {"effective_from": "2026-10-08"},
    ],
)
def test_goal_ranges_and_correction_audit(changes):
    with pytest.raises(ValidationError):
        GoalPayload.model_validate(example("goal.json") | changes)


@pytest.mark.parametrize(
    "data",
    [
        {"ranking": False},
        {"ranking": 1, "automatic_energy_adjustment": False},
        {"ranking": "false", "automatic_energy_adjustment": False},
        {"ranking": False, "automatic_energy_adjustment": False, "owner": "x"},
    ],
)
def test_full_strict_consents(data):
    with pytest.raises(ValidationError):
        ConsentInput.model_validate(data)


@pytest.mark.parametrize("bad", [None, "1", 'W/"1"', '"0"', '"01"', '"2147483648"', "*"])
def test_if_match_must_be_quoted_revision(bad):
    with pytest.raises(DomainError) as error:
        if_match_revision(bad)
    assert error.value.status == 422


def test_headers_canonical():
    key = str(uuid4())
    assert str(idempotency_key(key)) == key
    assert if_match_revision('"2147483647"') == 2147483647
    for bad in (None, key.upper(), "{" + key + "}", "x"):
        with pytest.raises(DomainError):
            idempotency_key(bad)


def test_goal_cursor_signed_bounded_and_has_separate_purpose():
    secret = SecretStr("a1" * 32)
    data = {
        "owner": str(uuid4()),
        "generation": 1,
        "epoch": str(uuid4()),
        "boundary": 2,
        "after": str(uuid4()),
        "limit": 1,
        "expires": 1790000000000000,
    }
    token = sign_goal_cursor(data, secret)
    assert len(token) < 1024
    assert parse_goal_cursor(token, secret) == data
    for bad in (token + "x", token.replace("gp1", "rp1"), "x" * 3000):
        with pytest.raises(DomainError) as error:
            parse_goal_cursor(bad, secret)
        assert error.value.status == 422
    with pytest.raises(DomainError):
        parse_goal_cursor(token, SecretStr("a2" * 32))
