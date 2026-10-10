"""Strict bounded JSON, including original UTF-8 payload spans."""

import json

from calorie_app.modules.sync.errors import SyncFailure

REQUEST_BYTES = 1_048_576
PAYLOAD_BYTES = 262_144
MAX_DEPTH = 64


def parse_push(raw: bytes) -> dict:
    if len(raw) > REQUEST_BYTES:
        raise SyncFailure(413, "request_too_large", {"limit_bytes": REQUEST_BYTES})
    try:
        source = raw.decode("utf-8", errors="strict")
        # Scan structural depth outside strings before recursive JSON decoding.
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
                if depth > MAX_DEPTH:
                    raise ValueError
            elif char in "]}":
                depth -= 1

        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        def constant(_):
            raise ValueError

        decoder = json.JSONDecoder(object_pairs_hook=object_pairs, parse_constant=constant)
        result = decoder.decode(source)
        # Parse positions with the same strict decoder. Capture payload values
        # at exactly operations[i].payload; whitespace after ':' counts too.
        whitespace = " \t\r\n"

        def skip(pos):
            while pos < len(source) and source[pos] in whitespace:
                pos += 1
            return pos

        def walk(pos, path):
            start = skip(pos)
            char = source[start]
            if char == "{":
                cursor = skip(start + 1)
                while source[cursor] != "}":
                    key, cursor = decoder.raw_decode(source, cursor)
                    cursor = skip(cursor)
                    if source[cursor] != ":":
                        raise ValueError
                    value_start = cursor + 1
                    cursor = walk(value_start, (*path, key))
                    if len(path) == 2 and path[0] == "operations" and key == "payload":
                        size = len(source[value_start:cursor].encode("utf-8"))
                        if size > PAYLOAD_BYTES:
                            raise SyncFailure(
                                413, "request_too_large", {"limit_bytes": PAYLOAD_BYTES}
                            )
                    cursor = skip(cursor)
                    if source[cursor] == "}":
                        break
                    if source[cursor] != ",":
                        raise ValueError
                    cursor = skip(cursor + 1)
                return cursor + 1
            if char == "[":
                cursor, index = skip(start + 1), 0
                while source[cursor] != "]":
                    cursor = skip(walk(cursor, (*path, index)))
                    index += 1
                    if source[cursor] == "]":
                        break
                    if source[cursor] != ",":
                        raise ValueError
                    cursor = skip(cursor + 1)
                return cursor + 1
            return decoder.raw_decode(source, start)[1]

        walk(0, ())
        return result
    except (ValueError, IndexError, RecursionError, UnicodeError):
        raise SyncFailure(422, "invalid_request") from None


async def read_push(request):
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise SyncFailure(422, "invalid_request")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise SyncFailure(422, "invalid_request")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > REQUEST_BYTES:
            raise SyncFailure(413, "request_too_large", {"limit_bytes": REQUEST_BYTES})
        body.extend(chunk)
    return parse_push(bytes(body))
