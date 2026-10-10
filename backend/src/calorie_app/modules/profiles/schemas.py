"""Required full E0 payloads; canonical numbers and semantic civil time."""

import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    WithJsonSchema,
    model_validator,
)

from calorie_app.modules.catalog.schemas import (
    DecimalValue,
    PositiveDecimal,
    Revision,
    Timestamp,
    Uuid,
)


def time_zone(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError("IANA time zone required")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("IANA time zone required") from None
    return value


def local_date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("ISO calendar date required")
    return date.fromisoformat(value)


TimeZone = Annotated[
    str,
    BeforeValidator(time_zone),
    Field(max_length=100),
    WithJsonSchema({"type": "string", "format": "iana-time-zone", "maxLength": 100}),
]
LocalDate = Annotated[date, BeforeValidator(local_date)]
ActivityClass = Literal["stationary", "line", "commando"]
TimelineRevision = Annotated[StrictInt, Field(ge=0, le=2147483647)]
COMPUTED_PATTERN = r"^(0|[1-9][0-9]{0,5})(\.[0-9]{0,11}[1-9])?$"


def computed(value):
    if not isinstance(value, str) or re.fullmatch(COMPUTED_PATTERN, value) is None:
        raise ValueError("Canonical computed decimal required")
    if Decimal(value) <= 0:
        raise ValueError("Positive computed decimal required")
    return value


ComputedDecimal = Annotated[
    str, BeforeValidator(computed), WithJsonSchema({"type": "string", "pattern": COMPUTED_PATTERN})
]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ProfilePayload(DTO):
    pseudonym: str = Field(strict=True, min_length=1, max_length=80)
    height_cm: Annotated[PositiveDecimal, Field(le=300)] | None
    activity_class: ActivityClass
    time_zone: TimeZone


class EstimateInput(DTO):
    age_years: Annotated[StrictInt, Field(ge=18, le=120)]
    height_cm: Annotated[PositiveDecimal, Field(le=300)]
    weight_kg: Annotated[PositiveDecimal, Field(le=1000)]
    equation_variant: Literal["plus_5", "minus_161"]
    activity_class: ActivityClass


class Estimate(DTO):
    method: Literal["mifflin_pal_v1"]
    input: EstimateInput
    resting_kcal: ComputedDecimal
    pal: Literal["1.5", "1.8", "2.2"]
    maintenance_kcal: ComputedDecimal
    estimated_at: Timestamp

    @model_validator(mode="after")
    def consistent_estimate(self) -> Self:
        with localcontext() as context:
            context.prec = 50
            data = self.input
            resting = (
                Decimal(10) * data.weight_kg
                + Decimal("6.25") * data.height_cm
                - Decimal(5) * data.age_years
                + Decimal(5 if data.equation_variant == "plus_5" else -161)
            )
            pal = {"stationary": "1.5", "line": "1.8", "commando": "2.2"}[data.activity_class]
            if (
                self.pal != pal
                or Decimal(self.resting_kcal) != resting
                or Decimal(self.maintenance_kcal) != resting * Decimal(pal)
            ):
                raise ValueError("Estimate must match its exact input and method")
        return self


class GoalPayload(DTO):
    effective_from: LocalDate
    decided_at: Timestamp
    time_zone: TimeZone
    goal_type: Literal["reduce", "maintain", "gain"]
    energy_kcal: Annotated[PositiveDecimal, Field(le=20000)]
    protein_g: Annotated[DecimalValue, Field(le=5000)] | None
    fat_g: Annotated[DecimalValue, Field(le=5000)] | None
    carbs_g: Annotated[DecimalValue, Field(le=5000)] | None
    activity_class: ActivityClass
    estimate: Estimate | None
    timeline_base_revision: TimelineRevision
    reason: Literal["user_decision", "history_correction"]
    correction_of: Uuid | None

    @model_validator(mode="after")
    def decision_audit(self) -> Self:
        day = datetime.fromisoformat(self.decided_at).astimezone(ZoneInfo(self.time_zone)).date()
        if self.reason == "user_decision":
            if self.correction_of is not None or self.effective_from < day:
                raise ValueError("New decision must apply today or later and not correct a version")
        elif self.correction_of is None:
            raise ValueError("History correction requires correction_of")
        return self


class ConsentInput(DTO):
    ranking: StrictBool
    automatic_energy_adjustment: StrictBool


class Consent(ConsentInput):
    revision: Revision
    updated_at: Timestamp


class Bootstrap(DTO):
    account_id: Uuid
    sync_epoch: Uuid
    account_generation: Revision
    server_time: Timestamp


class ProfileRecord(DTO):
    entity_id: Uuid
    revision: Revision
    payload: ProfilePayload


class ProfileRead(DTO):
    account_id: Uuid
    sync_epoch: Uuid
    profile: ProfileRecord | None
    consents: Consent
    goal_timeline_revision: TimelineRevision


class GoalRecord(DTO):
    entity_id: Uuid
    revision: Revision
    payload: GoalPayload


class GoalPage(DTO):
    items: list[GoalRecord] = Field(max_length=500)
    next_page_token: str | None = Field(min_length=1, max_length=4096)
    sync_epoch: Uuid


class GoalQuery(DTO):
    limit: int = Field(default=100, ge=1, le=500)
    page_token: str | None = Field(default=None, min_length=1, max_length=4096)
