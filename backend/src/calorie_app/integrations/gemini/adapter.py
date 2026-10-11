"""One synchronous REST request; only the fenced runner may schedule retries."""

import base64
import json
import re
from decimal import ROUND_CEILING, Decimal
from urllib.parse import urlsplit

import httpx

from calorie_app.integrations.gemini.protocol import (
    ProviderOutcome,
    parse_count_response,
    parse_generate_response,
)
from calorie_app.modules.ai.prompts import (
    MODEL,
    OUTPUT_TOKEN_LIMIT,
    PROMPT_VERSION,
    REST_PROFILE_VERSION,
    SCHEMA_VERSION,
    provider_schema,
    system_prompt,
)
from calorie_app.modules.ai.result import (
    MAX_PROVIDER_BYTES,
    ProviderResultError,
    parse_bounded_json,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 8 * 1024 * 1024
HOST = "generativelanguage.googleapis.com"


def build_generate_request(image: bytes) -> dict:
    if not isinstance(image, bytes) or not 1 <= len(image) <= MAX_IMAGE_BYTES:
        raise ProviderResultError("provider_response_size")
    if not image.startswith(b"\xff\xd8\xff"):
        raise ProviderResultError("provider_result_invalid")
    return {
        "model": "models/" + MODEL,
        "systemInstruction": {"parts": [{"text": system_prompt()}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64.b64encode(image).decode("ascii"),
                        }
                    },
                    {"text": "Propose the visible food and estimated quantities for human review."},
                ],
            }
        ],
        "serviceTier": "standard",
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": OUTPUT_TOKEN_LIMIT,
            "thinkingConfig": {"thinkingLevel": "MINIMAL", "includeThoughts": False},
            "responseFormat": {
                "text": {"mimeType": "APPLICATION_JSON", "schema": provider_schema()}
            },
        },
    }


def _endpoint(config: dict, call_kind: str) -> tuple[str, bool]:
    if call_kind not in ("countTokens", "generateContent"):
        raise ProviderResultError("provider_unavailable")
    for key, expected in (
        ("model", MODEL),
        ("model_id", MODEL),
        ("prompt_version", PROMPT_VERSION),
        ("schema_version", SCHEMA_VERSION),
        ("rest_profile_version", REST_PROFILE_VERSION),
    ):
        if key in config and config[key] != expected:
            raise ProviderResultError("provider_unavailable")
    base = f"https://{HOST}"
    fixture = "_test_base_url" in config
    if fixture:
        if config.get("environment") != "test" or config.get("test_fixture_adapter") is not True:
            raise ProviderResultError("provider_unavailable")
        base = config["_test_base_url"]
        if not isinstance(base, str):
            raise ProviderResultError("provider_unavailable")
        parsed = urlsplit(base)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not parsed.port
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderResultError("provider_unavailable")
        if base != f"http://127.0.0.1:{parsed.port}":
            raise ProviderResultError("provider_unavailable")
    elif config.get("live_authorized") is not True:
        raise ProviderResultError("provider_unavailable")
    return f"{base}/v1beta/models/{MODEL}:{call_kind}", fixture


def _retry_delay(raw: dict, header: str | None) -> int | None:
    delays = []
    if isinstance(header, str) and re.fullmatch(r"[0-9]{1,3}", header):
        delays.append(int(header))
    for detail in raw.get("details", []):
        if (
            isinstance(detail, dict)
            and detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo"
        ):
            duration = detail.get("retryDelay")
            if isinstance(duration, str) and re.fullmatch(
                r"[0-9]{1,3}(?:\.[0-9]{1,9})?s", duration
            ):
                delays.append(int(Decimal(duration[:-1]).to_integral_value(rounding=ROUND_CEILING)))
    return max(delays) if delays and max(delays) <= 120 else None


def classify_quota(raw: bytes, config: dict, retry_after: str | None = None) -> ProviderOutcome:
    """Interval comes from O3-confirmed exact machine IDs, never descriptions.

    Public docs do not guarantee Gemini quota IDs for every project/model. The
    default mapping is empty and every unrecognized 429 is terminal.
    """
    unknown = ProviderOutcome("ai_quota_exhausted", retry_kind="unknown")
    try:
        value = parse_bounded_json(raw)
        error = value.get("error")
        if (
            not isinstance(error, dict)
            or error.get("code") != 429
            or type(error.get("code")) is not int
            or error.get("status") != "RESOURCE_EXHAUSTED"
        ):
            return unknown
        details = error.get("details", [])
        if not isinstance(details, list) or not 1 <= len(details) <= 10:
            return unknown
        windows = config.get("quota_windows", {})
        if not isinstance(windows, dict) or len(windows) > 20:
            return unknown
        intervals = []
        for detail in details:
            if not isinstance(detail, dict):
                return unknown
            if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                continue
            if detail.get("@type") != "type.googleapis.com/google.rpc.QuotaFailure":
                return unknown
            violations = detail.get("violations")
            if not isinstance(violations, list) or not 1 <= len(violations) <= 10:
                return unknown
            for violation in violations:
                if not isinstance(violation, dict):
                    return unknown
                metric, quota_id = violation.get("quotaMetric"), violation.get("quotaId")
                dims = violation.get("quotaDimensions", {})
                if (
                    not isinstance(metric, str)
                    or not metric.startswith(HOST + "/")
                    or not isinstance(quota_id, str)
                    or len(quota_id) > 200
                    or violation.get("apiService", HOST) != HOST
                    or not isinstance(dims, dict)
                    or dims.get("model") != MODEL
                ):
                    return unknown
                interval = windows.get(quota_id)
                if interval not in ("minute", "daily"):
                    return unknown
                intervals.append(interval)
        if not intervals:
            return unknown
        if "daily" in intervals:
            return ProviderOutcome("ai_quota_exhausted", retry_kind="daily")
        delay = _retry_delay(error, retry_after)
        if delay is None:
            return unknown
        return ProviderOutcome(
            "provider_rate_limited", retry_kind="minute", retry_after_seconds=delay
        )
    except (ProviderResultError, ValueError, TypeError):
        return unknown


def rest_call(
    call_kind: str, image: bytes, config: dict, timeout_seconds: float
) -> ProviderOutcome:
    try:
        endpoint, fixture = _endpoint(config, call_kind)
        key = config.get("api_key", "fixture-key" if fixture else None)
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 4096
            or re.fullmatch(r"[!-~]+", key) is None
        ):
            return ProviderOutcome("provider_unavailable", sent=False)
        request = build_generate_request(image)
        if call_kind == "countTokens":
            request = {"generateContentRequest": request}
        body = json.dumps(
            request, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            return ProviderOutcome("provider_response_size", sent=False)
    except (ProviderResultError, ValueError, TypeError):
        return ProviderOutcome("provider_unavailable", sent=False)
    try:
        with httpx.Client(
            timeout=timeout_seconds,
            trust_env=False,
            follow_redirects=False,
            transport=httpx.HTTPTransport(verify=True, trust_env=False, retries=0),
        ) as client:
            with client.stream(
                "POST",
                endpoint,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": key,
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code >= 500:
                    return ProviderOutcome("provider_result_unknown")
                if response.headers.get("content-encoding", "identity") != "identity":
                    return ProviderOutcome("provider_response_size")
                raw = bytearray()
                for chunk in response.iter_raw(chunk_size=16384):
                    if len(raw) + len(chunk) > MAX_PROVIDER_BYTES:
                        return ProviderOutcome("provider_response_size")
                    raw.extend(chunk)
                if response.status_code == 429:
                    return classify_quota(bytes(raw), config, response.headers.get("retry-after"))
                if response.status_code != 200:
                    return ProviderOutcome("provider_unavailable")
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip()
                    != "application/json"
                ):
                    return ProviderOutcome("provider_json_invalid")
                parser = (
                    parse_count_response if call_kind == "countTokens" else parse_generate_response
                )
                return parser(bytes(raw))
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return ProviderOutcome("provider_unavailable", sent=False)
    except (httpx.HTTPError, OSError, ValueError):
        return ProviderOutcome("provider_result_unknown")
