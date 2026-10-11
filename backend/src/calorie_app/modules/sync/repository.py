"""Owner-scoped serialization and the common mutation counter."""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical
from calorie_app.modules.diary import service as diary
from calorie_app.modules.diary.models import DiaryDay, Meal, ProductDraft, Weight
from calorie_app.modules.profiles.models import GoalVersion, Profile
from calorie_app.modules.profiles.service import profile_data
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.models import RecoveryMapping, SyncChange, SyncCounter

MODELS = {
    "profile": Profile,
    "goal": GoalVersion,
    "meal": Meal,
    "weight": Weight,
    "diary_day": DiaryDay,
    "product_draft": ProductDraft,
}
MAX_POSITION = 9223372036854775807


def lock_counter(session, owner_id):
    session.execute(insert(SyncCounter).values(owner_id=owner_id).on_conflict_do_nothing())
    return session.scalar(
        select(SyncCounter)
        .where(SyncCounter.owner_id == owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def owned(session, owner_id, kind, entity_id):
    model = MODELS[kind]
    return session.scalar(
        select(model)
        .where(model.owner_id == owner_id, model.id == entity_id)
        .execution_options(populate_existing=True)
    )


def entity(session, owner_id, entity_type, entity_id, live=False):
    row = owned(session, owner_id, entity_type, entity_id)
    if row is None:
        return None
    deleted = getattr(row, "deleted_at", None) is not None
    if live and deleted:
        return None
    payload = None
    if not deleted:
        if entity_type == "profile":
            payload = profile_data(row)["payload"]
        elif entity_type == "goal" or entity_type == "product_draft":
            payload = deepcopy(row.payload)
        elif entity_type == "meal":
            payload = diary.meal_payload(session, row)
        elif entity_type == "weight":
            payload = {
                "weight_kg": canonical(row.weight_kg),
                "occurred_at": utc_text(row.occurred_at),
                "local_date": row.local_date.isoformat(),
                "time_zone": row.time_zone,
            }
        else:
            payload = {
                "local_date": row.local_date.isoformat(),
                "time_zone": row.time_zone,
                "declared_complete": row.declared_complete,
            }
    return {
        "entity_type": entity_type,
        "entity_id": str(row.id),
        "revision": row.revision,
        "deleted": deleted,
        "payload": payload,
    }


def append_change(session, counter, value):
    if counter.position == MAX_POSITION:
        raise SyncFailure(503, "sync_counter_exhausted")
    counter.position += 1
    session.add(
        SyncChange(
            owner_id=counter.owner_id,
            position=counter.position,
            entity=value,
            created_at=database_now(session),
        )
    )
    session.flush()


def mapping_data(session, row: RecoveryMapping):
    target = entity(session, row.owner_id, row.entity_type, row.target_entity_id)
    # Reservation survives target details; the mapping never changes UUID.
    revision = target["revision"] if target else row.target_revision
    return {
        "source_epoch": str(row.source_epoch),
        "source_entity_id": str(row.source_entity_id),
        "target_entity_id": str(row.target_entity_id),
        "target_revision": revision,
    }
