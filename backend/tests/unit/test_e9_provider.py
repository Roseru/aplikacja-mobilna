"""Typed text aggregates and explanation schema never authorize a number."""

import json

import pytest

from calorie_app.integrations.gemini.energy import build_request
from calorie_app.integrations.gemini.mock import generate_envelope
from calorie_app.integrations.gemini.protocol import parse_generate_response
from calorie_app.integrations.gemini.transport import execute

AGGREGATES = {
    "rule_version": "energy_adjustment_v1",
    "state": "ready",
    "complete_days": 14,
    "weight_days": 4,
    "first_median": "80",
    "second_median": "80",
    "proposed": "2200",
    "lower": "2090",
    "upper": "2310",
    "date_from": "2026-09-29",
    "date_to": "2026-10-12",
}
EXPLANATION = {
    "explanation": "Synthetic deterministic explanation",
    "uncertainty": "high",
    "suggested_class": None,
}


def test_text_request_contains_no_image_or_owner():
    request = build_request(AGGREGATES, "gemini-3.5-flash-lite")
    text = json.dumps(request)
    assert "inlineData" not in text and "account_id" not in text
    assert request["contents"][0]["parts"] == [{"text": json.dumps(AGGREGATES)}]


@pytest.mark.parametrize(
    "extra",
    [
        {"maintenance_kcal": "100000"},
        {"goal_type": "gain"},
        {"uncertainty": float("inf")},
        {"explanation": None},
        {"suggested_class": "admin"},
        {"explanation": ""},
    ],
)
def test_bad_model_output_cannot_produce_binding_result(extra):
    result = parse_generate_response(
        generate_envelope(EXPLANATION | extra), purpose="energy_adjustment"
    )
    assert result.code != "ok" and result.result is None


def test_valid_energy_response_uses_strict_explanation():
    result = parse_generate_response(generate_envelope(EXPLANATION), purpose="energy_adjustment")
    assert result.code == "ok"
    assert result.result.model_dump(mode="json") == EXPLANATION


def test_real_mock_process_receives_typed_aggregates():
    result = execute(
        "mock",
        "generateContent",
        AGGREGATES,
        {"purpose": "energy_adjustment", "mock_scenario": "valid"},
        10,
    )
    assert result.code == "ok"
    assert result.result.suggested_class is None


def test_aggregate_payload_cannot_be_used_as_a_photo():
    result = execute("mock", "generateContent", AGGREGATES, {"mock_scenario": "valid"}, 10)
    assert result.code == "provider_unavailable" and result.sent is False
