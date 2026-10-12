"""Strict Nemesis wire contracts; no participant authority or source statistics."""

import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
    WithJsonSchema,
    model_validator,
)

from calorie_app.core.wire import validate_json_strings
from calorie_app.modules.catalog.schemas import Revision, Timestamp, Uuid
from calorie_app.modules.nemesis.addressing import validate_share_code
from calorie_app.modules.profiles.schemas import LocalDate, TimeZone

MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def require_regularities(value):
    if value is not True:
        raise ValueError("regularity_scope_required")
    return value


def require_duration(value):
    if type(value) is not int or value not in (7, 30, 90):
        raise ValueError("invalid_nemesis_duration")
    return value


def validate_body_size(body: bytes) -> None:
    """The router calls this on actual bytes, including whitespace, before JSON parsing."""
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("nemesis_payload_too_large")


class NemesisDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def safe_text(cls, value):
        validate_json_strings(value)
        return value


class NemesisScope(NemesisDTO):
    regularity: Annotated[Literal[True], BeforeValidator(require_regularities)]
    weight_change: StrictBool = False
    mean_deficit: StrictBool = False


class NemesisTerms(NemesisDTO):
    rule_version: Literal["regularity_v1"]
    duration_days: Annotated[Literal[7, 30, 90], BeforeValidator(require_duration)] = 30
    time_zone: TimeZone = "Europe/Warsaw"
    scope: NemesisScope


ShareCode = Annotated[
    str, BeforeValidator(validate_share_code), Field(strict=True, min_length=43, max_length=43)
]


class CreateNemesis(NemesisDTO):
    destination_code: ShareCode = Field(repr=False)
    terms: NemesisTerms


class AcceptNemesis(NemesisDTO):
    terms: NemesisTerms


CancelReason = Literal["withdrawn", "declined", "sharing_revoked"]


class CancelNemesis(NemesisDTO):
    reason: CancelReason


class EmptyNemesisOperation(NemesisDTO):
    pass


class ShareCodeReceipt(NemesisDTO):
    destination_code: ShareCode = Field(repr=False)
    issued_at: Timestamp
    expires_at: Timestamp


class RevokeCodeReceipt(NemesisDTO):
    revoked: Literal[True]


class NemesisMetadata(NemesisDTO):
    id: Uuid
    revision: Revision
    role: Literal["inviter", "invitee"]
    status: Literal["invited", "active", "finished", "cancelled"]
    terms: NemesisTerms
    invited_at: Timestamp
    expires_at: Timestamp
    accepted_at: Timestamp | None
    start_date: LocalDate | None
    end_date: LocalDate | None = Field(description="Exclusive calendar date boundary")
    start_at: Timestamp | None
    end_at: Timestamp | None
    deadline: Timestamp | None
    result_status: Literal["provisional", "final"] | None
    cancel_reason: (
        Literal["withdrawn", "declined", "sharing_revoked", "expired", "deleted", "restore"] | None
    )
    partner_pseudonym: str | None = Field(max_length=80, strict=True)


class NemesisPage(NemesisDTO):
    items: list[NemesisMetadata] = Field(max_length=100)
    next_cursor: str | None = Field(max_length=128)


def validate_response_size(payload: dict) -> None:
    if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > (
        MAX_RESPONSE_BYTES
    ):
        raise ValueError("nemesis_response_too_large")


# Statistics are a separate additive contract, never sync-v1 entities or receipts.
SIGNED_PERCENT_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{0,11}[1-9])?$"


def signed_percent(value):
    """Wire percentages are canonical strings; no coercion or rounding at read."""
    if (
        not isinstance(value, str)
        or re.fullmatch(SIGNED_PERCENT_PATTERN, value) is None
        or value == "-0"
    ):
        raise ValueError("invalid_signed_percent")
    return Decimal(value)


def canonical_percent(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("invalid_signed_percent")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


SignedPercent = Annotated[
    Decimal,
    BeforeValidator(signed_percent),
    PlainSerializer(canonical_percent, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": SIGNED_PERCENT_PATTERN, "not": {"const": "-0"}}),
]
NemesisReadRevision = Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
DayCount = Annotated[StrictInt, Field(ge=0, le=90)]


class HiddenMetric(NemesisDTO):
    state: Literal["hidden"]


class WeightInsufficient(NemesisDTO):
    state: Literal["insufficient_data"]
    value: None
    observed_days: Annotated[StrictInt, Field(ge=0, le=1)]


class WeightAvailable(NemesisDTO):
    state: Literal["available"]
    value: SignedPercent
    observed_days: Annotated[StrictInt, Field(ge=2, le=90)]
    first_date: LocalDate
    last_date: LocalDate

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.first_date >= self.last_date:
            raise ValueError("weight_dates_must_be_distinct_and_ordered")
        span = (self.last_date - self.first_date).days + 1
        if self.observed_days > span:
            raise ValueError("weight_observations_exceed_calendar_dates")
        return self


WeightMetric = Annotated[
    HiddenMetric | WeightInsufficient | WeightAvailable, Field(discriminator="state")
]


class DeficitInsufficient(NemesisDTO):
    state: Literal["insufficient_data"]
    value: None
    eligible_days: Annotated[StrictInt, Field(ge=0, le=0)]


class DeficitAvailable(NemesisDTO):
    state: Literal["available"]
    value: SignedPercent
    eligible_days: Annotated[StrictInt, Field(ge=1, le=90)]


DeficitMetric = Annotated[
    HiddenMetric | DeficitInsufficient | DeficitAvailable, Field(discriminator="state")
]


class NemesisRegularity(NemesisDTO):
    points: Annotated[StrictInt, Field(ge=0, le=180)]
    closed_days: Annotated[StrictInt, Field(ge=1, le=90)]
    complete_days: DayCount
    days_in_goal: DayCount

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if not self.days_in_goal <= self.complete_days <= self.closed_days:
            raise ValueError("invalid_regularity_counts")
        if self.points != self.complete_days + self.days_in_goal:
            raise ValueError("invalid_regularity_points")
        return self


class NemesisParticipantStatistics(NemesisDTO):
    regularity: NemesisRegularity
    weight_change: WeightMetric
    mean_deficit: DeficitMetric

    @model_validator(mode="after")
    def metric_counts(self) -> Self:
        closed = self.regularity.closed_days
        if self.weight_change.state != "hidden" and self.weight_change.observed_days > closed:
            raise ValueError("weight_count_exceeds_closed_days")
        if (
            self.mean_deficit.state != "hidden"
            and self.mean_deficit.eligible_days > self.regularity.complete_days
        ):
            raise ValueError("deficit_count_exceeds_complete_days")
        return self


class NemesisStatisticsCommon(NemesisDTO):
    id: Uuid
    revision: NemesisReadRevision
    rule_version: Literal["regularity_v1"]
    as_of: Timestamp
    time_zone: TimeZone
    start_date: LocalDate
    end_date: LocalDate = Field(description="Exclusive calendar date boundary")
    deadline: Timestamp

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        duration = (self.end_date - self.start_date).days
        if duration not in (7, 30, 90):
            raise ValueError("invalid_nemesis_statistics_period")
        return self


class NemesisStatisticsPending(NemesisStatisticsCommon):
    status: Literal["pending"]


class NemesisStatisticsReady(NemesisStatisticsCommon):
    self: NemesisParticipantStatistics
    opponent: NemesisParticipantStatistics
    outcome: Literal["self_wins", "opponent_wins", "tie"]

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Self:
        own = self.self.regularity
        peer = self.opponent.regularity
        if own.closed_days != peer.closed_days:
            raise ValueError("inconsistent_snapshot_closed_days")
        duration = (self.end_date - self.start_date).days
        if own.closed_days > duration:
            raise ValueError("closed_days_exceed_period")
        expected = (
            "self_wins"
            if own.points > peer.points
            else "opponent_wins"
            if own.points < peer.points
            else "tie"
        )
        if self.outcome != expected:
            raise ValueError("outcome_does_not_match_points")
        for participant in (self.self, self.opponent):
            metric = participant.weight_change
            if metric.state == "available" and not (
                self.start_date <= metric.first_date < metric.last_date < self.end_date
            ):
                raise ValueError("weight_dates_outside_period")
        return self


class NemesisStatisticsProvisional(NemesisStatisticsReady):
    status: Literal["provisional"]


class NemesisStatisticsFinal(NemesisStatisticsReady):
    status: Literal["final"]
    finalized_at: Timestamp

    @model_validator(mode="after")
    def finalization_after_deadline(self) -> Self:
        if self.self.regularity.closed_days != (self.end_date - self.start_date).days:
            raise ValueError("final_requires_all_period_dates_mature")
        finalized = datetime.fromisoformat(self.finalized_at)
        if (
            not datetime.fromisoformat(self.deadline)
            < finalized
            <= datetime.fromisoformat(self.as_of)
        ):
            raise ValueError("invalid_finalization_time")
        return self


NemesisStatistics = Annotated[
    NemesisStatisticsPending | NemesisStatisticsProvisional | NemesisStatisticsFinal,
    Field(discriminator="status"),
]
