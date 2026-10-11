"""Signed product pages pin an immutable release and the authenticated context."""

import hashlib
import hmac
import json
from datetime import timedelta
from uuid import UUID

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import EPOCH, _decode, _encode, _key
from calorie_app.modules.catalog.validation import canonical_json


def encode_page(value: dict, secret) -> str:
    message = "pp1." + _encode(canonical_json(value))
    return message + "." + _encode(hmac.digest(_key(secret), message.encode(), hashlib.sha256))


def decode_page(token: str, secret, *, owner, generation, epoch, query, limit, now) -> dict:
    try:
        if len(token) > 4096:
            raise ValueError
        prefix, payload, signature = token.split(".")
        if prefix != "pp1":
            raise ValueError
        message = prefix + "." + payload
        if not hmac.compare_digest(
            _decode(signature), hmac.digest(_key(secret), message.encode(), hashlib.sha256)
        ):
            raise ValueError
        raw = _decode(payload)
        value = json.loads(raw)
        if set(value) != {
            "owner",
            "generation",
            "epoch",
            "query",
            "limit",
            "release",
            "after",
            "expiry",
        }:
            raise ValueError
        if canonical_json(value) != raw or value["owner"] != str(owner):
            raise ValueError
        if value["generation"] != generation or value["epoch"] != str(epoch):
            raise ValueError
        if value["query"] != query or value["limit"] != limit:
            raise ValueError
        if type(value["release"]) is not int or not 1 <= value["release"] <= 2147483647:
            raise ValueError
        if type(value["expiry"]) is not int or not 0 < value["expiry"] < 253402300800000000:
            raise ValueError
        if str(UUID(value["after"])) != value["after"]:
            raise ValueError
        expires = EPOCH + timedelta(microseconds=value["expiry"])
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        raise DomainError(422, "invalid_request") from None
    if now >= expires:
        raise DomainError(410, "page_expired")
    return value


def expiry_integer(value) -> int:
    delta = value - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
