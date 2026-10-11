"""statistics_v1 reducer and one coherent server snapshot orchestration."""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.repository import window_inputs
from calorie_app.modules.catalog.nutrition import FIELDS
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical
from calorie_app.modules.diary.validation import effective_complete, meal_totals
from calorie_app.modules.identity.service import current_epoch, lock_account
from calorie_app.modules.profiles.models import GoalTimeline, Profile
from calorie_app.modules.profiles.service import goal_for_dates
from calorie_app.modules.sync.models import SyncCounter

STATISTICS_STATEMENT_TIMEOUT_MS = 15000


def statistics_window(as_of, time_zone, days):
    if type(days) is not int or days not in (7, 30, 90):
        raise DomainError(422, "invalid_request")
    today = as_of.astimezone(ZoneInfo(time_zone)).date()
    return today - timedelta(days=days - 1), today


def rounded_average(values):
    if not values:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        return canonical(
            (sum(values, Decimal(0)) / Decimal(len(values))).quantize(
                Decimal("0.000000000001"), rounding=ROUND_HALF_UP
            )
        )


def build_statistics(start, today, declarations, meals, weights, goals):
    """Pure common-vector reducer; all inputs are already the same DB snapshot."""
    daily = []
    values = {field: [] for field in FIELDS}
    day = start
    with localcontext() as ctx:
        ctx.prec = 50
        while day <= today:
            day_meals = meals.get(day, [])
            items = [item for meal in day_meals for item in meal["items"]]
            declared = declarations.get(day, False)
            complete = effective_complete(declared, day_meals)
            totals = meal_totals(items)
            for field in FIELDS:
                known = sum(item["nutrition_per_100"][field] is not None for item in items)
                totals[field] = {
                    "known_sum": totals[field]["known_sum"] if known else None,
                    "complete": bool(items) and totals[field]["complete"],
                    "known_count": known,
                    "missing_count": totals[field]["missing_count"],
                }
                if day < today and complete and totals[field]["complete"]:
                    values[field].append(Decimal(totals[field]["known_sum"]))
            goal = goals.get(day)
            target = Decimal(goal["energy_kcal"]) if goal else None
            match = None
            if complete and target is not None and target > 0:
                energy = Decimal(totals["energy_kcal"]["known_sum"])
                match = target * Decimal("0.9") <= energy <= target * Decimal("1.1")
            points = weights.get(day, [])
            latest = max(
                points,
                key=lambda point: (
                    datetime.fromisoformat(point["occurred_at"]),
                    point["entity_id"],
                ),
                default=None,
            )
            daily.append(
                {
                    "local_date": day.isoformat(),
                    "closed": day < today,
                    "declared_complete": declared,
                    "effective_complete": complete,
                    "status": "no_data"
                    if not day_meals
                    else "complete"
                    if complete
                    else "incomplete",
                    "meal_count": len(day_meals),
                    "totals": totals,
                    "goal": goal,
                    "in_goal": match if day < today else None,
                    "preliminary_in_goal": match if day == today else None,
                    "latest_weight": latest,
                    "weight_count": len(points),
                }
            )
            day += timedelta(days=1)
        weight_days = [point for point in daily if point["latest_weight"] is not None]
        change = None
        if len(weight_days) >= 2:
            change = canonical(
                Decimal(weight_days[-1]["latest_weight"]["weight_kg"])
                - Decimal(weight_days[0]["latest_weight"]["weight_kg"])
            )
    return {
        "daily": daily,
        "averages": {
            field: {"value": rounded_average(values[field]), "day_count": len(values[field])}
            for field in FIELDS
        },
        "complete_day_count": sum(
            point["closed"] and point["effective_complete"] for point in daily
        ),
        "days_with_meals": sum(point["meal_count"] > 0 for point in daily),
        "goal_eligible_day_count": sum(point["in_goal"] is not None for point in daily),
        "in_goal_day_count": sum(point["in_goal"] is True for point in daily),
        "weight": {
            "observation_count": sum(point["weight_count"] for point in daily),
            "day_count": len(weight_days),
            "first_date": weight_days[0]["local_date"] if weight_days else None,
            "last_date": weight_days[-1]["local_date"] if weight_days else None,
            "change_kg": change,
        },
    }


def statistics(session, owner_id, days, *, expected_generation=None):
    """Caller must establish REPEATABLE READ before any authentication SQL."""
    session.execute(text(f"SET LOCAL statement_timeout = '{STATISTICS_STATEMENT_TIMEOUT_MS}ms'"))
    account = lock_account(session, owner_id, expected_generation)
    profile = session.scalar(
        select(Profile).where(Profile.owner_id == owner_id, Profile.deleted_at.is_(None))
    )
    if profile is None:
        raise DomainError(409, "profile_required")
    as_of = database_now(session)
    start, today = statistics_window(as_of, profile.time_zone, days)
    timeline = session.get(GoalTimeline, owner_id)
    revision = timeline.revision if timeline else 0
    resolved = goal_for_dates(
        session, owner_id, [start + timedelta(days=i) for i in range(days)], revision
    )
    goals = {
        day: {
            "entity_id": str(goal.id),
            "timeline_revision": goal.timeline_revision,
            "effective_from": goal.effective_from.isoformat(),
            "energy_kcal": canonical(goal.energy_kcal),
        }
        if goal
        else None
        for day, goal in resolved.items()
    }
    declarations, meals, weights = window_inputs(session, owner_id, start, today)
    counter = session.get(SyncCounter, owner_id)
    return {
        "account_id": str(account.id),
        "account_generation": account.generation,
        "sync_epoch": str(current_epoch(session)),
        "as_of": utc_text(as_of),
        "time_zone": profile.time_zone,
        "profile_revision": profile.revision,
        "goal_timeline_revision": revision,
        "server_position": counter.position if counter else 0,
        "from": start.isoformat(),
        "to": today.isoformat(),
        "days": days,
        "statistics_version": "statistics_v1",
        "goal_rule": "goal_band_v1",
        **build_statistics(start, today, declarations, meals, weights, goals),
    }
