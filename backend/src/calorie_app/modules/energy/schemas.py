"""Additive online DTOs; the existing GoalPayload remains unchanged."""

from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictInt

from calorie_app.modules.catalog.schemas import Revision, Timestamp, Uuid
from calorie_app.modules.profiles.schemas import DTO, ComputedDecimal, LocalDate, TimelineRevision


class Explanation(DTO):
    explanation: str = Field(strict=True, min_length=1, max_length=2000)
    uncertainty: Literal["low", "medium", "high"]
    suggested_class: Literal["stationary", "line", "commando"] | None


def affirmative(value):
    if value is not True:
        raise ValueError("affirmative notice required")
    return value


Affirmative = Annotated[Literal[True], BeforeValidator(affirmative)]
SnapshotHash = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class EnergyNotice(DTO):
    accepted: Affirmative
    qualified_for_v1: Affirmative
    notice_version: Literal["energy-aggregates-notice-v1"]
    aggregate_scope: Literal["energy_adjustment_v1_minimal_aggregates"]
    provider: Literal["mock", "gemini"]


class ManualNotice(EnergyNotice):
    scope: Literal["this_energy_analysis"]


class AutomaticNotice(EnergyNotice):
    scope: Literal["automatic_energy_adjustment"]


class NoticeRead(EnergyNotice):
    scope: Literal["this_energy_analysis", "automatic_energy_adjustment"]
    accepted_at: Timestamp
    snapshot_at: Timestamp
    snapshot_hash: SnapshotHash
    sync_epoch: Uuid
    account_generation: Revision
    profile_revision: Revision
    consent_revision: Revision
    baseline_id: Uuid | None
    revoked_at: Timestamp | None = None


class SnapshotContext(DTO):
    snapshot_hash: SnapshotHash
    sync_epoch: Uuid
    account_generation: Revision
    profile_revision: Revision
    goal_timeline_revision: TimelineRevision
    energy_axis_revision: TimelineRevision
    current_energy_id: Uuid | None
    consent_revision: Revision


class ContextRequest(DTO):
    sync_epoch: Uuid
    account_generation: Revision
    axis_revision: TimelineRevision


class AnalysisRequest(ContextRequest):
    notice: ManualNotice


class DecisionRequest(ContextRequest):
    id: Uuid
    revision: Revision


class AffirmRequest(ContextRequest):
    notice: AutomaticNotice
    id: Uuid
    consent_revision: Revision


class RevertRequest(ContextRequest):
    id: Uuid
    replace_id: Uuid | None


ExactBound = Annotated[str, Field(pattern=r"^[0-9]{1,7}(\.[0-9]{1,14})?$", strict=True)]


class RuleResult(DTO):
    rule_version: Literal["energy_adjustment_v1"]
    state: Literal[
        "insufficient_data",
        "energy_history_unavailable",
        "baseline_required",
        "baseline_range_conflict",
        "manual_review_required",
        "no_change",
        "ready",
    ]
    complete_days: Annotated[StrictInt, Field(ge=0, le=14)]
    weight_days: Annotated[StrictInt, Field(ge=0, le=14)]
    first_median: ComputedDecimal | None
    second_median: ComputedDecimal | None
    proposed: ComputedDecimal | None
    lower: ExactBound | None = None
    upper: ExactBound | None = None


class EnergyPayload(DTO):
    effective_from: LocalDate
    maintenance_kcal: ComputedDecimal
    method: Literal["mifflin_pal_v1", "energy_adjustment_v1", "energy_revert_v1"]
    source: Literal["legacy", "manual", "automatic", "revert"]
    source_id: Uuid
    supersedes: Uuid | None
    decided_at: Timestamp
    audit: dict


class EnergyEntity(DTO):
    entity_type: Literal["energy_estimate"]
    entity_id: Uuid
    revision: Revision
    deleted: Literal[False]
    payload: EnergyPayload


class UnavailableRead(DTO):
    id: None
    revision: None
    state: Literal[
        "insufficient_data",
        "energy_history_unavailable",
        "baseline_required",
        "baseline_range_conflict",
    ]
    result: RuleResult


class AffirmRead(DTO):
    baseline_id: Uuid
    axis_revision: TimelineRevision


class HistoryPage(DTO):
    items: list[EnergyEntity] = Field(max_length=500)
    next_revision: TimelineRevision


class AnalysisRead(DTO):
    notice: NoticeRead
    source_context: SnapshotContext
    id: Uuid
    revision: Revision
    state: Literal[
        "queued",
        "running",
        "ready",
        "manual_review_required",
        "no_change",
        "failed",
        "accepted",
        "rejected",
        "expired",
        "stale",
    ]
    automatic: bool
    accepted_at: Timestamp
    created_at: Timestamp | None
    expires_at: Timestamp | None
    date_from: LocalDate
    date_to: LocalDate
    result: RuleResult
    explanation: Explanation | None
    error_code: str | None


Limit = Annotated[StrictInt, Field(ge=1, le=500)]


class AnalysisPage(DTO):
    items: list[AnalysisRead] = Field(max_length=500)


class EnergyState(DTO):
    sync_epoch: Uuid
    account_generation: Revision
    axis_revision: TimelineRevision
    current_id: Uuid | None
    baseline_id: Uuid | None
    automatic_requested: bool
    automatic_effective: bool
    automatic_notice: NoticeRead | None
    last_applied_at: Timestamp | None
    next_apply_at: Timestamp | None
