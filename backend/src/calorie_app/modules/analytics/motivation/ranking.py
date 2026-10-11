"""Live ranking and bounded opaque cursors; no serialized private seek tuple.

Caller holds the account lock until commit. Initial page sessions are bounded
at eight per requester for ten minutes; continuing a session does not consume
this quota. Only the latest two input tokens remain usable. A lost ACK can
repeat its still-retained token with fresh visibility and current points.
"""

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.motivation.rules import rank_for_points
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.identity.service import current_epoch, lock_account

CURSOR_TTL = timedelta(minutes=10)
MAX_SESSIONS = 8
TOKEN_PATTERN = r"rk1\.[A-Za-z0-9_-]{43}"

# RANK is evaluated over every eligible participant before seek and LIMIT.
# The C collation also orders duplicate/Unicode pseudonyms deterministically;
# UUID is an internal presentation tiebreaker and never affects competition rank.
LIVE_RANKING = """
    WITH ranked AS (
        SELECT a.id AS owner_id, p.pseudonym COLLATE "C" AS pseudonym,
               m.total_points AS points, m.active_badges,
               RANK() OVER (ORDER BY m.total_points DESC) AS position
        FROM app.user_accounts a
        JOIN app.user_profiles p ON p.owner_id=a.id AND p.deleted_at IS NULL
        JOIN app.user_consents c ON c.owner_id=a.id AND c.ranking
        JOIN app.ranking_affirmations r ON r.owner_id=a.id
        JOIN app.motivation_accounts m ON m.owner_id=a.id
        WHERE a.state='active' AND m.backfill_state='ready'
          AND m.sync_epoch=:epoch AND r.ranking_consent_epoch=:epoch
    )
"""


def cursor_digest(token):
    if not isinstance(token, str) or re.fullmatch(TOKEN_PATTERN, token) is None:
        raise DomainError(422, "invalid_request")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_cursor_token():
    return "rk1." + secrets.token_urlsafe(32)


def own_ranking_position(session, owner_id, epoch):
    return session.scalar(
        text(LIVE_RANKING + "SELECT position FROM ranked WHERE owner_id=:owner"),
        {"owner": owner_id, "epoch": epoch},
    )


def ranking_publication(session, owner_id, epoch):
    """Marker revision is provenance, not a live-equality revision constraint."""
    row = (
        session.execute(
            text("""
            SELECT c.ranking AS requested,
                   (r.ranking_consent_epoch=:epoch) AS fresh,
                   (m.backfill_state='ready' AND m.sync_epoch=:epoch
                    AND p.id IS NOT NULL AND a.state='active') AS ready
            FROM app.user_accounts a JOIN app.user_consents c ON c.owner_id=a.id
            LEFT JOIN app.ranking_affirmations r ON r.owner_id=a.id
            LEFT JOIN app.motivation_accounts m ON m.owner_id=a.id
            LEFT JOIN app.user_profiles p ON p.owner_id=a.id AND p.deleted_at IS NULL
            WHERE a.id=:owner
        """),
            {"owner": owner_id, "epoch": epoch},
        )
        .mappings()
        .one()
    )
    requested, fresh = bool(row["requested"]), bool(row["fresh"])
    effective = requested and fresh and bool(row["ready"])
    return {
        "requested": requested,
        "effective": effective,
        "pending_consent_refresh": requested and not fresh,
        "consent_epoch": str(epoch),
        "own_position": own_ranking_position(session, owner_id, epoch) if effective else None,
    }


def _load_cursor(session, token, account, epoch, limit, now):
    cursor = (
        session.execute(
            text("""
            SELECT c.*, s.requester_id, s.generation, s.sync_epoch, s.page_limit,
                   s.purpose, s.expires_at
            FROM app.ranking_cursors c
            JOIN app.ranking_sessions s ON s.session_id=c.session_id
            WHERE c.token_digest=:digest AND s.requester_id=:owner
        """),
            {"digest": cursor_digest(token), "owner": account.id},
        )
        .mappings()
        .first()
    )
    if (
        cursor is None
        or cursor["generation"] != account.generation
        or cursor["sync_epoch"] != epoch
        or cursor["expires_at"] <= now
        or cursor["page_limit"] != limit
        or cursor["purpose"] != "ranking_v1"
        or cursor["anchor_id"] is None
    ):
        raise DomainError(410, "ranking_cursor_restart_required")
    return cursor


def _session_for_initial_page(session, account, epoch, limit, now):
    # There are at most eight rows for this locked owner: cleanup is bounded.
    session.execute(
        text("DELETE FROM app.ranking_sessions WHERE requester_id=:owner AND expires_at<=:now"),
        {"owner": account.id, "now": now},
    )
    count = session.scalar(
        text("SELECT count(*) FROM app.ranking_sessions WHERE requester_id=:owner"),
        {"owner": account.id},
    )
    if count >= MAX_SESSIONS:
        raise DomainError(429, "ranking_cursor_limit")
    session_id, expires = uuid4(), now + CURSOR_TTL
    session.execute(
        text("""
            INSERT INTO app.ranking_sessions
            (session_id,requester_id,generation,sync_epoch,page_limit,purpose,expires_at,created_at)
            VALUES (:id,:owner,:generation,:epoch,:limit,'ranking_v1',:expires,:now)
        """),
        {
            "id": session_id,
            "owner": account.id,
            "generation": account.generation,
            "epoch": epoch,
            "limit": limit,
            "expires": expires,
            "now": now,
        },
    )
    return session_id, expires


def _next_cursor(session, account, epoch, limit, now, cursor, anchor):
    if cursor is not None and cursor["next_token"]:
        existing = session.scalar(
            text("SELECT 1 FROM app.ranking_cursors WHERE token_digest=:digest"),
            {"digest": cursor_digest(cursor["next_token"])},
        )
        if existing:
            # Its original seek remains immutable even if the live replay page changed.
            return cursor["next_token"], cursor["expires_at"]
    if cursor is None:
        session_id, expires = _session_for_initial_page(session, account, epoch, limit, now)
        step = 1
    else:
        session_id, expires = cursor["session_id"], cursor["expires_at"]
        step = cursor["step"] + 1
    token = new_cursor_token()
    session.execute(
        text("""
            INSERT INTO app.ranking_cursors
            (token_digest,session_id,seek_points,seek_pseudonym,anchor_id,step)
            VALUES (:digest,:session,:points,:pseudonym,:anchor,:step)
        """),
        {
            "digest": cursor_digest(token),
            "session": session_id,
            "points": anchor["points"],
            "pseudonym": anchor["pseudonym"],
            "anchor": anchor["owner_id"],
            "step": step,
        },
    )
    if cursor is not None:
        session.execute(
            text("UPDATE app.ranking_cursors SET next_token=:token WHERE token_digest=:digest"),
            {"token": token, "digest": cursor["token_digest"]},
        )
    session.execute(
        text("DELETE FROM app.ranking_cursors WHERE session_id=:session AND step<:oldest"),
        {"session": session_id, "oldest": max(1, step - 1)},
    )
    return token, expires


def ranking_page(session, owner_id, limit=50, page_token=None, expected_generation=None):
    account = lock_account(session, owner_id, expected_generation)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainError(422, "invalid_request")
    epoch, now = current_epoch(session), database_now(session)
    cursor = _load_cursor(session, page_token, account, epoch, limit, now) if page_token else None
    seek = (
        ""
        if cursor is None
        else """
        WHERE points<:points OR (points=:points AND
            (pseudonym>:pseudonym COLLATE "C" OR
             (pseudonym=:pseudonym COLLATE "C" AND owner_id>:anchor)))
    """
    )
    parameters = {"epoch": epoch, "limit": limit + 1}
    if cursor is not None:
        parameters.update(
            points=cursor["seek_points"],
            pseudonym=cursor["seek_pseudonym"],
            anchor=cursor["anchor_id"],
        )
    rows = list(
        session.execute(
            text(
                LIVE_RANKING
                + "SELECT * FROM ranked "
                + seek
                + ' ORDER BY points DESC,pseudonym COLLATE "C",owner_id LIMIT :limit'
            ),
            parameters,
        ).mappings()
    )
    has_more, page = len(rows) > limit, rows[:limit]
    token, expires = None, None
    if has_more:
        token, expires = _next_cursor(session, account, epoch, limit, now, cursor, page[-1])
    return {
        "rule_version": "regularity_v1",
        "pagination": "live_keyset_v1",
        "as_of": utc_text(now),
        "items": [
            {
                "position": row["position"],
                "pseudonym": row["pseudonym"],
                "points": row["points"],
                "rank": rank_for_points(row["points"]),
                "active_badges": row["active_badges"],
            }
            for row in page
        ],
        "has_more": has_more,
        "next_page_token": token,
        "cursor_expires_at": utc_text(expires) if expires else None,
    }
