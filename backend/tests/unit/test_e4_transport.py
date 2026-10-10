import asyncio
import json

import pytest

from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.transport import PAYLOAD_BYTES, REQUEST_BYTES, parse_push, read_push


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":"\xff"}',
        b"[" * 65 + b"]" * 65,
        b"{}{}",
        b"{",
        b"",
    ],
)
def test_strict_invalid(raw):
    with pytest.raises(SyncFailure) as caught:
        parse_push(raw)
    assert caught.value.status == 422


def test_request_actual_bytes_boundary():
    assert parse_push(b"{}" + b" " * (REQUEST_BYTES - 2)) == {}
    with pytest.raises(SyncFailure) as caught:
        parse_push(b"{}" + b" " * (REQUEST_BYTES - 1))
    assert caught.value.status == 413


def test_original_payload_limit_precedes_semantic_unicode_validation():
    raw = b'{"operations":[{"payload":"' + b"a" * PAYLOAD_BYTES + b'\\u0000"}]}'
    with pytest.raises(SyncFailure) as caught:
        parse_push(raw)
    assert caught.value.status == 413


@pytest.mark.parametrize("piece", [b" ", b"\\u0061", "ą".encode()])
def test_payload_original_span(piece):
    start, end = b'{"operations":[{"payload":"', b'"}]}'
    # Whitespace and escapes in a JSON string count as their original bytes.
    payload = piece * ((PAYLOAD_BYTES - 2) // len(piece))
    raw = start + payload + end
    parse_push(raw)
    with pytest.raises(SyncFailure) as caught:
        parse_push(start + payload + piece * 3 + end)
    assert caught.value.status == 413


class Request:
    headers = {"content-type": "application/json", "content-length": "1"}

    def __init__(self, raw, encoding="identity"):
        self.raw = raw
        self.headers = self.headers | {"content-encoding": encoding}

    async def stream(self):
        for index in range(0, len(self.raw), 1000):
            yield self.raw[index : index + 1000]


def test_chunked_does_not_trust_content_length():
    assert asyncio.run(read_push(Request(b"{}"))) == {}
    with pytest.raises(SyncFailure) as caught:
        asyncio.run(read_push(Request(b" " * (REQUEST_BYTES + 1))))
    assert caught.value.status == 413


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate"])
def test_compression_explicit_rejection(encoding):
    with pytest.raises(SyncFailure) as caught:
        asyncio.run(read_push(Request(json.dumps({}).encode(), encoding)))
    assert caught.value.status == 422
