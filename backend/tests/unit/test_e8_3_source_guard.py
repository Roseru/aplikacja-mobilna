"""The immutable seam and the single Nemesis challenge lock phase."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.motivation.context import SourceMutationContext
from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection, SourceProvenance


class PrivateSession:
    def __init__(self, rows=None):
        self.transaction = object()
        self.savepoint = None
        self.rows = rows or []
        self.calls = []
        self.q = datetime(2026, 10, 12, tzinfo=UTC)

    def get_transaction(self):
        return self.transaction

    def get_nested_transaction(self):
        return self.savepoint

    def flush(self):
        self.calls.append(("flush",))

    def scalar(self, statement, values):
        self.calls.append((str(statement), values))
        return self.q if "app.e8n_source_refresh" in str(statement) else self.rows


def source(owner=None, **changes):
    return replace(
        SourceMutationContext(
            owner_id=owner or uuid4(),
            source_kind="meal",
            entity_id=uuid4(),
            old_dates=(date(2026, 10, 11),),
            new_dates=(date(2026, 10, 12),),
            old_revision=1,
            new_revision=2,
            source_position_before=1,
            source_position=2,
        ),
        **changes,
    )


def projection(context):
    return NemesisSourceProjection(SourceProvenance(context.owner_id, 1, uuid4()))


def locked_row(identifier):
    return {
        "id": str(identifier),
        "status": "active",
        "start_date": "2026-10-11",
        "end_date": "2026-10-18",
        "time_zone": "Europe/Warsaw",
        "deadline_at": "2026-11-16T23:00:00Z",
    }


def test_provenance_does_not_extend_shared_frozen_context():
    context = source()
    assert "sync_epoch" not in context.__dataclass_fields__
    assert "account_generation" not in context.__dataclass_fields__
    p = projection(context)
    with pytest.raises(FrozenInstanceError):
        context.new_revision = 3
    with pytest.raises(FrozenInstanceError):
        p.provenance.account_generation = 2
    assert context.affected_dates == (date(2026, 10, 11), date(2026, 10, 12))


@pytest.mark.parametrize("generation", [0, -1, 2147483648, True, 1.0, "1"])
def test_provenance_rejects_invalid_generation(generation):
    with pytest.raises(ValueError):
        SourceProvenance(uuid4(), generation, uuid4())


def test_lock_is_one_query_and_preserves_both_dates():
    context = source()
    p, session = projection(context), PrivateSession([locked_row(UUID(int=1))])
    p.lock(session, context)
    assert len(session.calls) == 2
    assert session.calls[0] == ("flush",)
    query, args = session.calls[1]
    assert "app.e8n_source_lock" in query
    assert args["old_dates"] == [date(2026, 10, 11)]
    assert args["new_dates"] == [date(2026, 10, 12)]
    assert args["epoch"] == p.provenance.sync_epoch
    assert p.plan.provenance == p.provenance and p.plan.source is context
    assert p.plan.challenges[0].end_date == date(2026, 10, 18)
    with pytest.raises(FrozenInstanceError):
        p.plan.challenges[0].time_zone = "UTC"
    qualified = replace(context, qualified_at=p.refresh(session, context))
    p.apply(session, qualified)
    assert len(session.calls) == 3  # One orchestrator; apply never adds SQL or commit.
    assert context.qualified_at is None


@pytest.mark.parametrize("kind", ["profile", "meal", "diary_day", "weight", "goal"])
def test_supported_sources_have_same_single_lock_phase(kind):
    context = source(source_kind=kind, goal_axis_changed=kind == "goal")
    p, session = projection(context), PrivateSession()
    p.lock(session, context)
    assert session.calls[1][1]["kind"] == kind
    assert session.calls[1][1]["goal_axis_changed"] == (kind == "goal")
    p.apply(session, replace(context, qualified_at=p.refresh(session, context)))


@pytest.mark.parametrize(
    "rows",
    [
        [locked_row(UUID(int=2)), locked_row(UUID(int=1))],
        [locked_row(UUID(int=1)), locked_row(UUID(int=1))],
    ],
)
def test_disordered_or_duplicate_lock_plan_fails_closed(rows):
    context = source()
    with pytest.raises(DomainError) as rejected:
        projection(context).lock(PrivateSession(rows), context)
    assert rejected.value.code == "nemesis_source_unqualified"


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": UUID(int=1)},
        {"source_kind": "unknown"},
        {"qualified_at": datetime.now(UTC)},
    ],
)
def test_invalid_lock_context_never_calls_db(change):
    context = source()
    p, session = projection(context), PrivateSession()
    with pytest.raises(DomainError):
        p.lock(session, replace(context, **change))
    assert session.calls == []


def test_no_transaction_or_second_lock_refused():
    context = source()
    p, session = projection(context), PrivateSession()
    session.transaction = None
    with pytest.raises(DomainError):
        p.lock(session, context)
    session.transaction = object()
    p.lock(session, context)
    with pytest.raises(DomainError):
        p.lock(session, context)
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"qualified_at": None},
        {"qualified_at": datetime(2026, 1, 1)},
        {"new_revision": 3, "qualified_at": datetime.now(UTC)},
        {"old_dates": (), "qualified_at": datetime.now(UTC)},
    ],
)
def test_apply_rejects_missing_qualification_or_changed_provenance(change):
    context = source()
    p, session = projection(context), PrivateSession()
    p.lock(session, context)
    with pytest.raises(DomainError):
        p.apply(session, replace(context, **change))
    assert len(session.calls) == 2


def test_apply_rejects_new_transaction_or_session():
    context = source()
    p, session = projection(context), PrivateSession()
    qualified = replace(context, qualified_at=datetime.now(UTC))
    p.lock(session, context)
    with pytest.raises(DomainError):
        p.apply(PrivateSession(), qualified)
    session.transaction = object()
    with pytest.raises(DomainError):
        p.apply(session, qualified)


def test_apply_before_lock_and_access_to_unprepared_plan_fail_closed():
    context = source()
    p = projection(context)
    with pytest.raises(DomainError):
        _ = p.plan
    with pytest.raises(DomainError):
        p.apply(PrivateSession(), replace(context, qualified_at=datetime.now(UTC)))


def test_apply_rejects_ended_or_replaced_source_savepoint():
    context = source()
    p, session = projection(context), PrivateSession()
    session.savepoint = object()
    p.lock(session, context)
    qualified = replace(context, qualified_at=p.refresh(session, context))
    p.apply(session, qualified)
    for replacement in (None, object()):
        session.savepoint = replacement
        with pytest.raises(DomainError):
            p.apply(session, qualified)
    assert len(session.calls) == 3


def test_apply_requires_exact_orchestrator_q_and_refresh_cannot_repeat():
    context = source()
    p, session = projection(context), PrivateSession()
    p.lock(session, context)
    with pytest.raises(DomainError):
        p.apply(session, replace(context, qualified_at=session.q))
    q = p.refresh(session, context)
    with pytest.raises(DomainError):
        p.refresh(session, context)
    with pytest.raises(DomainError):
        p.apply(session, replace(context, qualified_at=q.replace(year=2025)))
    p.apply(session, replace(context, qualified_at=q))
    assert len(session.calls) == 3
    assert "app.e8n_source_refresh" in session.calls[-1][0]
