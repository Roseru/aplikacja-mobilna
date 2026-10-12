"""Owner/date constrained bounded inputs; no per-day or per-meal queries."""

from collections import defaultdict

from sqlalchemy import select, text

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.nutrition import FIELDS
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical
from calorie_app.modules.diary.models import DiaryDay, Meal, MealItem, Weight

MAX_STATISTICS_ROWS = 100000


class Declarations(dict):
    """Preserve the three-input tuple and bool mapping while carrying source zones."""

    def __init__(self):
        super().__init__()
        self.time_zones = {}


def _bounded(session, query, maximum):
    rows = list(session.execute(query.limit(maximum + 1)))
    if len(rows) > maximum:
        raise DomainError(422, "statistics_resource_limit")
    return rows


def window_inputs(session, owner_id, start, end, *, maximum=MAX_STATISTICS_ROWS):
    """Load minimal snapshot columns; bounded by total observed domain rows."""
    used = 0
    declarations = Declarations()
    for row in _bounded(
        session,
        select(DiaryDay.local_date, DiaryDay.declared_complete, DiaryDay.time_zone).where(
            DiaryDay.owner_id == owner_id,
            DiaryDay.local_date.between(start, end),
            DiaryDay.deleted_at.is_(None),
        ),
        maximum,
    ):
        declarations[row.local_date] = row.declared_complete
        declarations.time_zones[row.local_date] = row.time_zone
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


def window_day_facts(session, owner_id, start, end):
    """One bounded source-authoritative query shared with E8 projections.

    E5's public window remains at most 90 dates. A missing row is a failed
    snapshot, never permission to evaluate a different runtime formula.
    """
    count = end.toordinal() - start.toordinal() + 1
    if not 1 <= count <= 90:
        raise DomainError(422, "statistics_resource_limit")
    dates = [type(start).fromordinal(start.toordinal() + offset) for offset in range(count)]
    rows = session.execute(
        text(
            "SELECT local_date, matures_at, effective_complete, in_goal "
            "FROM app.e8_day_facts(:owner, CAST(:dates AS date[]))"
        ),
        {"owner": owner_id, "dates": dates},
    ).mappings()
    facts = {row["local_date"]: dict(row) for row in rows}
    if len(facts) != count or set(facts) != set(dates):
        raise DomainError(503, "service_unavailable")
    return facts
