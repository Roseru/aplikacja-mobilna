"""Ordered operation transactions. The caller commits before publishing an ACK."""

import hashlib
from copy import deepcopy
from datetime import date
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.models import ProductVersion
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.diary import service as diary
from calorie_app.modules.diary.models import DiaryDay, Meal
from calorie_app.modules.identity.service import current_epoch, lock_account
from calorie_app.modules.profiles import service as profiles
from calorie_app.modules.profiles.models import GoalTimeline, Profile
from calorie_app.modules.profiles.schemas import GoalPayload, ProfilePayload
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.models import RecoveryMapping, SyncReceipt, SyncReservation
from calorie_app.modules.sync.repository import (
    MODELS,
    append_change,
    entity,
    lock_counter,
    mapping_data,
    owned,
)
from calorie_app.modules.sync.tokens import validate_checkpoint

MAX_REVISION = 2147483647


class Refusal(Exception):
    def __init__(self, code, *, status="rejected", current=None, mapping=None):
        self.code, self.status, self.current, self.mapping = code, status, current, mapping


def context(session, owner_id, data, secret, *, generation=None):
    account = lock_account(session, owner_id, generation)
    epoch = current_epoch(session)
    if data["sync_epoch"] != str(epoch) or any(
        op["sync_epoch"] != str(epoch) for op in data["operations"]
    ):
        raise SyncFailure(
            409,
            "sync_epoch_changed",
            {
                "current_sync_epoch": str(epoch),
                "requested_sync_epoch": data["sync_epoch"],
                "recovery_required": "epoch_recovery",
            },
        )
    validate_checkpoint(
        data["checkpoint"],
        secret,
        owner_id=owner_id,
        generation=account.generation,
        epoch=epoch,
        now=database_now(session),
        push=True,
    )
    return account


def fingerprint(operation):
    # Preflight has accepted only schema-recognized canonical Decimal strings.
    # Canonical JSON therefore normalizes recognized decimals without rewriting
    # arbitrary text, tokens, recovery IDs or ordered arrays.
    return hashlib.sha256(canonical_json(operation)).hexdigest()


def refusal_result(op, error, *, retained=True):
    return {
        "operation_id": op["operation_id"],
        "entity_id": op["entity_id"],
        "status": error.status,
        "code": error.code,
        "message": "Operacja wymaga uzgodnienia.",
        "current": error.current,
        "recovery_mapping": error.mapping,
        "details_retained": retained,
    }


def replay(session, receipt, op):
    if receipt.request_hash != fingerprint(op):
        return refusal_result(op, Refusal("operation_id_reused"))
    if receipt.response is not None:
        result = deepcopy(receipt.response)
        if result["status"] == "accepted":
            result["status"] = "already_applied"
        return result
    mapping = None
    if receipt.recovery_epoch is not None:
        row = session.get(
            RecoveryMapping, (receipt.owner_id, receipt.recovery_epoch, receipt.recovery_entity_id)
        )
        mapping = mapping_data(session, row) if row else None
    if receipt.status == "accepted":
        return {
            "operation_id": op["operation_id"],
            "entity_id": op["entity_id"],
            "status": "already_applied",
            "revision": receipt.revision,
            "recovery_mapping": mapping,
        }
    return refusal_result(
        op, Refusal(receipt.code, status=receipt.status, mapping=mapping), retained=False
    )


def check_recovery(session, owner_id, op):
    source = op.get("recovery")
    if source is None:
        return None
    epoch, source_id = UUID(source["source_epoch"]), UUID(source["source_entity_id"])
    kind = op["entity_type"]
    if epoch == UUID(op["sync_epoch"]) or op["action"] != "upsert":
        raise Refusal("recovery_source_invalid")
    existing = session.get(MODELS[kind], source_id)
    for source_kind, model in MODELS.items():
        known = session.get(model, source_id)
        if known is not None and (known.owner_id != owner_id or source_kind != kind):
            raise Refusal("recovery_source_invalid")
    reserved = session.scalar(select(SyncReservation).where(SyncReservation.entity_id == source_id))
    if reserved is not None:
        raise Refusal("recovery_source_invalid")
    if source["source_operation_id"] is not None:
        receipt = session.get(SyncReceipt, (owner_id, UUID(source["source_operation_id"])))
        if (
            receipt is None
            and session.scalar(
                select(SyncReceipt.owner_id)
                .where(
                    SyncReceipt.operation_id == UUID(source["source_operation_id"]),
                    SyncReceipt.owner_id != owner_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise Refusal("recovery_source_invalid")
        if receipt is not None and (
            receipt.source_epoch != epoch
            or receipt.entity_id != source_id
            or receipt.entity_type != kind
            or receipt.status != "accepted"
            or receipt.action != "upsert"
            or (
                source["source_revision"] is not None
                and receipt.revision != source["source_revision"]
            )
        ):
            raise Refusal("recovery_source_invalid")
    mapping = session.get(RecoveryMapping, (owner_id, epoch, source_id))
    if mapping is not None:
        data = mapping_data(session, mapping)
        target = entity(session, owner_id, mapping.entity_type, mapping.target_entity_id)
        if mapping.entity_type != kind:
            raise Refusal("recovery_source_invalid", mapping=data)
        if target is None or target["deleted"]:
            raise Refusal(
                "recovery_target_conflict", status="conflict", current=target, mapping=data
            )
        if canonical_json(target["payload"]) != canonical_json(op["payload"]):
            raise Refusal(
                "recovery_content_conflict", status="conflict", current=target, mapping=data
            )
        return {
            "status": "already_applied",
            "revision": target["revision"],
            "recovery_mapping": data,
        }
    if source["decision"] == "recreate_missing":
        if (
            op["base_revision"] is not None
            or UUID(op["entity_id"]) == source_id
            or existing is not None
        ):
            raise Refusal("recovery_source_invalid")
    elif op["base_revision"] is None:
        raise Refusal("recovery_source_invalid")
    return None


def mutate(session, owner_id, op, counter):
    kind, target_id, base = op["entity_type"], UUID(op["entity_id"]), op["base_revision"]
    recovered = check_recovery(session, owner_id, op)
    if recovered is not None:
        return recovered
    current = entity(session, owner_id, kind, target_id)
    row = owned(session, owner_id, kind, target_id)
    foreign = session.get(MODELS[kind], target_id)
    if foreign is not None and foreign.owner_id != owner_id:
        raise Refusal("entity_id_reserved", status="conflict")
    reserved = session.get(SyncReservation, (owner_id, kind, target_id))
    if reserved is not None:
        raise Refusal("entity_id_reserved", status="conflict", current=current)
    # Immutable goal decisions take precedence over axis/base validation.
    if kind == "goal" and row is not None:
        in_use = (
            op["action"] == "delete"
            and session.scalar(
                select(Meal.id).where(Meal.owner_id == owner_id, Meal.goal_id == target_id).limit(1)
            )
            is not None
        )
        raise Refusal("goal_in_use" if in_use else "goal_immutable", current=current)
    if current and current["deleted"]:
        raise Refusal("entity_deleted", status="conflict", current=current)
    if kind == "goal" and op["action"] == "delete":
        raise Refusal("goal_immutable")
    # Natural keys identify the owner's canonical entity without revealing B.
    if op["action"] == "upsert" and kind in {"profile", "diary_day"}:
        model = MODELS[kind]
        query = select(model).where(model.owner_id == owner_id, model.id != target_id)
        query = (
            query.where(Profile.deleted_at.is_(None))
            if kind == "profile"
            else query.where(DiaryDay.local_date == date.fromisoformat(op["payload"]["local_date"]))
        )
        natural = session.scalar(query)
        if natural is not None:
            raise Refusal(
                "revision_conflict",
                status="conflict",
                current=entity(session, owner_id, kind, natural.id),
            )
    if (row is None and base is not None) or (row is not None and base != row.revision):
        raise Refusal("revision_conflict", status="conflict", current=current)
    if row is not None and row.revision == MAX_REVISION:
        raise Refusal("revision_exhausted")
    if kind == "goal":
        timeline = session.get(GoalTimeline, owner_id)
        axis = timeline.revision if timeline else 0
        if axis == MAX_REVISION:
            raise Refusal("revision_exhausted")
    previous_day = None
    if kind == "meal" and op["action"] == "upsert":
        previous_day = session.scalar(
            select(DiaryDay.id).where(
                DiaryDay.owner_id == owner_id,
                DiaryDay.local_date == date.fromisoformat(op["payload"]["local_date"]),
            )
        )
        goal_id = op["payload"]["goal_id"]
        if goal_id and owned(session, owner_id, "goal", UUID(goal_id)) is None:
            raise Refusal("dependency_missing")
        for item in op["payload"]["items"]:
            reference = item["product"]
            if (
                reference
                and session.get(
                    ProductVersion, (UUID(reference["product_id"]), reference["revision"])
                )
                is None
            ):
                raise Refusal("dependency_missing")
    try:
        if op["action"] == "delete":
            if kind == "profile":
                profiles.delete_profile(session, owner_id, target_id, base)
            else:
                diary.delete_entity(session, MODELS[kind], owner_id, target_id, base_revision=base)
            row = owned(session, owner_id, kind, target_id)
            session.add(
                SyncReservation(
                    owner_id=owner_id,
                    entity_type=kind,
                    entity_id=target_id,
                    deleted_at=row.deleted_at,
                )
            )
        elif kind == "profile":
            row = profiles.save_profile(
                session,
                owner_id,
                target_id,
                ProfilePayload.model_validate(op["payload"]),
                base or 0,
            )
        elif kind == "goal":
            row = profiles.create_goal(
                session, owner_id, target_id, GoalPayload.model_validate(op["payload"])
            )
        else:
            row = getattr(diary, "save_" + kind)(
                session, owner_id, target_id, op["payload"], base_revision=base or 0
            )
    except DomainError as error:
        if error.code == "goal_timeline_conflict":
            raise Refusal(error.code, status="conflict") from None
        if error.code in {"version_conflict", "profile_already_exists"}:
            raise Refusal("revision_conflict", status="conflict", current=current) from None
        if error.code == "revision_exhausted":
            raise Refusal(error.code) from None
        if error.code in {"invalid_request", "not_found", "entity_id_reused"}:
            raise Refusal("invalid_payload") from None
        raise
    session.flush()
    # Deferred E3 aggregate and goal-axis constraints must pass before accepted.
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    if kind == "meal" and op["action"] == "upsert" and previous_day is None:
        day = session.scalar(
            select(DiaryDay).where(
                DiaryDay.owner_id == owner_id,
                DiaryDay.local_date == date.fromisoformat(op["payload"]["local_date"]),
            )
        )
        append_change(session, counter, entity(session, owner_id, "diary_day", day.id))
    append_change(session, counter, entity(session, owner_id, kind, target_id))
    mapping = None
    if "recovery" in op:
        source = op["recovery"]
        mapping_row = RecoveryMapping(
            owner_id=owner_id,
            source_epoch=UUID(source["source_epoch"]),
            source_entity_id=UUID(source["source_entity_id"]),
            entity_type=kind,
            target_entity_id=target_id,
            target_revision=row.revision,
        )
        session.add(mapping_row)
        session.flush()
        mapping = mapping_data(session, mapping_row)
    return {"status": "accepted", "revision": row.revision, "recovery_mapping": mapping}


def apply_operation(session, owner_id, data, op, secret, generation):
    lock_account(session, owner_id, generation)
    counter = lock_counter(session, owner_id)
    context(session, owner_id, data, secret, generation=generation)
    receipt = session.get(SyncReceipt, (owner_id, UUID(op["operation_id"])))
    if receipt is not None:
        return replay(session, receipt, op)
    try:
        with session.begin_nested():
            outcome = mutate(session, owner_id, op, counter)
        result = {"operation_id": op["operation_id"], "entity_id": op["entity_id"], **outcome}
    except Refusal as error:
        result = refusal_result(op, error)
    except ValidationError:
        # Valid schema can still fail a DB-dependent domain rule.
        result = refusal_result(op, Refusal("invalid_payload"))
    except IntegrityError as error:
        # Only named E3 domain constraints are durable refusals. Connection,
        # deadlock, serialization and unknown DB failures propagate to caller.
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint not in {"meal_day_fk", "meal_goal_fk", "meal_item_product_fk"}:
            raise
        result = refusal_result(op, Refusal("dependency_missing"))
    source = op.get("recovery", {})
    session.add(
        SyncReceipt(
            owner_id=owner_id,
            operation_id=UUID(op["operation_id"]),
            request_hash=fingerprint(op),
            source_epoch=UUID(op["sync_epoch"]),
            entity_type=op["entity_type"],
            entity_id=UUID(op["entity_id"]),
            action=op["action"],
            status="accepted" if result["status"] == "already_applied" else result["status"],
            code=result.get("code"),
            revision=result.get("revision"),
            response=result,
            created_at=database_now(session),
            recovery_epoch=UUID(source["source_epoch"]) if source else None,
            recovery_entity_id=UUID(source["source_entity_id"]) if source else None,
        )
    )
    session.flush()
    return result
