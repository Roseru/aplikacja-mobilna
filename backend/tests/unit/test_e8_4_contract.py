"""Strict E8.4 statistics wire contracts and independently frozen examples."""

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from calorie_app.modules.nemesis.schemas import (
    DeficitMetric,
    NemesisParticipantStatistics,
    NemesisStatistics,
    SignedPercent,
    WeightMetric,
)

ROOT = Path(__file__).resolve().parents[3]
STATISTICS = TypeAdapter(NemesisStatistics)
PERCENT = TypeAdapter(SignedPercent)


def sample(name="provisional"):
    return json.loads((ROOT / f"contracts/examples/nemesis-statistics-{name}.json").read_text())


@pytest.mark.parametrize("name", ["pending", "provisional", "final", "hidden"])
def test_frozen_wire_examples_roundtrip(name):
    wire = sample(name)
    assert STATISTICS.dump_python(STATISTICS.validate_python(wire), mode="json") == wire


@pytest.mark.parametrize(
    "text",
    ["0", "-50", "-15", "-0.000000000001", "100.123456789012", "123456789012345678901234567890"],
)
def test_signed_percentage_without_legacy_integer_bound(text):
    value = PERCENT.validate_python(text)
    assert isinstance(value, Decimal)
    assert PERCENT.dump_python(value, mode="json") == text


@pytest.mark.parametrize(
    "value",
    [
        0,
        0.0,
        -15.0,
        True,
        None,
        Decimal("-15"),
        "NaN",
        "Infinity",
        "-Infinity",
        "1e2",
        "1E+2",
        "+1",
        " 1",
        "1 ",
        "01",
        "-01",
        "1.",
        ".1",
        "0.0",
        "-0",
        "-0.00",
        "1.10",
        "0.1234567890123",
        "-15\n",
        "Ĺ®Ë‡",
    ],
)
def test_signed_percent_rejects_noncanonical_or_nonstring_wire(value):
    with pytest.raises(ValidationError):
        PERCENT.validate_python(value)


@pytest.mark.parametrize("field", ["self", "opponent", "outcome", "finalized_at"])
def test_pending_must_not_suggest_zero_or_result(field):
    wire = sample("pending")
    wire[field] = sample("final").get(field)
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire)


def test_status_is_required_strict_discriminator():
    wire = sample()
    for status in (None, "ready", 1, True):
        with pytest.raises(ValidationError):
            STATISTICS.validate_python(wire | {"status": status})
    del wire["status"]
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire)


@pytest.mark.parametrize("revision", [0, -1, True, 1.0, "1", 9223372036854775808])
def test_revision_is_positive_strict_bigint(revision):
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(sample() | {"revision": revision})


def test_revision_has_no_int32_limit():
    assert (
        STATISTICS.validate_python(sample() | {"revision": 9223372036854775807}).revision
        == 9223372036854775807
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("points", 8),
        ("closed_days", 0),
        ("closed_days", 91),
        ("complete_days", 8),
        ("days_in_goal", 4),
        ("points", "4"),
        ("complete_days", True),
    ],
)
def test_regularity_counts_and_score_are_consistent(field, value):
    wire = sample()
    wire["self"]["regularity"][field] = value
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire)


@pytest.mark.parametrize("outcome", ["opponent_wins", "tie"])
def test_outcome_only_follows_points(outcome):
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(sample() | {"outcome": outcome})


def test_two_sides_have_same_closed_dates():
    wire = sample()
    wire["opponent"]["regularity"]["closed_days"] = 6
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire)


@pytest.mark.parametrize("adapter", [TypeAdapter(WeightMetric), TypeAdapter(DeficitMetric)])
@pytest.mark.parametrize(
    "extra",
    [
        {"value": None},
        {"observed_days": 0},
        {"eligible_days": 0},
        {"data_available": False},
        {"first_date": "2026-10-13"},
    ],
)
def test_hidden_discloses_exactly_state(adapter, extra):
    assert adapter.dump_python(adapter.validate_python({"state": "hidden"}), mode="json") == {
        "state": "hidden"
    }
    with pytest.raises(ValidationError):
        adapter.validate_python({"state": "hidden", **extra})


@pytest.mark.parametrize(
    "wire",
    [
        {"state": "insufficient_data", "value": None, "observed_days": 0},
        {"state": "insufficient_data", "value": None, "observed_days": 1},
        {
            "state": "available",
            "value": "0",
            "observed_days": 2,
            "first_date": "2026-10-13",
            "last_date": "2026-10-14",
        },
    ],
)
def test_weight_null_and_zero_have_distinct_states(wire):
    assert (
        TypeAdapter(WeightMetric).dump_python(
            TypeAdapter(WeightMetric).validate_python(wire), mode="json"
        )
        == wire
    )


@pytest.mark.parametrize(
    "changes",
    [{"value": "0"}, {"observed_days": 2}, {"observed_days": True}, {"first_date": "2026-10-13"}],
)
def test_insufficient_weight_forbids_fabricated_data(changes):
    wire = {"state": "insufficient_data", "value": None, "observed_days": 1}
    with pytest.raises(ValidationError):
        TypeAdapter(WeightMetric).validate_python(wire | changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"value": None},
        {"observed_days": 1},
        {"last_date": "2026-10-13"},
        {"first_date": "2026-10-19"},
        {"observed_days": 8},
    ],
)
def test_available_weight_requires_two_distinct_dates_and_value(changes):
    wire = sample()["self"]["weight_change"]
    with pytest.raises(ValidationError):
        TypeAdapter(WeightMetric).validate_python(wire | changes)


@pytest.mark.parametrize(
    "wire",
    [
        {"state": "insufficient_data", "value": None, "eligible_days": 0},
        {"state": "available", "value": "0", "eligible_days": 1},
        {"state": "available", "value": "-50", "eligible_days": 1},
    ],
)
def test_deficit_all_three_numerical_semantics(wire):
    assert (
        TypeAdapter(DeficitMetric).dump_python(
            TypeAdapter(DeficitMetric).validate_python(wire), mode="json"
        )
        == wire
    )


@pytest.mark.parametrize(
    "wire",
    [
        {"state": "insufficient_data", "value": "0", "eligible_days": 0},
        {"state": "insufficient_data", "value": None, "eligible_days": 1},
        {"state": "available", "value": None, "eligible_days": 1},
        {"state": "available", "value": "0", "eligible_days": 0},
    ],
)
def test_deficit_requires_proper_counts_and_value(wire):
    with pytest.raises(ValidationError):
        TypeAdapter(DeficitMetric).validate_python(wire)


def test_metrics_cannot_count_more_than_eligible_closed_dates():
    wire = sample()["self"]
    for field, key, count in (
        ("weight_change", "observed_days", 8),
        ("mean_deficit", "eligible_days", 4),
    ):
        invalid = copy.deepcopy(wire)
        invalid[field][key] = count
        with pytest.raises(ValidationError):
            NemesisParticipantStatistics.model_validate(invalid)


@pytest.mark.parametrize(
    "field",
    ["partner_id", "account_id", "source_revision", "weight_kg", "intake_kcal", "maintenance_kcal"],
)
def test_no_private_partner_source_fields(field):
    wire = sample()
    wire["opponent"][field] = "secret"
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire)


def test_finalized_at_required_only_final_and_after_deadline():
    wire = sample("final")
    STATISTICS.validate_python(wire)
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire | {"status": "provisional"})
    for finalized in (wire["deadline"], "2026-11-21T00:00:00Z"):
        with pytest.raises(ValidationError):
            STATISTICS.validate_python(wire | {"finalized_at": finalized})
    del wire["finalized_at"]
    with pytest.raises(ValidationError):
        STATISTICS.validate_python(wire)


def test_openapi_discriminators_and_canonical_signed_pattern():
    schema = STATISTICS.json_schema()
    assert schema["discriminator"]["propertyName"] == "status"
    participant = schema["$defs"]["NemesisParticipantStatistics"]["properties"]
    assert participant["weight_change"]["discriminator"]["propertyName"] == "state"
    assert participant["mean_deficit"]["discriminator"]["propertyName"] == "state"
    assert schema["$defs"]["WeightAvailable"]["properties"]["value"]["type"] == "string"
    assert schema["$defs"]["HiddenMetric"]["additionalProperties"] is False


def test_final_requires_all_period_dates_mature():
    wire = sample("final")
    for side in ("self", "opponent"):
        wire[side]["regularity"]["closed_days"] = 6
    with pytest.raises(ValidationError, match="all_period_dates"):
        STATISTICS.validate_python(wire)
