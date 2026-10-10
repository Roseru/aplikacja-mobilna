"""Signed, context-bound tokens with separate checkpoint and pagination purposes."""

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from calorie_app.modules.sync.errors import SyncFailure

CHECKPOINT_TTL = timedelta(days=30)
SESSION_TTL = timedelta(minutes=60)
ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
MAX_POSITION = 9223372036854775807


def micros(value: datetime) -> int:
    delta = value.astimezone(UTC) - ORIGIN
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def timestamp(value: int) -> datetime:
    return ORIGIN + timedelta(microseconds=value)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(raw) != value:
        raise ValueError
    return raw


def _key(secret) -> bytes:
    if secret is None:
        raise SyncFailure(503, "service_unavailable")
    value = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    try:
        result = bytes.fromhex(value)
        if len(result) < 32:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise SyncFailure(503, "service_unavailable") from None


def sign_token(claims: dict, secret) -> str:
    message = "sync1." + _encode(_canonical(claims))
    return (
        message + "." + _encode(hmac.digest(_key(secret), message.encode("ascii"), hashlib.sha256))
    )


def context_claims(*, owner_id, generation, epoch, installation_id="calorie-app"):
    return {
        "protocol": 1,
        "owner": str(owner_id),
        "generation": generation,
        "epoch": str(epoch),
        "installation": installation_id,
    }


def read_token(
    token, secret, *, kind, owner_id, generation, epoch, installation_id="calorie-app"
) -> dict:
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise ValueError
        prefix, payload, signature = token.split(".")
        if prefix != "sync1":
            raise ValueError
        expected = hmac.digest(
            _key(secret), (prefix + "." + payload).encode("ascii"), hashlib.sha256
        )
        if not hmac.compare_digest(_decode(signature), expected):
            raise ValueError
        raw = _decode(payload)
        claims = json.loads(raw)
        if not isinstance(claims, dict) or _canonical(claims) != raw:
            raise ValueError
        context = context_claims(
            owner_id=owner_id, generation=generation, epoch=epoch, installation_id=installation_id
        )
        if claims.get("kind") != kind or any(
            type(claims.get(k)) is not type(v)
            or (k not in {"epoch", "generation"} and claims.get(k) != v)
            for k, v in context.items()
        ):
            raise ValueError
        # Only an authenticated token of this exact owner/installation/protocol
        # may reveal context drift. Epoch takes precedence over generation/age.
        if claims["epoch"] != str(epoch):
            raise SyncFailure(
                409,
                "sync_epoch_changed",
                details={
                    "current_sync_epoch": str(epoch),
                    "requested_sync_epoch": claims["epoch"],
                    "recovery_required": "epoch_recovery",
                },
            )
        if claims["generation"] != generation:
            raise SyncFailure(409, "account_generation_changed")
        return claims
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise SyncFailure(422, "invalid_sync_token") from None


def sign_checkpoint(
    secret, *, owner_id, generation, epoch, position, now, installation_id="calorie-app"
) -> str:
    return sign_token(
        context_claims(
            owner_id=owner_id, generation=generation, epoch=epoch, installation_id=installation_id
        )
        | {"kind": "checkpoint", "position": position, "issued": micros(now)},
        secret,
    )


def validate_checkpoint(
    token, secret, *, owner_id, generation, epoch, now, installation_id="calorie-app", push=False
) -> dict:
    claims = read_token(
        token,
        secret,
        kind="checkpoint",
        owner_id=owner_id,
        generation=generation,
        epoch=epoch,
        installation_id=installation_id,
    )
    try:
        if set(claims) != {
            "protocol",
            "owner",
            "generation",
            "epoch",
            "installation",
            "kind",
            "position",
            "issued",
        }:
            raise ValueError
        if type(claims["position"]) is not int or not 0 <= claims["position"] <= MAX_POSITION:
            raise ValueError
        if type(claims["issued"]) is not int or claims["issued"] < 0:
            raise ValueError
        issued = timestamp(claims["issued"])
        if issued > now:
            raise ValueError
    except (ValueError, OverflowError):
        raise SyncFailure(422, "invalid_sync_token") from None
    if now - issued > CHECKPOINT_TTL:
        raise SyncFailure(
            409 if push else 410,
            "sync_reconciliation_required" if push else "sync_cursor_expired",
            details={"current_sync_epoch": str(epoch), "recovery_required": "full_snapshot"},
        )
    return claims
