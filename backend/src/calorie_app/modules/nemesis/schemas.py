"""Strict Nemesis wire contracts; no participant authority or source statistics."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, model_validator

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
