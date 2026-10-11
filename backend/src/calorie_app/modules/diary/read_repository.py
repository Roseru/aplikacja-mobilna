"""Owner/date-bounded streaming private reads with bounded aggregate batches."""

import json

from sqlalchemy import select

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical
from calorie_app.modules.diary.models import DiaryDay, Meal, MealItem, Weight
from calorie_app.modules.diary.service import item_payload
from calorie_app.modules.diary.validation import effective_complete

MAX_COMPLETENESS_MEALS = 10000
MAX_COMPLETENESS_BYTES = 8 * 1024 * 1024
MAX_COMPLETENESS_ITEMS = 100000
MODELS = {"meals": Meal, "weights": Weight, "diary-days": DiaryDay}


def records(session, owner, endpoint, start, end):
    model = MODELS[endpoint]
    order = model.local_date if endpoint == "diary-days" else model.occurred_at
    query = (
        select(model)
        .where(
            model.owner_id == owner,
            model.local_date >= start,
            model.local_date <= end,
            model.deleted_at.is_(None),
        )
        .order_by(order, model.id)
    )
    stream = session.scalars(query.execution_options(yield_per=32))
    for batch in stream.partitions(32):
        if endpoint == "meals":
            items = _items(session, owner, [row.id for row in batch])
            for row in batch:
                yield _record(row, _meal(row, items.get(row.id, [])))
        elif endpoint == "weights":
            for row in batch:
                yield _record(
                    row,
                    {
                        "weight_kg": canonical(row.weight_kg),
                        "occurred_at": utc_text(row.occurred_at),
                        "local_date": row.local_date.isoformat(),
                        "time_zone": row.time_zone,
                    },
                )
        else:
            dates = [row.local_date for row in batch]
            meals = list(
                session.scalars(
                    select(Meal)
                    .where(
                        Meal.owner_id == owner,
                        Meal.local_date.in_(dates),
                        Meal.deleted_at.is_(None),
                    )
                    .limit(MAX_COMPLETENESS_MEALS + 1)
                )
            )
            # Bound completeness work separately even if declarations themselves are small.
            if len(meals) > MAX_COMPLETENESS_MEALS:
                raise DomainError(503, "read_resources_exhausted")
            payloads = {}
            work_bytes = 0
            work_items = 0
            for i in range(0, len(meals), 32):
                chunk = meals[i : i + 32]
                items = _items(session, owner, [row.id for row in chunk])
                work_items += sum(len(value) for value in items.values())
                if work_items > MAX_COMPLETENESS_ITEMS:
                    raise DomainError(503, "read_resources_exhausted")
                for meal in chunk:
                    work_bytes += len(
                        json.dumps(_meal(meal, items.get(meal.id, [])), ensure_ascii=False).encode(
                            "utf-8"
                        )
                    )
                    if work_bytes > MAX_COMPLETENESS_BYTES:
                        raise DomainError(503, "read_resources_exhausted")
                    payloads.setdefault(meal.local_date, []).append(
                        _meal(meal, items.get(meal.id, []))
                    )
            for row in batch:
                yield _record(
                    row,
                    {
                        "local_date": row.local_date.isoformat(),
                        "time_zone": row.time_zone,
                        "declared_complete": row.declared_complete,
                    },
                ) | {
                    "effective_complete": effective_complete(
                        row.declared_complete, payloads.get(row.local_date, [])
                    )
                }


def _items(session, owner, ids):
    result = {}
    for item in session.scalars(
        select(MealItem)
        .where(MealItem.owner_id == owner, MealItem.meal_id.in_(ids))
        .order_by(MealItem.meal_id, MealItem.position)
    ):
        result.setdefault(item.meal_id, []).append(item_payload(item))
    return result


def _meal(row, items):
    return {
        "title": row.title,
        "occurred_at": utc_text(row.occurred_at),
        "local_date": row.local_date.isoformat(),
        "time_zone": row.time_zone,
        "meal_type": row.meal_type,
        "goal_id": str(row.goal_id) if row.goal_id else None,
        "ration": row.ration,
        "items": items,
    }


def _record(row, payload):
    return {"entity_id": str(row.id), "revision": row.revision, "payload": payload}
