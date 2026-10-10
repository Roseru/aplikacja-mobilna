"""Authenticated, stateless ration cursors; legacy UUIDs have finite DB retention."""

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text

from calorie_app.modules.catalog.validation import canonical_json

PAGE_TTL = timedelta(minutes=60)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_INT = 2147483647


class InvalidPageToken(ValueError):
    pass


class CursorNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class PageCursor:
    package_id: UUID
    release: int
    after_id: UUID
    after_revision: int
    limit: int
    expires_at: datetime


def database_now(session) -> datetime:
    return session.scalar(select(func.clock_timestamp())).astimezone(UTC)


def prune_legacy_tokens(session) -> int:
    """A restricted definer function deletes only expired rows, at most 1000/call."""
    return session.scalar(text("SELECT app.prune_ration_page_tokens()"))


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise InvalidPageToken
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(raw) != value:
        raise InvalidPageToken
    return raw


def _key(secret) -> bytes:
    if secret is None:
        raise CursorNotConfigured
    return bytes.fromhex(secret.get_secret_value())


def encode_cursor(cursor: PageCursor, secret) -> str:
    # Integer arithmetic preserves the original expiry down to a microsecond.
    delta = cursor.expires_at.astimezone(UTC) - EPOCH
    expires = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    payload = _encode(
        canonical_json(
            {
                "v": 1,
                "p": str(cursor.package_id),
                "r": cursor.release,
                "a": str(cursor.after_id),
                "j": cursor.after_revision,
                "l": cursor.limit,
                "e": expires,
            }
        )
    )
    message = "rp1." + payload
    signature = hmac.digest(_key(secret), message.encode("ascii"), hashlib.sha256)
    return message + "." + _encode(signature)


def _uuid(value) -> UUID:
    if not isinstance(value, str):
        raise InvalidPageToken
    parsed = UUID(value)
    if str(parsed) != value:
        raise InvalidPageToken
    return parsed


def _integer(value, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise InvalidPageToken
    return value


def decode_cursor(token: str, secret) -> PageCursor:
    try:
        if len(token) > 1024:
            raise InvalidPageToken
        prefix, payload, signature = token.split(".")
        if prefix != "rp1":
            raise InvalidPageToken
        signed = (prefix + "." + payload).encode("ascii")
        signature_bytes = _decode(signature)
        if len(signature_bytes) != 32 or not hmac.compare_digest(
            signature_bytes, hmac.digest(_key(secret), signed, hashlib.sha256)
        ):
            raise InvalidPageToken
        # Authenticate the exact encoded bytes before constructing a JSON object.
        raw = _decode(payload)
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "p", "r", "a", "j", "l", "e"}
            or type(value["v"]) is not int
            or value["v"] != 1
            or canonical_json(value) != raw
        ):
            raise InvalidPageToken
        expiry = _integer(value["e"], 253402300799999999)
        return PageCursor(
            package_id=_uuid(value["p"]),
            release=_integer(value["r"], MAX_INT),
            after_id=_uuid(value["a"]),
            after_revision=_integer(value["j"], MAX_INT),
            limit=_integer(value["l"], 500),
            expires_at=EPOCH + timedelta(microseconds=expiry),
        )
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise InvalidPageToken from None
