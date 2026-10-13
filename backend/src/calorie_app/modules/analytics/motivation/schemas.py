"""Strict private motivation and public, minimally disclosed ranking contracts."""

import re
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictBool, StrictInt

from calorie_app.modules.catalog.schemas import Revision, Timestamp, Uuid
from calorie_app.modules.profiles.schemas import DTO, LocalDate

Count = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
RankName = Literal["Rekrut", "Szeregowy", "Kapral", "Sierżant"]
BadgeCode = Literal["complete_streak_10", "in_goal_streak_10", "weight_days_4_14", "ration_days_5"]


def ranking_limit(value):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,2}", value):
        return int(value)
    return value


class RankingQuery(DTO):
    limit: Annotated[StrictInt, BeforeValidator(ranking_limit), Field(ge=1, le=100)] = 50
    page_token: str | None = Field(default=None, pattern=r"^rk1\.[A-Za-z0-9_-]{43}$")


class RankingEntry(DTO):
    position: Annotated[StrictInt, Field(ge=1)]
    pseudonym: str = Field(strict=True, min_length=1, max_length=80)
    points: Count
    rank: RankName
    active_badges: Annotated[StrictInt, Field(ge=0, le=4)]


class RankingPage(DTO):
    rule_version: Literal["regularity_v1"]
    pagination: Literal["live_keyset_v1"]
    as_of: Timestamp
    items: list[RankingEntry] = Field(max_length=100)
    has_more: StrictBool
    next_page_token: str | None = Field(pattern=r"^rk1\.[A-Za-z0-9_-]{43}$")
    cursor_expires_at: Timestamp | None


class MotivationBadge(DTO):
    code: BadgeCode
    rule_version: Literal["regularity_v1"]
    status: Literal["pending", "final", "revoked"]
    progress: Annotated[StrictInt, Field(ge=0, le=10)]
    required: Annotated[StrictInt, Field(ge=1, le=10)]
    witness_dates: list[LocalDate] = Field(max_length=10)
    first_awarded_at: Timestamp | None
    activated_at: Timestamp | None
    revoked_at: Timestamp | None


class MotivationRanking(DTO):
    requested: StrictBool
    effective: StrictBool
    pending_consent_refresh: StrictBool
    consent_epoch: Uuid
    own_position: Annotated[StrictInt, Field(ge=1)] | None


class MotivationRead(DTO):
    account_generation: Revision
    sync_epoch: Uuid
    as_of: Timestamp
    rule_version: Literal["regularity_v1"]
    revision: Count
    source_position: Count
    status: Literal["pending_backfill", "pending_materialization", "final"]
    points: Count | None
    rank: RankName | None
    badges: list[MotivationBadge] = Field(min_length=4, max_length=4)
    ranking: MotivationRanking
