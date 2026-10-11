"""Signed immutable-timeline boundaries, without per-page database state."""

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.identity.service import current_epoch, lock_account
from calorie_app.modules.profiles.models import GoalTimeline, GoalVersion

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _encode(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value):
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _encode(raw) != value:
        raise ValueError
    return raw


def _secret(secret):
    if secret is None:
        raise DomainError(503, "service_unavailable")
    return bytes.fromhex(secret.get_secret_value())


def sign_goal_cursor(payload, secret):
    message = "gp1." + _encode(canonical_json(payload))
    return message + "." + _encode(hmac.digest(_secret(secret), message.encode(), hashlib.sha256))


def parse_goal_cursor(token, secret):
    try:
        if not isinstance(token, str) or len(token) > 2048:
            raise ValueError
        prefix, encoded, signature = token.split(".")
        message = (prefix + "." + encoded).encode()
        if prefix != "gp1" or not hmac.compare_digest(
            _decode(signature), hmac.digest(_secret(secret), message, hashlib.sha256)
        ):
            raise ValueError
        raw = _decode(encoded)
        data = json.loads(raw)
        if set(data) != {"owner", "generation", "epoch", "boundary", "after", "limit", "expires"}:
            raise ValueError
        if canonical_json(data) != raw:
            raise ValueError
        from uuid import UUID

        for field in ("owner", "epoch", "after"):
            if not isinstance(data[field], str) or str(UUID(data[field])) != data[field]:
                raise ValueError
        for field, low, high in (
            ("generation", 1, 2147483647),
            ("boundary", 1, 2147483647),
            ("limit", 1, 500),
            ("expires", 1, 253402300799999999),
        ):
            if type(data[field]) is not int or not low <= data[field] <= high:
                raise ValueError
        return data
    except (ValueError, TypeError, UnicodeError, OverflowError, KeyError):
        raise DomainError(422, "invalid_request") from None


def goal_page(session, owner_id, limit=100, page_token=None, secret=None):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise DomainError(422, "invalid_request")
    account = lock_account(session, owner_id)
    epoch = current_epoch(session)
    now = database_now(session)
    if page_token is None:
        timeline = session.get(GoalTimeline, owner_id, populate_existing=True)
        boundary = timeline.revision if timeline else 0
        delta = now + timedelta(hours=1) - EPOCH
        expires = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
        after = None
    else:
        cursor = parse_goal_cursor(page_token, secret)
        if (
            cursor["owner"] != str(owner_id)
            or cursor["generation"] != account.generation
            or cursor["epoch"] != str(epoch)
            or cursor["limit"] != limit
        ):
            raise DomainError(422, "invalid_request")
        if now >= EPOCH + timedelta(microseconds=cursor["expires"]):
            raise DomainError(410, "page_expired")
        boundary, expires, after = cursor["boundary"], cursor["expires"], cursor["after"]
    query = select(GoalVersion).where(
        GoalVersion.owner_id == owner_id, GoalVersion.timeline_revision <= boundary
    )
    if after is not None:
        from uuid import UUID

        query = query.where(GoalVersion.id > UUID(after))
    rows = list(session.scalars(query.order_by(GoalVersion.id).limit(limit + 1)))
    token = None
    if len(rows) > limit:
        token = sign_goal_cursor(
            {
                "owner": str(owner_id),
                "generation": account.generation,
                "epoch": str(epoch),
                "boundary": boundary,
                "after": str(rows[limit - 1].id),
                "limit": limit,
                "expires": expires,
            },
            secret,
        )
    return {
        "items": [
            {"entity_id": str(row.id), "revision": row.revision, "payload": row.payload}
            for row in rows[:limit]
        ],
        "next_page_token": token,
        "sync_epoch": str(epoch),
    }
