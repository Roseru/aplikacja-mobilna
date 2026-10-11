"""Stdlib-only bootstrap: deadline survives a killed or disconnected worker.

The absolute host-monotonic deadline includes the parent's serialization,
spawn, pipe transfer and child imports. Arm the watchdog before importing
HTTPX/Pydantic/provider code; resettable socket timeouts are never its clock.
"""

import json
import math
import os
import sys
import threading
import time

MAX_PROCESS_REQUEST_BYTES = 8 * 1024 * 1024
DEADLINE_EXIT_CODE = 124


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("invalid process request")
        result[key] = value
    return result


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_PROCESS_REQUEST_BYTES + 1)
        if not raw or len(raw) > MAX_PROCESS_REQUEST_BYTES:
            return 2
        request = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs)
        deadline = request["deadline_monotonic"]
        duration = request["timeout_seconds"]
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or type(duration) not in (int, float)
            or not math.isfinite(duration)
            or not 0 < duration <= 45
        ):
            return 2
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return DEADLINE_EXIT_CODE
        if remaining > duration:
            return 2
    except (ValueError, TypeError, KeyError, RecursionError):
        return 2

    watchdog = threading.Timer(remaining, os._exit, args=(DEADLINE_EXIT_CODE,))
    watchdog.daemon = True
    watchdog.start()
    try:
        # Deliberately imported after watchdog.start(): provider import/startup
        # cannot add a fresh timeout window after the parent has disappeared.
        from calorie_app.integrations.gemini.transport import run_request

        output = run_request(raw)
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        return 0
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
