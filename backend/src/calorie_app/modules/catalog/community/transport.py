"""Bound streaming JSON before framework decoding of E6 online requests."""

import json
import re
from uuid import UUID, uuid4

from starlette.requests import Request

from calorie_app.core.errors import error_response

MAX_BODY = 1048576
MAX_DEPTH = 20


def protected_mutation(path, method):
    return method in {"POST", "PUT", "PATCH", "DELETE"} and (
        path.rstrip("/") in {"/api/v1/products", "/api/v1/products/matches"}
        or re.fullmatch(r"/api/v1/products/[^/]+/(vote|reports)/?", path) is not None
        or path.startswith("/api/v1/moderation/")
    )


def validate_body(raw):
    """Structural depth and duplicate keys are validated without echoing input."""
    value = raw.decode("utf-8", errors="strict")
    quoted = escaped = False
    depth = 0
    for char in value:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError
        elif char in "]}":
            depth -= 1

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    def constant(_):
        raise ValueError

    json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


class E6BodyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not protected_mutation(scope["path"], scope["method"]):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            request_id = str(UUID(headers.get(b"x-request-id", b"").decode("ascii")))
        except (ValueError, UnicodeError):
            request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def reject(status, code):
            response = error_response(
                Request(scope),
                status,
                code,
                "Niepoprawne dane żądania.",
                {"Cache-Control": "no-store", "X-Request-ID": request_id},
            )
            await response(scope, receive, send)

        if headers.get(b"content-encoding", b"identity").lower() != b"identity":
            await reject(422, "invalid_request")
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY:
                await reject(413, "request_too_large")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if scope["method"] == "DELETE":
            if body:
                await reject(422, "invalid_request")
                return
        else:
            if headers.get(b"content-type", b"").split(b";", 1)[0].lower() != b"application/json":
                await reject(422, "invalid_request")
                return
            try:
                validate_body(bytes(body))
            except (ValueError, UnicodeError, RecursionError):
                await reject(422, "invalid_request")
                return
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
