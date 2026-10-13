"""A disposable process owns physical IO; hard timeout confirms its termination.

The worker must commit its permit and dispatch marker BEFORE execute. Neither
this module nor the child releases database permits or makes another attempt.
"""

import base64
import json
import logging
import math
import os
import subprocess
import sys
import time

from calorie_app.integrations.gemini.adapter import MAX_IMAGE_BYTES, rest_call
from calorie_app.integrations.gemini.mock import mock_call
from calorie_app.integrations.gemini.protocol import ProviderOutcome, encode_outcome
from calorie_app.modules.ai.result import ProviderResultError, parse_bounded_json

MAX_PROCESS_REQUEST_BYTES = 8 * 1024 * 1024


def execute(
    provider: str, call_kind: str, image: bytes, config: dict, timeout_seconds: float
) -> ProviderOutcome:
    started = time.monotonic()
    if (
        provider not in ("mock", "gemini")
        or call_kind not in ("countTokens", "generateContent")
        or not isinstance(config, dict)
        or not (
            isinstance(image, bytes)
            and 1 <= len(image) <= MAX_IMAGE_BYTES
            and config.get("purpose", "food_photo") == "food_photo"
            or isinstance(image, dict)
            and config.get("purpose") == "energy_adjustment"
        )
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 45
    ):
        return ProviderOutcome("provider_unavailable", sent=False)
    try:
        body = json.dumps(
            {
                "provider": provider,
                "call_kind": call_kind,
                "image": base64.b64encode(image).decode("ascii")
                if isinstance(image, bytes)
                else None,
                **({"aggregates": image} if isinstance(image, dict) else {}),
                "config": config,
                "timeout_seconds": timeout_seconds,
                "deadline_monotonic": started + timeout_seconds,
            },
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(body) > MAX_PROCESS_REQUEST_BYTES:
            return ProviderOutcome("provider_response_size", sent=False)
        # Preserve import/runtime paths for source and installed wheel use; do
        # not give the child unrelated DB/JWT/cloud credentials via environment.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH"}
        }
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [sys.executable, "-m", "calorie_app.integrations.gemini.process"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, ValueError, TypeError):
        return ProviderOutcome("provider_unavailable", sent=False)
    try:
        remaining = max(0, timeout_seconds - (time.monotonic() - started))
        output, _ = process.communicate(body, timeout=remaining)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        process.wait()
        return ProviderOutcome("provider_result_unknown")
    except BaseException:
        process.kill()
        process.communicate()
        process.wait()
        raise
    if process.returncode != 0:
        return ProviderOutcome("provider_result_unknown")
    try:
        return ProviderOutcome.from_wire(output)
    except (ProviderResultError, ValueError, TypeError):
        return ProviderOutcome("provider_result_unknown")


def run_request(raw: bytes) -> bytes:
    """Called only after the stdlib bootstrap arms its independent watchdog."""
    logging.disable(logging.CRITICAL)
    try:
        request = parse_bounded_json(raw, max_bytes=MAX_PROCESS_REQUEST_BYTES)
        if set(request) - {"aggregates"} != {
            "provider",
            "call_kind",
            "image",
            "config",
            "timeout_seconds",
            "deadline_monotonic",
        }:
            raise ValueError("invalid process request")
        remaining = request["deadline_monotonic"] - time.monotonic()
        if remaining <= 0:
            return encode_outcome(ProviderOutcome("provider_result_unknown"))
        if request["config"].get("purpose") == "energy_adjustment":
            from calorie_app.integrations.gemini.energy import validate_aggregates

            if request["image"] is not None or "aggregates" not in request:
                raise ValueError("invalid typed process payload")
            image = validate_aggregates(request["aggregates"])
        else:
            if "aggregates" in request:
                raise ValueError("unexpected aggregate payload")
            image = base64.b64decode(request["image"], validate=True)
            if not 1 <= len(image) <= MAX_IMAGE_BYTES:
                raise ValueError("invalid process image")
        if request["provider"] == "mock":
            outcome = mock_call(request["call_kind"], request["config"])
        elif request["provider"] == "gemini":
            outcome = rest_call(request["call_kind"], image, request["config"], remaining)
        else:
            raise ValueError("invalid process provider")
    except Exception:
        # An unexpected crash might occur after an outbound call. Never label
        # that as a proven pre-send failure eligible for automatic repetition.
        outcome = ProviderOutcome("provider_result_unknown")
    output = encode_outcome(outcome)
    if len(output) > 1024 * 1024:
        output = encode_outcome(ProviderOutcome("provider_response_size"))
    return output
