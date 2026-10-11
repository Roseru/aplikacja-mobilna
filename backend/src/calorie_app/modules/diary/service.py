"""Private writes under the account lock; callers own commit/rollback and E4 receipts."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.nutrition import FIELDS
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical
from calorie_app.modules.diary import repository
from calorie_app.modules.diary.models import DiaryDay, Meal, MealItem, ProductDraft, Weight
from calorie_app.modules.diary.validation import (
    DiaryValidationError,
    effective_complete,
    validate_payload,
)
from calorie_app.modules.identity.service import lock_account
from calorie_app.modules.profiles.models import GoalVersion

MAX_REVISION = 2147483647


def _validate(payload: dict, definition: str):
    try:
        validate_payload(payload, definition)
    except DiaryValidationError as error:
        raise DomainError(422, "invalid_request") from error


def _revision(row, base_revision: int):
    if type(base_revision) is not int or not 0 <= base_revision <= MAX_REVISION:
        raise DomainError(422, "invalid_request")
    current = row.revision if row else 0
    if current != base_revision or (row is not None and row.deleted_at is not None):
        raise DomainError(409, "version_conflict")
    if current == MAX_REVISION:
        raise DomainError(409, "version_conflict")
    return current + 1


def _ensure_day(session, owner_id, local_date, time_zone):
    day = repository.day_for_date(session, owner_id, local_date)
    if day is not None:
        if day.time_zone != time_zone or day.deleted_at is not None:
            raise DomainError(409, "version_conflict")
        return day
    day = DiaryDay(
        id=uuid4(),
        owner_id=owner_id,
        revision=1,
        local_date=local_date,
        time_zone=time_zone,
        declared_complete=False,
    )
    session.add(day)
    session.flush()
    return day


def _item(owner_id, meal_id, position, item):
    product = item["product"]
    return MealItem(
        owner_id=owner_id,
        meal_id=meal_id,
        item_id=UUID(item["item_id"]),
        position=position,
        name=item["name"],
        product_id=UUID(product["product_id"]) if product else None,
        product_revision=product["revision"] if product else None,
        quantity_amount=Decimal(item["quantity"]["amount"]),
        quantity_unit=item["quantity"]["unit"],
        basis_unit=item["basis_unit"],
        **{
            field: Decimal(item["nutrition_per_100"][field])
            if item["nutrition_per_100"][field] is not None
            else None
            for field in FIELDS
        },
        density_g_per_ml=Decimal(item["density_g_per_ml"])
        if item["density_g_per_ml"] is not None
        else None,
        density_source=item["density_source"],
        nutrition_origin=item["nutrition_origin"],
        formula_version=item["formula_version"],
        ration_component_position=item["ration_component_position"],
    )


def item_payload(item: MealItem) -> dict:
    return {
        "item_id": str(item.item_id),
        "name": item.name,
        "product": {"product_id": str(item.product_id), "revision": item.product_revision}
        if item.product_id is not None
        else None,
        "quantity": {"amount": canonical(item.quantity_amount), "unit": item.quantity_unit},
        "basis_unit": item.basis_unit,
        "nutrition_per_100": {
            field: canonical(getattr(item, field)) if getattr(item, field) is not None else None
            for field in FIELDS
        },
        "density_g_per_ml": canonical(item.density_g_per_ml)
        if item.density_g_per_ml is not None
        else None,
        "density_source": item.density_source,
        "nutrition_origin": item.nutrition_origin,
        "formula_version": item.formula_version,
        "ration_component_position": item.ration_component_position,
    }


def meal_payload(session: Session, meal: Meal) -> dict:
    return {
        "title": meal.title,
        "occurred_at": utc_text(meal.occurred_at),
        "time_zone": meal.time_zone,
        "local_date": meal.local_date.isoformat(),
        "meal_type": meal.meal_type,
        "goal_id": str(meal.goal_id) if meal.goal_id else None,
        "ration": deepcopy(meal.ration),
        "items": [
            item_payload(item) for item in repository.meal_items(session, meal.owner_id, meal.id)
        ],
    }


def read_meal(
    session: Session, owner_id: UUID, entity_id: UUID, *, expected_generation=None
) -> dict:
    lock_account(session, owner_id, expected_generation=expected_generation)
    meal = repository.owned(session, Meal, owner_id, entity_id)
    if meal is None:
        raise DomainError(404, "not_found")
    return meal_payload(session, meal)


def save_meal(
    session: Session,
    owner_id: UUID,
    entity_id: UUID,
    payload: dict,
    *,
    base_revision=0,
    expected_generation=None,
) -> Meal:
    lock_account(session, owner_id, expected_generation=expected_generation)
    _validate(payload, "Meal")
    row = repository.owned(session, Meal, owner_id, entity_id, live=False)
    revision = _revision(row, base_revision)
    local_date = date.fromisoformat(payload["local_date"])
    _ensure_day(session, owner_id, local_date, payload["time_zone"])
    goal_id = UUID(payload["goal_id"]) if payload["goal_id"] else None
    if (
        goal_id
        and session.scalar(
            select(GoalVersion.id).where(
                GoalVersion.owner_id == owner_id, GoalVersion.id == goal_id
            )
        )
        is None
    ):
        raise DomainError(422, "invalid_request")
    fields = {key: payload[key] for key in ("title", "time_zone", "meal_type")}
    fields.update(
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        local_date=local_date,
        goal_id=goal_id,
        ration=deepcopy(payload["ration"]),
    )
    if row is None:
        row = Meal(id=entity_id, owner_id=owner_id, revision=revision, **fields)
        session.add(row)
    else:
        row.revision = revision
        for key, value in fields.items():
            setattr(row, key, value)
        session.execute(
            delete(MealItem).where(MealItem.owner_id == owner_id, MealItem.meal_id == entity_id)
        )
    session.flush()
    session.add_all(
        [_item(owner_id, entity_id, i, item) for i, item in enumerate(payload["items"], start=1)]
    )
    session.flush()
    return row


def save_weight(
    session: Session,
    owner_id: UUID,
    entity_id: UUID,
    payload: dict,
    *,
    base_revision=0,
    expected_generation=None,
) -> Weight:
    lock_account(session, owner_id, expected_generation=expected_generation)
    _validate(payload, "Weight")
    row = repository.owned(session, Weight, owner_id, entity_id, live=False)
    revision = _revision(row, base_revision)
    fields = dict(
        weight_kg=Decimal(payload["weight_kg"]),
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        local_date=date.fromisoformat(payload["local_date"]),
        time_zone=payload["time_zone"],
    )
    if row is None:
        row = Weight(id=entity_id, owner_id=owner_id, revision=revision, **fields)
        session.add(row)
    else:
        row.revision = revision
        for key, value in fields.items():
            setattr(row, key, value)
    session.flush()
    return row


def save_product_draft(
    session: Session,
    owner_id: UUID,
    entity_id: UUID,
    payload: dict,
    *,
    base_revision=0,
    expected_generation=None,
) -> ProductDraft:
    lock_account(session, owner_id, expected_generation=expected_generation)
    _validate(payload, "ProductDraft")
    row = repository.owned(session, ProductDraft, owner_id, entity_id, live=False)
    revision = _revision(row, base_revision)
    if row is None:
        row = ProductDraft(
            id=entity_id, owner_id=owner_id, revision=revision, payload=deepcopy(payload)
        )
        session.add(row)
    else:
        row.revision, row.payload = revision, deepcopy(payload)
    session.flush()
    return row


def save_diary_day(
    session: Session,
    owner_id: UUID,
    entity_id: UUID,
    payload: dict,
    *,
    base_revision=0,
    expected_generation=None,
) -> DiaryDay:
    lock_account(session, owner_id, expected_generation=expected_generation)
    _validate(payload, "DiaryDay")
    row = repository.owned(session, DiaryDay, owner_id, entity_id, live=False)
    revision = _revision(row, base_revision)
    local_date = date.fromisoformat(payload["local_date"])
    existing = repository.day_for_date(session, owner_id, local_date)
    if existing is not None and existing.id != entity_id:
        raise DomainError(409, "version_conflict")
    if row is not None and (row.local_date != local_date or row.time_zone != payload["time_zone"]):
        raise DomainError(409, "version_conflict")
    if row is None:
        row = DiaryDay(
            id=entity_id,
            owner_id=owner_id,
            revision=revision,
            local_date=local_date,
            time_zone=payload["time_zone"],
            declared_complete=payload["declared_complete"],
        )
        session.add(row)
    else:
        row.revision, row.declared_complete = revision, payload["declared_complete"]
    session.flush()
    return row


def day_is_complete(
    session: Session, owner_id: UUID, entity_id: UUID, *, expected_generation=None
) -> bool:
    lock_account(session, owner_id, expected_generation=expected_generation)
    day = repository.owned(session, DiaryDay, owner_id, entity_id)
    if day is None:
        raise DomainError(404, "not_found")
    meals = repository.meals_for_date(session, owner_id, day.local_date)
    return effective_complete(day.declared_complete, [meal_payload(session, row) for row in meals])


def delete_entity(
    session: Session,
    model,
    owner_id: UUID,
    entity_id: UUID,
    *,
    base_revision: int,
    expected_generation=None,
):
    """Tombstones retain snapshots and IDs; stale edits cannot resurrect them."""
    if model not in repository.PRIVATE_MODELS:
        raise ValueError("unsupported_private_entity")
    lock_account(session, owner_id, expected_generation=expected_generation)
    row = repository.owned(session, model, owner_id, entity_id, live=False)
    if row is None:
        raise DomainError(404, "not_found")
    revision = _revision(row, base_revision)
    if model is DiaryDay and repository.meals_for_date(session, owner_id, row.local_date):
        raise DomainError(409, "version_conflict")
    row.revision, row.deleted_at = revision, database_now(session)
    session.flush()
    return row


def remove_meal_item(
    session: Session,
    owner_id: UUID,
    entity_id: UUID,
    item_id: UUID,
    *,
    base_revision: int,
    expected_generation=None,
) -> Meal:
    lock_account(session, owner_id, expected_generation=expected_generation)
    row = repository.owned(session, Meal, owner_id, entity_id)
    if row is None:
        raise DomainError(404, "not_found")
    _revision(row, base_revision)
    payload = meal_payload(session, row)
    remaining = [item for item in payload["items"] if item["item_id"] != str(item_id)]
    if len(remaining) == len(payload["items"]):
        raise DomainError(404, "not_found")
    if not remaining:
        return delete_entity(
            session,
            Meal,
            owner_id,
            entity_id,
            base_revision=base_revision,
            expected_generation=expected_generation,
        )
    payload["items"] = remaining
    return save_meal(
        session,
        owner_id,
        entity_id,
        payload,
        base_revision=base_revision,
        expected_generation=expected_generation,
    )
