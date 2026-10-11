"""Small validated process envelope. No raw provider response crosses this boundary."""

import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, ValidationError

from calorie_app.modules.ai.prompts import INPUT_TOKEN_LIMIT, OUTPUT_TOKEN_LIMIT
from calorie_app.modules.ai.result import (
    ProviderFoodResult,
    ProviderResultError,
    parse_bounded_json,
    parse_food_result,
)
from calorie_app.modules.catalog.schemas import CatalogDTO

ProviderCode = Literal[
    "ok",
    "provider_unavailable",
    "provider_result_unknown",
    "provider_response_size",
    "provider_json_invalid",
    "provider_json_depth",
    "provider_json_duplicate",
    "provider_result_invalid",
    "provider_no_food",
    "provider_no_candidates",
    "provider_safety_block",
    "provider_result_truncated",
    "provider_parts_invalid",
    "provider_usage_invalid",
    "provider_input_too_large",
    "ai_quota_exhausted",
    "provider_rate_limited",
]
RetryKind = Literal["minute", "daily", "unknown"]
Token = Annotated[StrictInt, Field(ge=0, le=INPUT_TOKEN_LIMIT + OUTPUT_TOKEN_LIMIT)]
ModelVersion = Annotated[
    str, Field(strict=True, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/-]+$")
]


class _OutcomeDTO(CatalogDTO):
    code: ProviderCode
    result: ProviderFoodResult | None
    input_tokens: Token | None
    output_tokens: Token | None
    thoughts_tokens: Token | None
    total_tokens: Token | None
    model_version: ModelVersion | None
    retry_kind: RetryKind | None
    retry_after_seconds: Annotated[StrictInt, Field(ge=0, le=120)] | None
    token_count: Annotated[StrictInt, Field(ge=0, le=INPUT_TOKEN_LIMIT)] | None
    sent: StrictBool


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    code: ProviderCode
    result: ProviderFoodResult | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thoughts_tokens: int | None = None
    total_tokens: int | None = None
    model_version: str | None = None
    retry_kind: RetryKind | None = None
    retry_after_seconds: int | None = None
    token_count: int | None = None
    sent: bool = True

    def to_wire(self) -> dict:
        return _OutcomeDTO(
            **{key: getattr(self, key) for key in self.__dataclass_fields__}
        ).model_dump(mode="json")

    @classmethod
    def from_wire(cls, value: dict | bytes) -> "ProviderOutcome":
        if isinstance(value, bytes):
            value = parse_bounded_json(value)
        dto = _OutcomeDTO.model_validate(value)
        result = cls(**{key: getattr(dto, key) for key in cls.__dataclass_fields__})
        usage = (
            result.input_tokens,
            result.output_tokens,
            result.thoughts_tokens,
            result.total_tokens,
        )
        if any(item is not None for item in usage) and not _valid_usage(*usage):
            raise ProviderResultError("provider_usage_invalid")
        if result.code != "ok" and (result.result is not None or result.token_count is not None):
            raise ProviderResultError("provider_result_invalid")
        if result.code == "ok" and ((result.result is None) == (result.token_count is None)):
            raise ProviderResultError("provider_result_invalid")
        if (result.retry_kind == "minute") != (result.code == "provider_rate_limited"):
            raise ProviderResultError("provider_result_invalid")
        if result.retry_kind in ("daily", "unknown") and result.code != "ai_quota_exhausted":
            raise ProviderResultError("provider_result_invalid")
        return result


def _valid_usage(input_tokens, output_tokens, thoughts_tokens, total_tokens) -> bool:
    if any(
        type(value) is not int or value < 0
        for value in (input_tokens, output_tokens, thoughts_tokens, total_tokens)
    ):
        return False
    return (
        input_tokens <= INPUT_TOKEN_LIMIT
        and output_tokens + thoughts_tokens <= OUTPUT_TOKEN_LIMIT
        and total_tokens == input_tokens + output_tokens + thoughts_tokens
    )


def _metadata(value: dict) -> dict:
    version = value.get("modelVersion")
    if version is not None and (
        not isinstance(version, str) or re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", version) is None
    ):
        raise ProviderResultError("provider_result_invalid")
    result = {"model_version": version}
    usage = value.get("usageMetadata")
    if usage is None:
        return result  # No trusted usage: the worker retains the full reservation.
    if not isinstance(usage, dict):
        raise ProviderResultError("provider_usage_invalid")
    input_tokens = usage.get("promptTokenCount")
    output_tokens = usage.get("candidatesTokenCount")
    thoughts_tokens = usage.get("thoughtsTokenCount", 0)
    total_tokens = usage.get("totalTokenCount")
    if not _valid_usage(input_tokens, output_tokens, thoughts_tokens, total_tokens):
        raise ProviderResultError("provider_usage_invalid")
    if any(
        usage.get(key, 0) != 0 or type(usage.get(key, 0)) is not int
        for key in ("cachedContentTokenCount", "toolUsePromptTokenCount")
    ):
        raise ProviderResultError("provider_usage_invalid")
    result.update(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thoughts_tokens=thoughts_tokens,
        total_tokens=total_tokens,
    )
    return result


_SAFETY = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}


def parse_generate_response(raw: bytes) -> ProviderOutcome:
    metadata = {}
    try:
        value = parse_bounded_json(raw)
        if set(value) - {
            "candidates",
            "promptFeedback",
            "usageMetadata",
            "modelVersion",
            "responseId",
        }:
            raise ProviderResultError("provider_result_invalid")
        metadata = _metadata(value)
        feedback = value.get("promptFeedback", {})
        if not isinstance(feedback, dict):
            raise ProviderResultError("provider_result_invalid")
        block = feedback.get("blockReason")
        if block in _SAFETY:
            raise ProviderResultError("provider_safety_block")
        if block not in (None, "BLOCK_REASON_UNSPECIFIED"):
            raise ProviderResultError("provider_result_invalid")
        candidates = value.get("candidates", [])
        if candidates == []:
            raise ProviderResultError("provider_no_candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ProviderResultError("provider_result_invalid")
        candidate = candidates[0]
        if not isinstance(candidate, dict) or set(candidate) - {
            "content",
            "finishReason",
            "index",
            "safetyRatings",
        }:
            raise ProviderResultError("provider_result_invalid")
        reason = candidate.get("finishReason")
        if reason == "MAX_TOKENS":
            raise ProviderResultError("provider_result_truncated")
        if reason in _SAFETY:
            raise ProviderResultError("provider_safety_block")
        if reason != "STOP":
            raise ProviderResultError("provider_result_invalid")
        ratings = candidate.get("safetyRatings", [])
        if not isinstance(ratings, list) or len(ratings) > 20:
            raise ProviderResultError("provider_result_invalid")
        for rating in ratings:
            if not isinstance(rating, dict):
                raise ProviderResultError("provider_result_invalid")
            if rating.get("blocked") is True:
                raise ProviderResultError("provider_safety_block")
        content = candidate.get("content")
        if not isinstance(content, dict) or set(content) - {"parts", "role"}:
            raise ProviderResultError("provider_parts_invalid")
        if content.get("role", "model") != "model":
            raise ProviderResultError("provider_parts_invalid")
        parts = content.get("parts")
        if not isinstance(parts, list) or len(parts) != 1:
            raise ProviderResultError("provider_parts_invalid")
        part = parts[0]
        if not isinstance(part, dict) or set(part) != {"text"} or not isinstance(part["text"], str):
            raise ProviderResultError("provider_parts_invalid")
        result = parse_food_result(part["text"].encode("utf-8", errors="strict"))
        return ProviderOutcome("ok", result=result, **metadata)
    except ProviderResultError as error:
        return ProviderOutcome(error.code, **metadata)
    except (ValueError, TypeError, UnicodeError, ValidationError):
        return ProviderOutcome("provider_result_invalid", **metadata)


def parse_count_response(raw: bytes) -> ProviderOutcome:
    try:
        value = parse_bounded_json(raw)
        if set(value) - {"totalTokens", "cachedContentTokenCount", "promptTokensDetails"}:
            raise ProviderResultError("provider_result_invalid")
        count = value.get("totalTokens")
        if type(count) is not int or count < 0:
            raise ProviderResultError("provider_result_invalid")
        if count > INPUT_TOKEN_LIMIT:
            raise ProviderResultError("provider_input_too_large")
        cached = value.get("cachedContentTokenCount", 0)
        if type(cached) is not int or cached != 0:
            raise ProviderResultError("provider_result_invalid")
        return ProviderOutcome("ok", token_count=count)
    except ProviderResultError as error:
        return ProviderOutcome(error.code)


def encode_outcome(outcome: ProviderOutcome) -> bytes:
    return json.dumps(
        outcome.to_wire(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
