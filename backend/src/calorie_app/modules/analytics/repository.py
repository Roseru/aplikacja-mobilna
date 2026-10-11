"""Owner/date constrained bounded inputs; no per-day or per-meal queries."""

from collections import defaultdict

from sqlalchemy import select

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.nutrition import FIELDS
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical
from calorie_app.modules.diary.models import DiaryDay, Meal, MealItem, Weight

MAX_STATISTICS_ROWS = 100000


def _bounded(session, query, maximum):
    rows = list(session.execute(query.limit(maximum + 1)))
    if len(rows) > maximum:
        raise DomainError(422, "statistics_resource_limit")
    return rows


def window_inputs(session, owner_id, start, end, *, maximum=MAX_STATISTICS_ROWS):
    """Load minimal snapshot columns; bounded by total observed domain rows."""
    used = 0
    declarations = {}
    for row in _bounded(
        session,
        select(DiaryDay.local_date, DiaryDay.declared_complete).where(
            DiaryDay.owner_id == owner_id,
            DiaryDay.local_date.between(start, end),
            DiaryDay.deleted_at.is_(None),
        ),
        maximum,
    ):
        declarations[row.local_date] = row.declared_complete
        used += 1
    meals = defaultdict(list)
    by_id = {}
    for row in _bounded(
        session,
        select(Meal.id, Meal.local_date).where(
            Meal.owner_id == owner_id,
            Meal.local_date.between(start, end),
            Meal.deleted_at.is_(None),
        ),
        maximum - used,
    ):
        payload = {"items": []}
        meals[row.local_date].append(payload)
        by_id[row.id] = payload
        used += 1
    columns = [getattr(MealItem, field) for field in FIELDS]
    for row in _bounded(
        session,
        select(
            MealItem.meal_id,
            MealItem.quantity_amount,
            MealItem.quantity_unit,
            MealItem.basis_unit,
            MealItem.density_g_per_ml,
            *columns,
        )
        .join(
            Meal,
            (Meal.id == MealItem.meal_id) & (Meal.owner_id == MealItem.owner_id),
        )
        .where(
            MealItem.owner_id == owner_id,
            Meal.owner_id == owner_id,
            Meal.local_date.between(start, end),
            Meal.deleted_at.is_(None),
        ),
        maximum - used,
    ):
        by_id[row.meal_id]["items"].append(
            {
                "quantity": {"amount": canonical(row.quantity_amount), "unit": row.quantity_unit},
                "basis_unit": row.basis_unit,
                "density_g_per_ml": canonical(row.density_g_per_ml)
                if row.density_g_per_ml is not None
                else None,
                "nutrition_per_100": {
                    field: canonical(getattr(row, field))
                    if getattr(row, field) is not None
                    else None
                    for field in FIELDS
                },
            }
        )
        used += 1
    weights = defaultdict(list)
    for row in _bounded(
        session,
        select(Weight.id, Weight.local_date, Weight.occurred_at, Weight.weight_kg).where(
            Weight.owner_id == owner_id,
            Weight.local_date.between(start, end),
            Weight.deleted_at.is_(None),
        ),
        maximum - used,
    ):
        weights[row.local_date].append(
            {
                "entity_id": str(row.id),
                "occurred_at": utc_text(row.occurred_at),
                "weight_kg": canonical(row.weight_kg),
            }
        )
        used += 1
    return declarations, meals, weights
