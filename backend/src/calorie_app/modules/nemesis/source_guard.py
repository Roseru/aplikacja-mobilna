"""One ordered source lock phase for Nemesis, before shared qualification.

The caller has authenticated the principal and locked its account and counter.
The database orchestrator revalidates provenance and the complete challenge plan,
refreshes motivation exactly once and writes all eligible Nemesis projections
with its single DB qualification. Apply only verifies that specific invocation.
"""

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.motivation.context import SourceMutationContext

_SOURCE_KINDS = frozenset({"profile", "meal", "diary_day", "weight", "goal"})


@dataclass(frozen=True)
class SourceProvenance:
    owner_id: UUID
    account_generation: int
    sync_epoch: UUID

    def __post_init__(self):
        if (
            not isinstance(self.owner_id, UUID)
            or not isinstance(self.sync_epoch, UUID)
            or type(self.account_generation) is not int
            or not 1 <= self.account_generation <= 2147483647
        ):
            raise ValueError("invalid Nemesis source provenance")


@dataclass(frozen=True)
class LockedChallenge:
    id: UUID
    status: str
    start_date: date
    end_date: date  # Exclusive, like the accepted period.
    time_zone: str
    deadline_at: datetime


@dataclass(frozen=True)
class SourceLockPlan:
    provenance: SourceProvenance
    source: SourceMutationContext
    challenges: tuple[LockedChallenge, ...]


def _locked_challenge(row):
    return LockedChallenge(
        id=UUID(str(row["id"])),
        status=row["status"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]),
        time_zone=row["time_zone"],
        deadline_at=datetime.fromisoformat(row["deadline_at"].replace("Z", "+00:00")),
    )


class NemesisSourceProjection:
    """The sole aggregate extension owning all Nemesis challenge locks.

    Instantiate once per source operation; do not register another challenge
    locking extension. The DB orchestrator consumes this immutable plan;
    apply cannot discover or acquire more locks. Existing goal axes and weight
    zones are deliberately unrestricted. Weight discovery is conservative:
    old source local_dates cannot describe the overwritten UTC instant.
    """

    def __init__(self, provenance: SourceProvenance):
        self.provenance = provenance
        self._plan = None
        self._session = None
        self._transaction = None
        self._savepoint = None
        self._qualified_at = None

    @property
    def plan(self) -> SourceLockPlan:
        if self._plan is None:
            raise DomainError(503, "nemesis_source_unqualified")
        return self._plan

    def lock(self, session, context: SourceMutationContext) -> None:
        if (
            self._plan is not None
            or context.owner_id != self.provenance.owner_id
            or context.source_kind not in _SOURCE_KINDS
            or context.qualified_at is not None
            or session.get_transaction() is None
        ):
            raise DomainError(503, "nemesis_source_unqualified")
        # The source must already be flushed; all guard checks and challenge
        # locks finish before shared e8_refresh assigns qualified_at.
        session.flush()
        rows = session.scalar(
            text(
                "SELECT app.e8n_source_lock(:owner, :generation, :epoch, :kind, "
                "CAST(:old_dates AS date[]), CAST(:new_dates AS date[]), :goal_axis_changed)"
            ),
            {
                "owner": self.provenance.owner_id,
                "generation": self.provenance.account_generation,
                "epoch": self.provenance.sync_epoch,
                "kind": context.source_kind,
                "old_dates": list(context.old_dates),
                "new_dates": list(context.new_dates),
                "goal_axis_changed": context.goal_axis_changed,
            },
        )
        if not isinstance(rows, list):
            raise DomainError(503, "nemesis_source_unqualified")
        challenges = tuple(_locked_challenge(row) for row in rows)
        ids = tuple(row.id for row in challenges)
        if ids != tuple(sorted(set(ids))):
            raise DomainError(503, "nemesis_source_unqualified")
        self._plan = SourceLockPlan(self.provenance, context, challenges)
        self._session = session
        self._transaction = session.get_transaction()
        self._savepoint = session.get_nested_transaction()

    def refresh(self, session, context: SourceMutationContext) -> datetime:
        """The explicit replacement for plain motivation refresh, exactly once."""
        if (
            self._plan is None
            or session is not self._session
            or session.get_transaction() is not self._transaction
            or session.get_nested_transaction() is not self._savepoint
            or context != self._plan.source
            or self._qualified_at is not None
        ):
            raise DomainError(503, "nemesis_source_unqualified")
        source = asdict(context)
        source.pop("qualified_at")
        for name in ("owner_id", "entity_id"):
            source[name] = str(source[name])
        for name in ("old_dates", "new_dates"):
            source[name] = [value.isoformat() for value in source[name]]
        q = session.scalar(
            text(
                "SELECT app.e8n_source_refresh(:owner,:generation,:epoch,"
                "CAST(:source AS jsonb),CAST(:ids AS uuid[]))"
            ),
            {
                "owner": self.provenance.owner_id,
                "generation": self.provenance.account_generation,
                "epoch": self.provenance.sync_epoch,
                "source": json.dumps(source, allow_nan=False),
                "ids": [row.id for row in self._plan.challenges],
            },
        )
        if not isinstance(q, datetime) or q.tzinfo is None or q.utcoffset() is None:
            raise DomainError(503, "nemesis_source_unqualified")
        self._qualified_at = q
        return q

    def apply(self, session, context: SourceMutationContext) -> None:
        qualified = context.qualified_at
        if (
            self._plan is None
            or session is not self._session
            or session.get_transaction() is not self._transaction
            or session.get_nested_transaction() is not self._savepoint
            or self._qualified_at is None
            or qualified != self._qualified_at
            or qualified is None
            or qualified.tzinfo is None
            or qualified.utcoffset() is None
            or replace(context, qualified_at=None) != self._plan.source
        ):
            raise DomainError(503, "nemesis_source_unqualified")
        # The same orchestrator already wrote projection within this savepoint.
        # This phase adds no SQL, lock discovery, external IO or commit.
