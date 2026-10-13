"""Text aggregate payload for explanation only; no owner or source records."""

import json

from calorie_app.modules.ai.result import parse_bounded_json
from calorie_app.modules.energy.schemas import Explanation

PROMPT_VERSION = "energy-explanation-v1"
SCHEMA_VERSION = "energy-explanation-v1"
PREPARATION_VERSION = "energy-aggregates-v1"
KEYS = frozenset(
    {
        "rule_version",
        "state",
        "complete_days",
        "weight_days",
        "first_median",
        "second_median",
        "proposed",
        "lower",
        "upper",
        "date_from",
        "date_to",
    }
)


def validate_aggregates(value):
    if not isinstance(value, dict) or set(value) - KEYS:
        raise ValueError("invalid energy aggregates")
    # The frozen deterministic backend result is data, never system instructions.
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > 16384:
        raise ValueError("energy aggregate size")
    if parse_bounded_json(raw, max_bytes=16384) != value:
        raise ValueError("invalid energy aggregate wire")
    return value


def build_request(value, model):
    value = validate_aggregates(value)
    schema = Explanation.model_json_schema()
    return {
        "model": "models/" + model,
        "systemInstruction": {
            "parts": [
                {
                    "text": "Explain the frozen energy_adjustment_v1 result and its uncertainty. "
                    "Do not select or change any energy number, goal, class or account. "
                    "Only return explanation, uncertainty, suggested_class. "
                    "Any class suggestion is optional and requires a separate user decision."
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": json.dumps(value, allow_nan=False)}]}],
        "serviceTier": "standard",
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingLevel": "MINIMAL", "includeThoughts": False},
            "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}},
        },
    }


def parse_explanation(raw):
    return Explanation.model_validate(parse_bounded_json(raw, max_bytes=16384))
