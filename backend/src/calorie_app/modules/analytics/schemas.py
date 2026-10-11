"""Private statistics_v1 read models and exact decimal output types."""

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictBool, StrictInt, WithJsonSchema

from calorie_app.modules.catalog.schemas import Revision, Timestamp, Uuid
from calorie_app.modules.profiles.schemas import DTO, LocalDate, TimelineRevision, TimeZone

RESULT_PATTERN = r"^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$"


def result_decimal(value):
    if not isinstance(value, str) or re.fullmatch(RESULT_PATTERN, value) is None:
        raise ValueError("Canonical result decimal required")
    if value == "-0" or len(value) > 128 or not Decimal(value).is_finite():
        raise ValueError("Canonical result decimal required")
    return value


ResultDecimal = Annotated[
    str,
    BeforeValidator(result_decimal),
    WithJsonSchema({"type": "string", "pattern": RESULT_PATTERN, "maxLength": 128}),
]


def nonnegative_result(value):
    result_decimal(value)
    if Decimal(value) < 0:
        raise ValueError("Nonnegative result decimal required")
    return value


NonnegativeResultDecimal = Annotated[
    str,
    BeforeValidator(nonnegative_result),
    WithJsonSchema(
        {"type": "string", "pattern": "^" + RESULT_PATTERN.removeprefix("^-?"), "maxLength": 128}
    ),
]
Count = Annotated[StrictInt, Field(ge=0)]


def statistics_days(value):
    if isinstance(value, str) and value in ("7", "30", "90"):
        return int(value)
    return value


class StatisticsQuery(DTO):
    days: Annotated[Literal[7, 30, 90], BeforeValidator(statistics_days)] = 30


class FieldTotal(DTO):
    known_sum: NonnegativeResultDecimal | None
    complete: StrictBool
    known_count: Count
    missing_count: Count


class NutrientTotals(DTO):
    energy_kcal: FieldTotal
    protein_g: FieldTotal
    fat_g: FieldTotal
    carbs_g: FieldTotal


class Average(DTO):
    value: NonnegativeResultDecimal | None
    day_count: Count


class NutrientAverages(DTO):
    energy_kcal: Average
    protein_g: Average
    fat_g: Average
    carbs_g: Average


class HistoricalGoal(DTO):
    entity_id: Uuid
    timeline_revision: Revision
    effective_from: LocalDate
    energy_kcal: NonnegativeResultDecimal


class DailyWeight(DTO):
    entity_id: Uuid
    occurred_at: Timestamp
    weight_kg: NonnegativeResultDecimal


class StatisticsDay(DTO):
    local_date: LocalDate
    closed: StrictBool
    declared_complete: StrictBool
    effective_complete: StrictBool
    status: Literal["no_data", "incomplete", "complete"]
    meal_count: Count
    totals: NutrientTotals
    goal: HistoricalGoal | None
    in_goal: StrictBool | None
    preliminary_in_goal: StrictBool | None
    latest_weight: DailyWeight | None
    weight_count: Count


class WeightSummary(DTO):
    observation_count: Count
    day_count: Count
    first_date: LocalDate | None
    last_date: LocalDate | None
    change_kg: ResultDecimal | None


class Statistics(DTO):
    account_id: Uuid
    account_generation: Revision
    sync_epoch: Uuid
    as_of: Timestamp
    time_zone: TimeZone
    profile_revision: Revision
    goal_timeline_revision: TimelineRevision
    server_position: Count
    from_date: LocalDate = Field(alias="from")
    to_date: LocalDate = Field(alias="to")
    days: Literal[7, 30, 90]
    statistics_version: Literal["statistics_v1"]
    goal_rule: Literal["goal_band_v1"]
    daily: list[StatisticsDay] = Field(min_length=7, max_length=90)
    averages: NutrientAverages
    complete_day_count: Count
    days_with_meals: Count
    goal_eligible_day_count: Count
    in_goal_day_count: Count
    weight: WeightSummary
