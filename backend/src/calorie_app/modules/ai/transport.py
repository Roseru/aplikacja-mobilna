"""Bounded, memory-only multipart transport; never invokes framework file spooling."""

import json
import math
import re

from starlette.requests import ClientDisconnect, Request

from calorie_app.core.errors import DomainError
from calorie_app.core.wire import validate_json_strings

MAX_BODY_BYTES = 6 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024
MAX_HEADER_BYTES = 4096
MAX_HEADER_COUNT = 8
MAX_JSON_DEPTH = 20
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_BOUNDARY = re.compile(r"^[0-9A-Za-z'()+_,./:=? -]{1,70}$")


def _invalid() -> DomainError:
    return DomainError(422, "invalid_request")


async def read_body(request: Request, maximum: int = MAX_BODY_BYTES) -> bytes:
    """Count actual stream bytes, independent of declared Content-Length."""
    if not 0 < maximum <= MAX_BODY_BYTES:
        raise ValueError("invalid_body_limit")
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(chunk) > maximum - len(body):
                raise DomainError(413, "request_too_large")
            body.extend(chunk)
    except ClientDisconnect:
        raise _invalid() from None
    return bytes(body)


def _parameters(source: str) -> tuple[str, dict[str, str]]:
    """Small strict MIME parameter grammar, with bounded caller input."""
    if any(ord(char) < 32 or ord(char) == 127 for char in source):
        raise ValueError
    position = source.find(";")
    if position == -1:
        return source.strip().lower(), {}
    head, params = source[:position].strip().lower(), {}
    while position < len(source):
        if source[position] != ";":
            raise ValueError
        position += 1
        while position < len(source) and source[position] == " ":
            position += 1
        match = re.match(r"([!#$%&'*+.^_`|~0-9A-Za-z-]+)\s*=\s*", source[position:])
        if match is None:
            raise ValueError
        name = match[1].lower()
        position += match.end()
        if name in params or position == len(source):
            raise ValueError
        if source[position] == '"':
            position += 1
            value = []
            while position < len(source) and source[position] != '"':
                char = source[position]
                if char == "\\":
                    position += 1
                    if position == len(source):
                        raise ValueError
                    char = source[position]
                value.append(char)
                position += 1
            if position == len(source):
                raise ValueError
            position += 1
            params[name] = "".join(value)
        else:
            end = source.find(";", position)
            end = len(source) if end == -1 else end
            value = source[position:end].strip()
            if not _TOKEN.fullmatch(value):
                raise ValueError
            params[name] = value
            position = end
        while position < len(source) and source[position] == " ":
            position += 1
    return head, params


def _headers(raw: bytes) -> tuple[str, dict[str, str]]:
    lines = raw.split(b"\r\n")
    if len(raw) > MAX_HEADER_BYTES or len(lines) > MAX_HEADER_COUNT:
        raise DomainError(413, "request_too_large")
    headers = {}
    for line in lines:
        if len(line) > 1024 or b":" not in line:
            raise ValueError
        name, value = line.split(b":", 1)
        name = name.decode("ascii").lower()
        # Filename is ignored, including its encoding and any apparent path.
        value = value.decode("latin1").strip(" ")
        if not _TOKEN.fullmatch(name) or name in headers:
            raise ValueError
        if name not in {"content-disposition", "content-type"}:
            raise ValueError
        headers[name] = value
    disposition, params = _parameters(headers.get("content-disposition", ""))
    if disposition != "form-data" or set(params) - {"name", "filename"}:
        raise ValueError
    name = params.get("name")
    if name not in {"metadata", "image"}:
        raise ValueError
    media, media_params = _parameters(headers.get("content-type", ""))
    if name == "metadata":
        if media != "application/json" or set(media_params) - {"charset"}:
            raise ValueError
        if media_params.get("charset", "utf-8").lower() != "utf-8":
            raise ValueError
    elif media and not re.fullmatch(
        r"[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+", media
    ):
        raise ValueError
    return name, headers


def _metadata(raw: bytes) -> dict:
    source = raw.decode("utf-8", errors="strict")
    quoted = escaped = False
    depth = 0
    for char in source:
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
            if depth > MAX_JSON_DEPTH:
                raise ValueError
        elif char in "]}":
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def constant(_):
        raise ValueError

    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)

    value = json.loads(source, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError
    validate_json_strings(value)
    finite(value)
    return value


def parse_multipart(body: bytes, content_type: str) -> tuple[dict, bytes]:
    """Return the two parts in memory; consent/domain validation belongs to caller."""
    if len(body) > MAX_BODY_BYTES:
        raise DomainError(413, "request_too_large")
    try:
        if len(content_type) > 512:
            raise ValueError
        media, params = _parameters(content_type)
        boundary = params.get("boundary", "")
        if media != "multipart/form-data" or set(params) != {"boundary"}:
            raise ValueError
        if not _BOUNDARY.fullmatch(boundary) or boundary.endswith(" "):
            raise ValueError
        delimiter = b"--" + boundary.encode("ascii")
        if not body.startswith(delimiter + b"\r\n"):
            raise ValueError
        position = len(delimiter) + 2
        parts = {}
        while True:
            if len(parts) == 2:
                raise ValueError
            header_end = body.find(b"\r\n\r\n", position, position + MAX_HEADER_BYTES + 4)
            if header_end == -1:
                raise ValueError
            name, _ = _headers(body[position:header_end])
            if name in parts:
                raise ValueError
            position = header_end + 4
            marker = b"\r\n" + delimiter
            end = body.find(marker, position)
            # A boundary-prefix inside payload is legal unless followed by the
            # exact MIME delimiter suffix. Scan monotonically within 6 MiB.
            while end != -1 and body[end + len(marker) : end + len(marker) + 2] not in {
                b"\r\n",
                b"--",
            }:
                end = body.find(marker, end + len(marker))
            if end == -1:
                raise ValueError
            size = end - position
            maximum = MAX_METADATA_BYTES if name == "metadata" else MAX_IMAGE_BYTES
            if size > maximum:
                raise DomainError(413, "request_too_large")
            if size == 0:
                raise ValueError
            parts[name] = body[position:end]
            position = end + len(marker)
            if body[position : position + 2] == b"--":
                if body[position + 2 :] not in {b"", b"\r\n"}:
                    raise ValueError
                break
            position += 2
        if set(parts) != {"metadata", "image"}:
            raise ValueError
        return _metadata(parts["metadata"]), parts["image"]
    except (ValueError, UnicodeError, RecursionError, IndexError):
        raise _invalid() from None
