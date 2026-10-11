"""Owner-bound community and moderation keyset tokens with fixed expiry."""

import hashlib
import hmac
import json
from datetime import timedelta
from uuid import UUID

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import EPOCH, InvalidPageToken, _decode, _encode, _key
from calorie_app.modules.catalog.validation import canonical_json

PREFIXES = {"community": "cp1", "reports": "mq1"}
FIELDS = {
    "owner",
    "generation",
    "epoch",
    "query",
    "filter",
    "sort",
    "limit",
    "after",
    "version",
    "expiry",
}


def encode_page(value: dict, secret, *, kind="community") -> str:
    message = PREFIXES[kind] + "." + _encode(canonical_json(value))
    return message + "." + _encode(hmac.digest(_key(secret), message.encode(), hashlib.sha256))


def decode_page(
    token,
    secret,
    *,
    owner,
    generation,
    epoch,
    query,
    filter=None,
    sort="id",
    limit=100,
    now,
    kind="community",
) -> dict:
    """Reject owner/parameter drift before inspecting catalog version in the read lock."""
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        prefix, payload, signature = token.split(".")
        if prefix != PREFIXES[kind]:
            raise ValueError
        message = prefix + "." + payload
        if not hmac.compare_digest(
            _decode(signature), hmac.digest(_key(secret), message.encode(), hashlib.sha256)
        ):
            raise ValueError
        raw = _decode(payload)
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != FIELDS or canonical_json(value) != raw:
            raise ValueError
        if (
            value["owner"] != str(owner)
            or type(value["generation"]) is not int
            or not 1 <= value["generation"] <= 2147483647
        ):
            raise ValueError
        if (
            not isinstance(value["epoch"], str)
            or str(UUID(value["epoch"])) != value["epoch"]
            or value["query"] != query
            or value["filter"] != filter
            or value["sort"] != sort
        ):
            raise ValueError
        if type(value["limit"]) is not int or value["limit"] != limit or not 1 <= limit <= 500:
            raise ValueError
        if type(value["version"]) is not int or not 1 <= value["version"] <= 9223372036854775807:
            raise ValueError
        if type(value["expiry"]) is not int or not 0 < value["expiry"] < 253402300800000000:
            raise ValueError
        if not isinstance(value["after"], str) or str(UUID(value["after"])) != value["after"]:
            raise ValueError
        expiry = EPOCH + timedelta(microseconds=value["expiry"])
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, InvalidPageToken):
        raise DomainError(422, "invalid_page_token") from None
    # Only a well-shaped, signed token belonging to this current account can
    # disclose reconciliation context. Restore takes precedence over expiry
    # and catalog version, consistently with E4/E5 and online E6 writes.
    if value["epoch"] != str(epoch):
        raise DomainError(
            409, "sync_epoch_changed", [{"field": "sync_epoch", "reason": str(epoch)}]
        )
    if value["generation"] != generation:
        raise DomainError(
            409,
            "account_generation_changed",
            [{"field": "account_generation", "reason": str(generation)}],
        )
    if now >= expiry:
        raise DomainError(410, "page_expired")
    return value
