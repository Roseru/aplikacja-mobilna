"""Repeatable-read materialization and durable, bounded private pull pagination."""

import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.identity.service import current_epoch, lock_account
from calorie_app.modules.profiles.models import GoalTimeline
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.models import RecoveryMapping, SyncChange, SyncCounter, SyncReceipt
from calorie_app.modules.sync.repository import MODELS, entity, mapping_data
from calorie_app.modules.sync.snapshot_models import SyncSession, SyncSessionItem
from calorie_app.modules.sync.tokens import (
    CHECKPOINT_TTL,
    SESSION_TTL,
    context_claims,
    read_token,
    sign_checkpoint,
    sign_token,
    timestamp,
    validate_checkpoint,
)

MAX_SESSIONS = 4
MAX_SESSION_ITEMS = 100000
MAX_SESSION_BYTES = 64 * 1024 * 1024
MAX_ITEM_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")


def validate_query(query):
    """The router preserves repeated recovery IDs and rejects repeated scalars."""
    allowed = {
        "sync_epoch",
        "checkpoint",
        "snapshot_token",
        "page_token",
        "limit",
        "recovery_operation_ids",
    }
    if set(query) - allowed:
        raise SyncFailure(422, "invalid_request")
    result = dict(query)
    try:
        value = result.get("limit", 500)
        if isinstance(value, str):
            if not value.isascii() or not value.isdigit():
                raise ValueError
            value = int(value)
        if type(value) is not int or not 1 <= value <= 500:
            raise ValueError
        result["limit"] = value
        if "sync_epoch" in result:
            value = str(result["sync_epoch"])
            if str(UUID(value)) != value:
                raise ValueError
            result["sync_epoch"] = value
        for key in ("checkpoint", "snapshot_token", "page_token"):
            if key in result and (
                not isinstance(result[key], str) or not 1 <= len(result[key]) <= 4096
            ):
                raise ValueError
        if "recovery_operation_ids" in result:
            ids = result["recovery_operation_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
                raise ValueError
            ids = [str(x) for x in ids]
            if len(set(ids)) != len(ids) or any(str(UUID(x)) != x for x in ids):
                raise ValueError
            result["recovery_operation_ids"] = ids
        checkpoint, snapshot, page = (
            key in result for key in ("checkpoint", "snapshot_token", "page_token")
        )
        if checkpoint:
            if snapshot or "sync_epoch" not in result or "recovery_operation_ids" in result:
                raise ValueError
        elif snapshot:
            if not page or "sync_epoch" not in result or "recovery_operation_ids" in result:
                raise ValueError
        elif page:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise SyncFailure(422, "invalid_request") from None
    return result


def _context(session, owner_id, query):
    try:
        account = lock_account(session, owner_id)
    except DomainError as error:
        raise SyncFailure(error.status, error.code) from None
    # All writers use account -> counter -> aggregate. The account lock also
    # serializes creation/resource accounting across concurrent pull requests.
    counter = session.scalar(
        select(SyncCounter).where(SyncCounter.owner_id == owner_id).with_for_update()
    )
    epoch = current_epoch(session)
    if "sync_epoch" in query and query["sync_epoch"] != str(epoch):
        raise SyncFailure(
            409,
            "sync_epoch_changed",
            details={
                "current_sync_epoch": str(epoch),
                "requested_sync_epoch": query["sync_epoch"],
                "recovery_required": "epoch_recovery",
            },
        )
    return account, epoch, counter.position if counter else 0, database_now(session)


def _claims(state, kind, installation_id, offset=None):
    value = context_claims(
        owner_id=state.owner_id,
        generation=state.generation,
        epoch=state.epoch,
        installation_id=installation_id,
    ) | {"kind": kind, "session": str(state.id)}
    if offset is not None:
        value["offset"] = offset
    return value


def _add_item(session, state, kind, value):
    size = len(_json(value))
    if (
        size > MAX_ITEM_BYTES
        or state.item_count >= MAX_SESSION_ITEMS
        or state.byte_count + size > MAX_SESSION_BYTES
    ):
        raise SyncFailure(503, "sync_resources_exhausted")
    state.item_count += 1
    state.byte_count += size
    session.add(
        SyncSessionItem(
            session_id=state.id,
            owner_id=state.owner_id,
            position=state.item_count,
            kind=kind,
            value=value,
            byte_size=size,
        )
    )
    # Bounded client-side state even when an owner has many large aggregates.
    if state.item_count % 8 == 0:
        session.flush()


def _materialize(session, owner_id, query, secret, installation_id):
    account, epoch, high, now = _context(session, owner_id, query)
    claims = None
    if "checkpoint" in query:
        claims = validate_checkpoint(
            query["checkpoint"],
            secret,
            owner_id=owner_id,
            generation=account.generation,
            epoch=epoch,
            now=now,
            installation_id=installation_id,
        )
        if claims["position"] > high:
            raise SyncFailure(422, "invalid_sync_token")
    count = session.scalar(
        select(func.count()).select_from(SyncSession).where(SyncSession.owner_id == owner_id)
    )
    if count >= MAX_SESSIONS:
        raise SyncFailure(503, "sync_resources_exhausted")
    timeline = session.get(GoalTimeline, owner_id)
    state = SyncSession(
        id=uuid4(),
        owner_id=owner_id,
        generation=account.generation,
        epoch=epoch,
        mode="incremental" if claims else "snapshot",
        page_limit=query["limit"],
        high_position=high,
        base_position=claims["position"] if claims else 0,
        base_issued_at=timestamp(claims["issued"]) if claims else None,
        created_at=now,
        expires_at=now + SESSION_TTL,
        timeline_revision=timeline.revision if timeline else 0,
        item_count=0,
        byte_count=0,
    )
    session.add(state)
    session.flush()
    if claims:
        changes = session.scalars(
            select(SyncChange)
            .where(
                SyncChange.owner_id == owner_id,
                SyncChange.position > state.base_position,
                SyncChange.position <= high,
            )
            .order_by(SyncChange.position)
            .execution_options(yield_per=64)
        )
        for change in changes:
            if change.entity is not None:  # An internal online marker is not a wire entity.
                _add_item(session, state, "entities", change.entity)
    else:
        for entity_type, model in MODELS.items():
            ids = select(model.id).where(model.owner_id == owner_id)
            if hasattr(model, "deleted_at"):
                ids = ids.where(model.deleted_at.is_(None))
            for entity_id in session.scalars(
                ids.order_by(model.id).execution_options(yield_per=64)
            ):
                value = entity(session, owner_id, entity_type, entity_id)
                if value is None or value["deleted"]:
                    raise SyncFailure(503, "service_unavailable")
                _add_item(session, state, "entities", value)
    # Maps are copied with the target revision from this same frozen read. They
    # are harmlessly repeated in incremental pulls so deleted targets remain
    # associated with their original source without a second recreate.
    mappings = session.scalars(
        select(RecoveryMapping)
        .where(RecoveryMapping.owner_id == owner_id)
        .order_by(RecoveryMapping.source_epoch, RecoveryMapping.source_entity_id)
        .execution_options(yield_per=64)
    )
    for mapping in mappings:
        _add_item(session, state, "recovery_mappings", mapping_data(session, mapping))
    if "recovery_operation_ids" in query:
        receipts = session.scalars(
            select(SyncReceipt)
            .where(
                SyncReceipt.owner_id == owner_id,
                SyncReceipt.operation_id.in_([UUID(x) for x in query["recovery_operation_ids"]]),
            )
            .order_by(SyncReceipt.operation_id)
            .execution_options(yield_per=64)
        )
        for receipt in receipts:
            _add_item(
                session,
                state,
                "operation_receipts",
                {
                    "source_epoch": str(receipt.source_epoch),
                    "operation_id": str(receipt.operation_id),
                    "entity_id": str(receipt.entity_id),
                    "status": receipt.status,
                    "revision": receipt.revision,
                    "code": receipt.code,
                },
            )
    session.flush()
    # No page is published before the entire materialization has succeeded.
    return _page(session, state, 0, secret, installation_id, database_now(session))


def _page(session, state, offset, secret, installation_id, now):
    if now >= state.expires_at:
        raise SyncFailure(410, "snapshot_expired")
    if state.base_issued_at is not None and now - state.base_issued_at > CHECKPOINT_TTL:
        raise SyncFailure(
            410,
            "sync_cursor_expired",
            details={"current_sync_epoch": str(state.epoch), "recovery_required": "full_snapshot"},
        )
    if state.final_offset == offset and state.final_response is not None:
        return state.final_response
    response = {
        "sync_epoch": str(state.epoch),
        "mode": state.mode,
        "snapshot_token": sign_token(_claims(state, "snapshot", installation_id), secret)
        if state.mode == "snapshot"
        else None,
        "page_token": None,
        "checkpoint": None,
        "server_time": utc_text(state.created_at),
        "entities": [],
        "goal_timeline_revision": state.timeline_revision,
        "recovery_mappings": [],
        "operation_receipts": [],
    }
    items = session.scalars(
        select(SyncSessionItem)
        .where(
            SyncSessionItem.session_id == state.id,
            SyncSessionItem.owner_id == state.owner_id,
            SyncSessionItem.position > offset,
        )
        .order_by(SyncSessionItem.position)
        .limit(state.page_limit)
        .execution_options(yield_per=1)
    )
    end = offset
    size = len(_json(response)) + 4096  # reserve bounded token/envelope overhead
    for item in items:
        if size + item.byte_size + 1 > MAX_RESPONSE_BYTES:
            break
        response[item.kind].append(item.value)
        size += item.byte_size + 1
        end = item.position
    if end < state.item_count:
        if end == offset:
            raise SyncFailure(503, "sync_resources_exhausted")
        response["page_token"] = sign_token(_claims(state, "page", installation_id, end), secret)
    else:
        response["checkpoint"] = sign_checkpoint(
            secret,
            owner_id=state.owner_id,
            generation=state.generation,
            epoch=state.epoch,
            position=state.high_position,
            now=now,
            installation_id=installation_id,
        )
        state.final_offset, state.final_response = offset, response
        session.flush()
    if len(_json(response)) > MAX_RESPONSE_BYTES:
        raise SyncFailure(503, "sync_resources_exhausted")
    return response


def _continue(session, owner_id, query, secret, installation_id):
    account, epoch, _, now = _context(session, owner_id, query)
    context = {
        "owner_id": owner_id,
        "generation": account.generation,
        "epoch": epoch,
        "installation_id": installation_id,
    }
    page = read_token(query["page_token"], secret, kind="page", **context)
    try:
        if set(page) != {
            "protocol",
            "owner",
            "generation",
            "epoch",
            "installation",
            "kind",
            "session",
            "offset",
        }:
            raise ValueError
        session_id = UUID(page["session"])
        if (
            str(session_id) != page["session"]
            or type(page["offset"]) is not int
            or page["offset"] < 1
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise SyncFailure(422, "invalid_sync_token") from None
    state = session.scalar(
        select(SyncSession)
        .where(SyncSession.id == session_id, SyncSession.owner_id == owner_id)
        .with_for_update()
    )
    if state is None:
        raise SyncFailure(410, "snapshot_expired")
    if (
        state.epoch != epoch
        or state.generation != account.generation
        or state.page_limit != query["limit"]
        or page["offset"] > state.item_count
    ):
        raise SyncFailure(422, "invalid_sync_token")
    if state.mode == "snapshot":
        if "snapshot_token" not in query:
            raise SyncFailure(422, "invalid_sync_token")
        snapshot = read_token(query["snapshot_token"], secret, kind="snapshot", **context)
        if snapshot != _claims(state, "snapshot", installation_id):
            raise SyncFailure(422, "invalid_sync_token")
    else:
        if "checkpoint" not in query:
            raise SyncFailure(422, "invalid_sync_token")
        claims = validate_checkpoint(query["checkpoint"], secret, now=now, **context)
        if (
            claims["position"] != state.base_position
            or timestamp(claims["issued"]) != state.base_issued_at
        ):
            raise SyncFailure(422, "invalid_sync_token")
    return _page(session, state, page["offset"], secret, installation_id, now)


def pull(session_factory, owner_id, query, secret, *, installation_id="calorie-app") -> dict:
    query = validate_query(query)
    for attempt in range(3):
        try:
            with session_factory() as session:
                # Isolation is selected before the first statement. A competing
                # writer while waiting for account lock yields a retry, never a
                # partly materialized session from a mismatched read.
                if "page_token" not in query:
                    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                result = (
                    _continue(session, owner_id, query, secret, installation_id)
                    if "page_token" in query
                    else _materialize(session, owner_id, query, secret, installation_id)
                )
                session.commit()
                return result
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) not in {"40001", "40P01"} or attempt == 2:
                raise SyncFailure(503, "service_unavailable") from None
    raise SyncFailure(503, "service_unavailable")
