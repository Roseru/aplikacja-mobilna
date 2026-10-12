"""Explicit source provenance and ordered projection extension boundary."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class SourceMutationContext:
    owner_id: UUID
    source_kind: str
    entity_id: UUID
    old_dates: tuple[date, ...]
    new_dates: tuple[date, ...]
    old_revision: int | None
    new_revision: int
    source_position_before: int
    source_position: int
    goal_axis_changed: bool = False
    goal_axis_revision_before: int | None = None
    goal_axis_revision: int | None = None
    goal_probe_changed: bool = False
    qualified_at: datetime | None = None

    @property
    def affected_dates(self) -> tuple[date, ...]:
        return tuple(sorted(set(self.old_dates) | set(self.new_dates)))


class SourceProjection(Protocol):
    """Caller supplies implemented projections; no runtime plugin discovery.

    lock() holds future challenge locks in UUID order before any projection
    qualification; apply() uses the single DB qualification instant. Failure
    propagates through the source savepoint. Neither method may commit.
    """

    def lock(self, session, context: SourceMutationContext) -> None: ...

    def apply(self, session, context: SourceMutationContext) -> None: ...
