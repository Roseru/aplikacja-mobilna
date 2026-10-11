"""Deterministic regularity_v1 facts and bounded all-history badge witnesses."""

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from calorie_app.modules.diary.validation import effective_complete, meal_totals

RULE_VERSION = "regularity_v1"
BADGE_CODES = {
    "complete_streak_10": 10,
    "in_goal_streak_10": 10,
    "weight_days_4_14": 4,
    "ration_days_5": 5,
}


@dataclass(frozen=True)
class DayEvaluation:
    effective_complete: bool
    in_goal: bool | None
    candidate_points: int


def day_candidate_points(effective_complete: bool, in_goal: bool | None) -> int:
    """Points have no dependence on meal count, deficit size, or badges."""
    return int(effective_complete) + int(effective_complete and in_goal is True)


def evaluate_day(declared_complete: bool, meals: list[dict], goal_energy) -> DayEvaluation:
    """Use the existing effective-completeness and nutrition_v1 Decimal rules."""
    complete = effective_complete(declared_complete, meals)
    in_goal = None
    if complete and goal_energy is not None:
        target = Decimal(goal_energy)
        if target.is_finite() and target > 0:
            energy = Decimal(
                meal_totals([item for meal in meals for item in meal["items"]])["energy_kcal"][
                    "known_sum"
                ]
            )
            with localcontext() as context:
                context.prec = 50
                in_goal = target * Decimal("0.9") <= energy <= target * Decimal("1.1")
    return DayEvaluation(complete, in_goal, day_candidate_points(complete, in_goal))


def rank_for_points(points: int) -> str:
    if type(points) is not int or points < 0:
        raise ValueError("invalid_points")
    if points < 20:
        return "Rekrut"
    if points < 60:
        return "Szeregowy"
    if points < 120:
        return "Kapral"
    return "Sier\u017cant"


def ration_meal_qualifies(meal: Mapping) -> bool:
    """Saved ration provenance plus actual positive consumed component only.

    Legacy positive items whose ration_component_position is null deliberately
    stay ineligible. Nutrition/energy are irrelevant to this independent badge.
    Callers load only live source meals; no current catalog lookup occurs here.
    """
    if not meal.get("ration") or meal.get("deleted_at") is not None:
        return False
    for item in meal.get("items", ()):
        position = item.get("ration_component_position")
        if type(position) is int and position > 0 and Decimal(item["quantity"]["amount"]) > 0:
            return True
    return False


@dataclass(frozen=True)
class BadgeDay:
    local_date: date
    complete: bool = False
    in_goal: bool = False
    weight: bool = False
    ration: bool = False
    closed: bool = True


@dataclass(frozen=True)
class BadgeEvaluation:
    active: bool
    witness: tuple[date, ...]
    progress: int
    target: int


def reduce_badges(days: Iterable[BadgeDay]) -> dict[str, BadgeEvaluation]:
    """Consume distinct ascending dates once; keep at most 58 date references.

    Complete/in_goal eligibility can include an open date for progress; only
    closed dates confirm their streaks. Weight/ration flags denote independently
    mature source dates, even where a DiaryDay with another zone remains open.
    Progress is the best historical partial witness, capped at each target.
    The first minimal valid witness wins deterministically; scanning continues
    to verify order without retaining account history or all alternatives.
    """
    witnesses = {code: () for code in BADGE_CODES}
    progress = dict.fromkeys(BADGE_CODES, 0)
    confirmed = {code: deque(maxlen=10) for code in BADGE_CODES if "streak" in code}
    preliminary = dict.fromkeys(confirmed, 0)
    weights = deque(maxlen=4)
    rations = []
    previous = None
    for fact in days:
        day = fact.local_date
        if previous is not None and day <= previous:
            raise ValueError("badge_dates_must_be_distinct_and_ordered")
        adjacent = previous is None or day.toordinal() == previous.toordinal() + 1
        for code, qualifies in (
            ("complete_streak_10", fact.complete),
            ("in_goal_streak_10", fact.in_goal),
        ):
            preliminary[code] = (
                min(10, preliminary[code] + 1) if adjacent and qualifies else int(qualifies)
            )
            progress[code] = max(progress[code], preliminary[code])
            if not adjacent or not qualifies or not fact.closed:
                confirmed[code].clear()
            if qualifies and fact.closed:
                confirmed[code].append(day)
            if len(confirmed[code]) == 10 and not witnesses[code]:
                witnesses[code] = tuple(confirmed[code])
        if fact.weight:
            while weights and day.toordinal() - weights[0].toordinal() > 13:
                weights.popleft()
            weights.append(day)
            progress["weight_days_4_14"] = max(progress["weight_days_4_14"], len(weights))
            if len(weights) == 4 and not witnesses["weight_days_4_14"]:
                witnesses["weight_days_4_14"] = tuple(weights)
        if fact.ration and len(rations) < 5:
            rations.append(day)
            progress["ration_days_5"] = len(rations)
            if len(rations) == 5:
                witnesses["ration_days_5"] = tuple(rations)
        previous = day
    return {
        code: BadgeEvaluation(bool(witnesses[code]), witnesses[code], progress[code], target)
        for code, target in BADGE_CODES.items()
    }
