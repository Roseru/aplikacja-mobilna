"""Technical REST metadata is bounded inert data, independent of strict food/usage."""

import base64
import copy
import json
from pathlib import Path
from sys import float_info

import pytest

from calorie_app.integrations.gemini.mock import generate_envelope
from calorie_app.integrations.gemini.protocol import (
    MAX_FINISH_MESSAGE_BYTES,
    MAX_THOUGHT_SIGNATURE_BYTES,
    parse_generate_response,
)
from calorie_app.modules.ai.prompts import INPUT_TOKEN_LIMIT, OUTPUT_TOKEN_LIMIT

ROOT = Path(__file__).resolve().parents[3]
FOOD = json.loads((ROOT / "contracts/examples/e7/provider-result.json").read_text(encoding="utf-8"))
AUXILIARY = {
    "thoughtSignature": "AQIDBA==",
    "tokenCount": 24,
    "finishMessage": "TECHNICAL_METADATA_DO_NOT_STORE",
    "avgLogprobs": -0.1,
}


def envelope(fields=None):
    value = json.loads(generate_envelope(FOOD))
    candidate = value["candidates"][0]
    for key, item in (fields or {}).items():
        target = (
            candidate["content"]["parts"][0]
            if key in {"thoughtSignature", "thought"}
            else candidate
        )
        target[key] = item
    return value


def parse(value):
    return parse_generate_response(json.dumps(value, ensure_ascii=False).encode("utf-8"))


@pytest.mark.parametrize("fields", [{key: value} for key, value in AUXILIARY.items()] + [AUXILIARY])
def test_each_optional_field_and_combination_has_identical_food_usage_and_wire(fields):
    baseline = parse(envelope())
    actual = parse(envelope(fields))
    assert actual == baseline and actual.code == "ok"
    assert actual.result.model_dump(mode="json") == FOOD
    assert actual.to_wire() == baseline.to_wire()
    wire = json.dumps(actual.to_wire())
    assert "thoughtSignature" not in wire and "finishMessage" not in wire
    assert AUXILIARY["thoughtSignature"] not in wire
    assert AUXILIARY["finishMessage"] not in wire


@pytest.mark.parametrize(
    "signature",
    ["", "AQIDBA==", "AQIDBA", "+/8=", "+/8", "-_8=", "-_8"],
    ids=["empty", "standard-padded", "standard", "symbols-padded", "symbols", "url-padded", "url"],
)
def test_protobuf_bytes_encodings_and_explicit_non_thought_part(signature):
    assert parse(envelope(AUXILIARY | {"thoughtSignature": signature, "thought": False})) == (
        parse(envelope())
    )


@pytest.mark.parametrize(
    "fields",
    [
        {
            "thoughtSignature": base64.b64encode(
                b"x" * (MAX_THOUGHT_SIGNATURE_BYTES // 4 * 3)
            ).decode()
        },
        {"finishMessage": "x" * MAX_FINISH_MESSAGE_BYTES},
        {"finishMessage": "🪖" * (MAX_FINISH_MESSAGE_BYTES // 4)},
        {"tokenCount": 0},
        {"tokenCount": INPUT_TOKEN_LIMIT + OUTPUT_TOKEN_LIMIT},
        {"avgLogprobs": 0},
        {"avgLogprobs": -float_info.max},
    ],
)
def test_inclusive_local_bounds_do_not_change_trusted_usage(fields):
    assert parse(envelope(fields)) == parse(envelope())


@pytest.mark.parametrize(
    "field,value",
    [
        ("thoughtSignature", value)
        for value in (
            None,
            True,
            4,
            [],
            {},
            "é",
            "?",
            "A",
            "AB==",
            "AQIDBA=",
            "AQIDBA===",
            "A=QIDBA",
            "-+8=",
            " AQIDBA==",
            "x" * (MAX_THOUGHT_SIGNATURE_BYTES + 1),
        )
    ]
    + [("tokenCount", value) for value in (None, True, False, "24", 24.0, -1, 10241, [], {})]
    + [
        ("finishMessage", value)
        for value in (None, True, 1, [], {}, "x" * (MAX_FINISH_MESSAGE_BYTES + 1), "🪖" * 1025)
    ]
    + [("avgLogprobs", value) for value in (None, True, False, "-0.1", [], {}, 0.1, -(10**310))],
    ids=lambda value: value if isinstance(value, str) and len(value) < 20 else "bounded-value",
)
def test_invalid_metadata_is_controlled_without_returning_the_value(field, value):
    actual = parse(envelope({field: value}))
    expected = (
        "provider_parts_invalid" if field == "thoughtSignature" else "provider_result_invalid"
    )
    assert actual.code == expected and actual.result is None
    assert field not in actual.to_wire()


@pytest.mark.parametrize(
    "field,value",
    [
        ("thought", True),
        ("thought", None),
        ("thought", 0),
        ("thought", "false"),
        ("avgLogprobs", float("nan")),
        ("avgLogprobs", float("inf")),
        ("avgLogprobs", -float("inf")),
        ("finishMessage", "\0"),
        ("finishMessage", "\ud800"),
        ("thoughtSignature", "\0"),
    ],
    ids=lambda value: value if isinstance(value, str) and len(value) < 20 else "bounded-value",
)
def test_nonfinite_control_and_thought_metadata_never_produce_a_result(field, value):
    value = envelope({field: value})
    actual = parse_generate_response(json.dumps(value).encode("utf-8"))
    assert actual.code in {"provider_parts_invalid", "provider_json_invalid"}
    assert actual.result is None


@pytest.mark.parametrize("location", ["response", "candidate", "part", "food"])
def test_new_unknown_fields_remain_forbidden_in_each_layer(location):
    value = envelope(AUXILIARY)
    if location == "response":
        value["unexpected"] = 1
    elif location == "candidate":
        value["candidates"][0]["unexpected"] = 1
    elif location == "part":
        value["candidates"][0]["content"]["parts"][0]["unexpected"] = 1
    else:
        food = copy.deepcopy(FOOD) | {"thoughtSignature": AUXILIARY["thoughtSignature"]}
        value["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(food)
    actual = parse(value)
    assert actual.result is None
    assert actual.code == (
        "provider_parts_invalid" if location == "part" else "provider_result_invalid"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "thought",
        "functionCall",
        "functionResponse",
        "toolCall",
        "toolResponse",
        "inlineData",
        "fileData",
        "executableCode",
        "codeExecutionResult",
        "split",
        "safety",
        "ratings",
        "truncated",
        "usage",
        "no_food",
    ],
)
def test_auxiliary_metadata_cannot_bypass_existing_refusals(mutation):
    bare, decorated = envelope(), envelope(AUXILIARY)
    for value in (bare, decorated):
        candidate = value["candidates"][0]
        if mutation == "safety":
            candidate["finishReason"] = "SAFETY"
        elif mutation == "ratings":
            candidate["safetyRatings"] = [{"blocked": True}]
        elif mutation == "truncated":
            candidate["finishReason"] = "MAX_TOKENS"
        elif mutation == "usage":
            value["usageMetadata"]["totalTokenCount"] += 1
        elif mutation == "split":
            candidate["content"]["parts"].append({"text": "{}"})
        elif mutation == "no_food":
            candidate["content"]["parts"][0]["text"] = '{"items":[],"notes":[]}'
        else:
            candidate["content"]["parts"][0][mutation] = True if mutation == "thought" else {}
    assert parse(bare) == parse(decorated)
    assert parse(decorated).result is None and parse(decorated).code != "ok"


def test_auxiliary_token_count_does_not_replace_missing_usage():
    bare, decorated = envelope(), envelope(AUXILIARY | {"tokenCount": 0})
    for value in (bare, decorated):
        del value["usageMetadata"]
    assert parse(bare) == parse(decorated)
    actual = parse(decorated)
    assert actual.code == "ok" and actual.input_tokens is None
    assert actual.output_tokens is None and actual.total_tokens is None
