import asyncio
import builtins
import os
import tempfile

import pytest
from starlette.requests import ClientDisconnect

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai.transport import (
    MAX_BODY_BYTES,
    MAX_IMAGE_BYTES,
    MAX_METADATA_BYTES,
    parse_multipart,
    read_body,
)

CONTENT_TYPE = 'multipart/form-data; boundary="e7-boundary"'


def multipart(metadata=b'{"accepted":true}', image=b"image", order=("metadata", "image")):
    output = bytearray()
    for name in order:
        output.extend(b"--e7-boundary\r\n")
        output.extend(f'Content-Disposition: form-data; name="{name}"'.encode())
        if name == "image":
            output.extend(b'; filename="../../private.jpg"')
        output.extend(
            b"\r\nContent-Type: "
            + (b"application/json; charset=UTF-8" if name == "metadata" else b"image/jpeg")
            + b"\r\n\r\n"
        )
        output.extend(metadata if name == "metadata" else image)
        output.extend(b"\r\n")
    return bytes(output) + b"--e7-boundary--\r\n"


@pytest.mark.parametrize("order", [("metadata", "image"), ("image", "metadata")])
def test_two_parts_never_open_or_spool_files(monkeypatch, order):
    def forbidden(*args, **kwargs):
        raise AssertionError("parser_performed_file_io")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    for name in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, forbidden)
    # No codec/storage call occurs merely because image precedes false consent.
    metadata, image = parse_multipart(multipart(b'{"accepted":false}', order=order), CONTENT_TYPE)
    assert metadata == {"accepted": False}
    assert image == b"image"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"accepted":true,"accepted":false}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e999}',
        b'{"x":"\xff"}',
        b'{"x":"\\ud800"}',
        b'{"x":"\\u0000"}',
        b"[]",
        b"null",
        b"{}{}",
        b"",
        b"{",
        b"\xef\xbb\xbf{}",
        b'{"x":' + b"[" * 20 + b"0" + b"]" * 20 + b"}",
    ],
)
def test_strict_metadata(raw):
    with pytest.raises(DomainError) as error:
        parse_multipart(multipart(raw), CONTENT_TYPE)
    assert error.value.status == 422
    assert error.value.details == []
    assert str(error.value) == "invalid_request"


def test_depth_20_and_quoted_braces_and_unicode():
    raw = b'{"x":' + b"[" * 19 + b'"{{{{["' + b"]" * 19 + b"}"
    assert parse_multipart(multipart(raw), CONTENT_TYPE)[0]["x"]
    assert parse_multipart(multipart('{"x":"ą🍊"}'.encode()), CONTENT_TYPE)[0] == {"x": "ą🍊"}


@pytest.mark.parametrize(
    "content_type",
    [
        "",
        "application/json",
        "multipart/form-data",
        "multipart/form-data; boundary=",
        "multipart/form-data; boundary=e7-boundary; boundary=x",
        "multipart/form-data; boundary=e7-boundary; unknown=x",
        'multipart/form-data; boundary="space "',
        'multipart/form-data; boundary="' + "x" * 71 + '"',
        "multipart/form-data; boundary=e7-boundary\r\nBad: header",
    ],
)
def test_invalid_content_type(content_type):
    with pytest.raises(DomainError) as error:
        parse_multipart(multipart(), content_type)
    assert error.value.status == 422


@pytest.mark.parametrize(
    "order",
    [
        ("metadata",),
        ("image",),
        ("metadata", "metadata"),
        ("image", "image"),
        ("metadata", "image", "extra"),
        ("metadata", "extra"),
    ],
)
def test_exactly_two_unique_names(order):
    with pytest.raises(DomainError) as error:
        parse_multipart(multipart(order=order), CONTENT_TYPE)
    assert error.value.status == 422


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b"preamble\r\n" + b,
        lambda b: b + b"epilogue",
        lambda b: b[:-5],
        lambda b: b.replace(b"\r\n", b"\n"),
        lambda b: b.replace(
            b"Content-Type: image/jpeg", b"Content-Type: image/jpeg\r\nX-Secret: raw"
        ),
        lambda b: b.replace(
            b"Content-Type: image/jpeg", b"Content-Type: image/jpeg\r\nContent-Type: image/png"
        ),
        lambda b: b.replace(b'name="image"', b"name=\"image\"; filename*=UTF-8''secret"),
        lambda b: b.replace(
            b"application/json; charset=UTF-8", b"application/json; charset=latin1"
        ),
        lambda b: b.replace(b"Content-Type: image/jpeg", b" Content-Type: image/jpeg"),
    ],
)
def test_malformed_headers_framing_and_extra_data(change):
    with pytest.raises(DomainError) as error:
        parse_multipart(change(multipart()), CONTENT_TYPE)
    assert error.value.status == 422


def test_boundary_prefix_is_data_but_actual_boundary_is_delimiter():
    image = b"prefix\r\n--e7-boundary-with-other-suffix\r\nsuffix"
    assert parse_multipart(multipart(image=image), CONTENT_TYPE)[1] == image
    with pytest.raises(DomainError):
        parse_multipart(multipart(image=b"prefix\r\n--e7-boundary\r\nsuffix"), CONTENT_TYPE)


def test_exact_part_byte_limits():
    metadata = b"{}" + b" " * (MAX_METADATA_BYTES - 2)
    image = b"x" * MAX_IMAGE_BYTES
    parsed = parse_multipart(multipart(metadata, image), CONTENT_TYPE)
    assert parsed[0] == {} and len(parsed[1]) == MAX_IMAGE_BYTES
    for raw in (multipart(metadata + b" ", b"x"), multipart(b"{}", image + b"x")):
        with pytest.raises(DomainError) as error:
            parse_multipart(raw, CONTENT_TYPE)
        assert error.value.status == 413


class Request:
    headers = {"content-length": "1"}

    def __init__(self, pieces):
        self.pieces = pieces
        self.consumed = 0

    async def stream(self):
        for piece in self.pieces:
            self.consumed += 1
            if piece is None:
                raise ClientDisconnect
            yield piece


def test_actual_stream_size_and_early_stop():
    assert asyncio.run(read_body(Request([b"ab", b"cd"]), 4)) == b"abcd"
    request = Request([b"ab", b"cde", b"must-not-be-consumed"])
    with pytest.raises(DomainError) as error:
        asyncio.run(read_body(request, 4))
    assert error.value.status == 413 and request.consumed == 2
    with pytest.raises(DomainError) as error:
        asyncio.run(read_body(Request([b"a", None])))
    assert error.value.status == 422


def test_entire_body_limit_precedes_parser():
    with pytest.raises(DomainError) as error:
        parse_multipart(b"x" * (MAX_BODY_BYTES + 1), CONTENT_TYPE)
    assert error.value.status == 413
