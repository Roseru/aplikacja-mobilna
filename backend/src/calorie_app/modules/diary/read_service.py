"""Repeatable-read materialization; each continuation rechecks current account context."""

import json
import re
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.diary import read_repository, read_tokens
from calorie_app.modules.diary.read_models import ReadSession, ReadSessionItem
from calorie_app.modules.identity.service import current_epoch, require_account
from calorie_app.modules.profiles.models import GoalTimeline, Profile
from calorie_app.modules.sync.models import SyncCounter
from calorie_app.modules.sync.tokens import SESSION_TTL, context_claims, micros

MAX_ADMISSION_ATTEMPTS = 8
MAX_SESSIONS = 4
MAX_SESSION_ITEMS = 100000
MAX_SESSION_BYTES = 64 * 1024 * 1024
MAX_ITEM_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")


def validate_query(query):
    try:
        if set(query) - {"from", "to", "limit", "page_token"}:
            raise ValueError
        result = dict(query)
        for key in ("from", "to"):
            if (
                not isinstance(result[key], str)
                or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", result[key]) is None
            ):
                raise ValueError
            result[key] = date.fromisoformat(result[key])
        if not 0 <= (result["to"] - result["from"]).days < 366:
            raise ValueError
        limit = result.get("limit", 100)
        if isinstance(limit, str):
            if len(limit) > 3 or not limit.isascii() or not limit.isdigit():
                raise ValueError
            limit = int(limit)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError
        result["limit"] = limit
        if "page_token" in result and (
            not isinstance(result["page_token"], str) or not 1 <= len(result["page_token"]) <= 4096
        ):
            raise ValueError
        return result
    except (ValueError, TypeError, KeyError):
        raise DomainError(422, "invalid_request") from None


def _claims(state, offset):
    return context_claims(
        owner_id=state.owner_id, generation=state.generation, epoch=state.epoch
    ) | {
        "kind": "read_page",
        "session": str(state.id),
        "endpoint": state.endpoint,
        "from": state.date_from.isoformat(),
        "to": state.date_to.isoformat(),
        "limit": state.page_limit,
        "offset": offset,
        "expires": micros(state.expires_at),
    }


def _materialize(session, account, epoch, endpoint, query, secret):
    session.execute(text("SELECT app.admit_read_session(:owner)"), {"owner": account.id})
    now = database_now(session)
    count = session.scalar(
        select(func.count())
        .select_from(ReadSession)
        .where(ReadSession.owner_id == account.id, ReadSession.expires_at > now)
    )
    if count >= MAX_SESSIONS:
        raise DomainError(503, "read_resources_exhausted")
    profile = session.scalar(
        select(Profile).where(Profile.owner_id == account.id, Profile.deleted_at.is_(None))
    )
    timeline = session.get(GoalTimeline, account.id)
    high = (
        session.scalar(select(SyncCounter.position).where(SyncCounter.owner_id == account.id)) or 0
    )
    context = {
        "account_id": str(account.id),
        "account_generation": account.generation,
        "sync_epoch": str(epoch),
        "as_of": utc_text(now),
        "time_zone": profile.time_zone if profile else None,
        "profile_revision": profile.revision if profile else None,
        "goal_timeline_revision": timeline.revision if timeline else 0,
        "server_position": high,
        "from": query["from"].isoformat(),
        "to": query["to"].isoformat(),
    }
    state = ReadSession(
        id=uuid4(),
        owner_id=account.id,
        generation=account.generation,
        epoch=epoch,
        endpoint=endpoint,
        date_from=query["from"],
        date_to=query["to"],
        page_limit=query["limit"],
        created_at=now,
        expires_at=now + SESSION_TTL,
        context=context,
        item_count=0,
        byte_count=0,
    )
    session.add(state)
    session.flush()
    for value in read_repository.records(session, account.id, endpoint, query["from"], query["to"]):
        size = len(encode(value))
        if (
            size > MAX_ITEM_BYTES
            or state.item_count >= MAX_SESSION_ITEMS
            or state.byte_count + size > MAX_SESSION_BYTES
        ):
            raise DomainError(503, "read_resources_exhausted")
        state.item_count += 1
        state.byte_count += size
        session.add(
            ReadSessionItem(
                session_id=state.id,
                owner_id=account.id,
                position=state.item_count,
                value=value,
                byte_size=size,
            )
        )
        if state.item_count % 8 == 0:
            session.flush()
    session.flush()
    response = _page(session, state, 0, secret, database_now(session))
    if response["next_page_token"] is None:
        # No continuation was issued: this copy has no replay value. Keep the
        # admission tuple write committed so waiting RR admissions still retry.
        session.execute(
            text("SELECT app.discard_unpaged_read(:owner,:session)"),
            {"owner": account.id, "session": state.id},
        )
    return response


def _page(session, state, offset, secret, now):
    if now >= state.expires_at:
        raise DomainError(410, "read_session_expired")
    response = state.context | {"items": [], "next_page_token": None}
    size, end = len(encode(response)) + 4096, offset
    for item in session.scalars(
        select(ReadSessionItem)
        .where(
            ReadSessionItem.session_id == state.id,
            ReadSessionItem.owner_id == state.owner_id,
            ReadSessionItem.position > offset,
        )
        .order_by(ReadSessionItem.position)
        .limit(state.page_limit)
        .execution_options(yield_per=1)
    ):
        if size + item.byte_size + 1 > MAX_RESPONSE_BYTES:
            break
        response["items"].append(item.value)
        size += item.byte_size + 1
        end = item.position
    if end < state.item_count:
        if end == offset:
            raise DomainError(503, "read_resources_exhausted")
        response["next_page_token"] = read_tokens.sign(_claims(state, end), secret)
    if len(encode(response)) > MAX_RESPONSE_BYTES:
        raise DomainError(503, "read_resources_exhausted")
    return response


def _continue(session, account, epoch, endpoint, query, secret):
    claims = read_tokens.verify(
        query["page_token"], secret, owner_id=account.id, generation=account.generation, epoch=epoch
    )
    try:
        identifier = UUID(claims["session"])
        offset = claims["offset"]
        if str(identifier) != claims["session"] or type(offset) is not int or offset < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise DomainError(422, "invalid_read_token") from None
    state = session.scalar(
        select(ReadSession).where(ReadSession.id == identifier, ReadSession.owner_id == account.id)
    )
    if state is None:
        raise DomainError(410, "read_session_expired")
    if (
        claims != _claims(state, offset)
        or state.endpoint != endpoint
        or state.date_from != query["from"]
        or state.date_to != query["to"]
        or state.page_limit != query["limit"]
        or offset >= state.item_count
    ):
        raise DomainError(422, "invalid_read_token")
    return _page(session, state, offset, secret, database_now(session))


def read(factory, principal, endpoint, query, secret):
    query = validate_query(query)
    if endpoint not in read_repository.MODELS:
        raise DomainError(422, "invalid_request")
    for attempt in range(MAX_ADMISSION_ATTEMPTS):
        try:
            with factory() as session:
                if "page_token" not in query:
                    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                session.execute(text("SET LOCAL statement_timeout='15000ms'"))
                session.execute(text("SET LOCAL lock_timeout='5000ms'"))
                account = require_account(session, principal)
                epoch = current_epoch(session)
                result = (
                    _continue(session, account, epoch, endpoint, query, secret)
                    if "page_token" in query
                    else _materialize(session, account, epoch, endpoint, query, secret)
                )
                session.commit()
                return result
        except DBAPIError as error:
            if (
                getattr(error.orig, "sqlstate", None) not in {"40001", "40P01"}
                or attempt == MAX_ADMISSION_ATTEMPTS - 1
            ):
                raise DomainError(503, "service_unavailable") from None
    raise DomainError(503, "service_unavailable")
