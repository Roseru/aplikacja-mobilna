"""Every private query contains the owner predicate, including nested items."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from calorie_app.modules.diary.models import DiaryDay, Meal, MealItem, ProductDraft, Weight


def owned(session: Session, model, owner_id: UUID, entity_id: UUID, *, live=True):
    query = select(model).where(model.owner_id == owner_id, model.id == entity_id)
    if live:
        query = query.where(model.deleted_at.is_(None))
    return session.scalar(query.execution_options(populate_existing=True))


def day_for_date(session: Session, owner_id: UUID, local_date):
    return session.scalar(
        select(DiaryDay)
        .where(DiaryDay.owner_id == owner_id, DiaryDay.local_date == local_date)
        .execution_options(populate_existing=True)
    )


def meal_items(session: Session, owner_id: UUID, meal_id: UUID) -> list[MealItem]:
    return list(
        session.scalars(
            select(MealItem)
            .where(MealItem.owner_id == owner_id, MealItem.meal_id == meal_id)
            .order_by(MealItem.position)
        )
    )


def meals_for_date(session: Session, owner_id: UUID, local_date) -> list[Meal]:
    return list(
        session.scalars(
            select(Meal)
            .where(
                Meal.owner_id == owner_id, Meal.local_date == local_date, Meal.deleted_at.is_(None)
            )
            .order_by(Meal.occurred_at, Meal.id)
        )
    )


# These classes are deliberately explicit exports for the small owned lookup helper.
PRIVATE_MODELS = (DiaryDay, Meal, ProductDraft, Weight)
