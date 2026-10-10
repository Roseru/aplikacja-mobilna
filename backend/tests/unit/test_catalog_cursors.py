"""Stateless cursor authentication, strict parsing and safe secret configuration."""

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from calorie_app.core.config import Settings
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.pagination import (
    CursorNotConfigured,
    InvalidPageToken,
    PageCursor,
    decode_cursor,
    encode_cursor,
)

SECRET = SecretStr("e2" * 32)


def cursor():
    return PageCursor(
        OFFICIAL_PACKAGE_ID, 9, uuid4(), 2, 1, datetime(2026, 10, 10, 12, 30, 0, 100001, tzinfo=UTC)
    )


def signed_raw(raw: bytes) -> str:
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    message = "rp1." + payload
    signature = hmac.digest(
        bytes.fromhex(SECRET.get_secret_value()), message.encode(), hashlib.sha256
    )
    return message + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def test_roundtrip_exact_metadata_and_expiry():
    value = cursor()
    token = encode_cursor(value, SECRET)
    assert decode_cursor(token, SECRET) == value
    assert len(token) < 1024
    assert encode_cursor(value, SECRET) == token
    assert encode_cursor(replace(value, release=10), SECRET) != token


@pytest.mark.parametrize(
    "token", ["", "rp1", "rp1..", "rp1.a.a", "rp1.a.a.a", "rp1.?.a", "rp1.a.!", "x" * 4096]
)
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(InvalidPageToken):
        decode_cursor(token, SECRET)


def test_wrong_key_and_modified_payload_are_rejected():
    token = encode_cursor(cursor(), SECRET)
    with pytest.raises(InvalidPageToken):
        decode_cursor(token, SecretStr("ab" * 32))
    prefix, payload, signature = token.split(".")
    value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    value["r"] += 1
    altered = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    with pytest.raises(InvalidPageToken):
        decode_cursor(prefix + "." + altered + "." + signature, SECRET)


@pytest.mark.parametrize(
    "field,value",
    [
        ("v", True),
        ("v", 2),
        ("r", 0),
        ("r", True),
        ("r", 2147483648),
        ("j", 0),
        ("l", 501),
        ("e", 0),
        ("e", 10**30),
        ("p", "broken"),
        ("a", "broken"),
    ],
)
def test_authenticated_invalid_claims_still_fail(field, value):
    token = encode_cursor(cursor(), SECRET)
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims[field] = value
    from calorie_app.modules.catalog.validation import canonical_json

    with pytest.raises(InvalidPageToken):
        decode_cursor(signed_raw(canonical_json(claims)), SECRET)


@pytest.mark.parametrize(
    "raw", [b"{}", b"[]", b"null", b'{"v":1,"v":1}', b"NaN", b'{"v":Infinity}']
)
def test_signed_noncanonical_or_incomplete_json_is_rejected(raw):
    with pytest.raises(InvalidPageToken):
        decode_cursor(signed_raw(raw), SECRET)


def test_missing_secret_does_not_generate_an_ephemeral_key():
    with pytest.raises(CursorNotConfigured):
        encode_cursor(cursor(), None)
    with pytest.raises(CursorNotConfigured):
        decode_cursor(encode_cursor(cursor(), SECRET), None)


@pytest.mark.parametrize("secret", ["", "aa", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_secret_configuration_is_strict_and_redacted(secret):
    with pytest.raises(ValidationError) as error:
        Settings(
            database_url="postgresql+psycopg://unused@localhost/unused",
            catalog_page_token_secret=secret,
        )
    assert "input_value=" not in str(error.value)


def test_secret_is_hidden_from_repr_and_model_json():
    settings = Settings(
        database_url="postgresql+psycopg://unused@localhost/unused",
        catalog_page_token_secret=SECRET,
    )
    assert SECRET.get_secret_value() not in repr(settings)
    assert SECRET.get_secret_value() not in settings.model_dump_json()
