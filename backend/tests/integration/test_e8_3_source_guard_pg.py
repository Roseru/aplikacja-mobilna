"""Real PostgreSQL source guards through the explicit, unmounted E8.3 seam."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.motivation.context import SourceMutationContext
from calorie_app.modules.analytics.motivation.service import source_mutated
from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection, SourceProvenance
from calorie_app.modules.profiles.schemas import GoalPayload
from calorie_app.modules.profiles.service import create_goal
from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
TERMS = {
    "rule_version": "regularity_v1",
    "duration_days": 7,
    "time_zone": "UTC",
    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
}


@pytest.fixture(scope="module")
def private_pg():
    private = PrivatePostgres.from_environment()
    admin, api = private.engine("admin"), private.engine("api")
    with admin.connect() as c:
        assert 170000 <= int(c.scalar(text("SHOW server_version_num"))) < 180000
        assert c.scalar(text("SELECT version_num FROM app.alembic_version")) == (
            "0018_e8_nemesis_lifecycle"
        )
    with api.connect() as c:
        assert c.scalar(text("SELECT session_user")) == "calorie_app_api"
    yield admin, api
    api.dispose()
    admin.dispose()


def add_challenge(c, owners, epoch, start, *, status="active"):
    identifier = uuid4()
    start_at = datetime.combine(start, time.min, UTC)
    end_at = start_at + timedelta(days=7)
    c.execute(
        text("""INSERT INTO app.nemesis_challenges
        (id,inviter_id,invitee_id,inviter_generation,invitee_generation,sync_epoch,
         status,terms,created_at,expires_at,accepted_at,start_date,end_date,start_at,
         end_at,deadline_at,result_status)
        VALUES(:id,:a,:b,1,1,:epoch,:status,CAST(:terms AS jsonb),:created,
         :expires,:accepted,:start,:end,:start_at,:end_at,:deadline,'provisional')"""),
        {
            "id": identifier,
            "a": owners[0],
            "b": owners[1],
            "epoch": epoch,
            "status": status,
            "terms": json.dumps(TERMS),
            "created": start_at - timedelta(days=2),
            "expires": start_at + timedelta(days=5),
            "accepted": start_at - timedelta(hours=12),
            "start": start,
            "end": start + timedelta(days=7),
            "start_at": start_at,
            "end_at": end_at,
            "deadline": end_at + timedelta(days=30),
        },
    )
    if status == "active":
        for owner in sorted(owners):
            c.execute(
                text("INSERT INTO app.nemesis_slots VALUES(:owner,:id)"),
                {"owner": owner, "id": identifier},
            )
    return identifier


@pytest.fixture
def source_accounts(private_pg):
    admin, api = private_pg
    owners = (uuid4(), uuid4())
    with admin.begin() as c:
        epoch = c.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
        today = c.scalar(text("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date"))
        for owner in owners:
            c.execute(
                text("INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:issuer,:sub)"),
                {"id": owner, "issuer": "https://source.fixture.invalid", "sub": str(owner)},
            )
            c.execute(
                text("INSERT INTO app.sync_counters(owner_id,position) VALUES(:id,0)"),
                {"id": owner},
            )
            c.execute(
                text("""INSERT INTO app.user_profiles
                (id,owner_id,revision,pseudonym,activity_class,time_zone)
                VALUES(:profile,:id,1,'Fixture','stationary','UTC')"""),
                {"profile": uuid4(), "id": owner},
            )
        start = today + timedelta(days=1)
        challenge = add_challenge(c, owners, epoch, start)
    yield {
        "admin": admin,
        "api": api,
        "owners": owners,
        "epoch": epoch,
        "start": start,
        "challenge": challenge,
    }
    # Target only this fixture's accounts, never truncate a shared history.
    with admin.begin() as c:
        values = {"owners": list(owners)}
        for table in (
            "nemesis_slots",
            "nemesis_receipts",
            "nemesis_admissions",
            "nemesis_share_codes",
            "nemesis_cursors",
        ):
            column = "requester_id" if table == "nemesis_cursors" else "owner_id"
            c.execute(text(f"DELETE FROM app.{table} WHERE {column}=ANY(:owners)"), values)
        c.execute(
            text(
                "DELETE FROM app.nemesis_challenges WHERE "
                "inviter_id=ANY(:owners) OR invitee_id=ANY(:owners)"
            ),
            values,
        )
        for table in (
            "motivation_badges",
            "motivation_days",
            "motivation_accounts",
            "ranking_affirmations",
            "sync_receipts",
            "sync_changes",
            "weights",
            "meal_items",
            "meals",
            "diary_days",
            "goal_versions",
            "goal_timelines",
            "user_profiles",
            "sync_counters",
        ):
            c.execute(text(f"DELETE FROM app.{table} WHERE owner_id=ANY(:owners)"), values)
        c.execute(text("DELETE FROM app.user_accounts WHERE id=ANY(:owners)"), values)


def context(fixture, kind="meal", **changes):
    return replace(
        SourceMutationContext(
            owner_id=fixture["owners"][0],
            source_kind=kind,
            entity_id=uuid4(),
            old_dates=(fixture["start"],),
            new_dates=(fixture["start"] + timedelta(days=1),),
            old_revision=1,
            new_revision=2,
            source_position_before=0,
            source_position=1,
            goal_axis_changed=kind == "goal",
        ),
        **changes,
    )


def projection(fixture):
    return NemesisSourceProjection(SourceProvenance(fixture["owners"][0], 1, fixture["epoch"]))


def insert_day(session, fixture, day, zone="UTC"):
    session.execute(
        text("""INSERT INTO app.diary_days
        (id,owner_id,revision,local_date,time_zone,declared_complete)
        VALUES(:id,:owner,1,:day,:zone,false)"""),
        {"id": uuid4(), "owner": fixture["owners"][0], "day": day, "zone": zone},
    )


@pytest.mark.parametrize("kind", ["profile", "meal", "diary_day", "weight", "goal"])
def test_actual_seam_qualifies_and_never_mutates_shared_context(source_accounts, kind):
    f = source_accounts
    ctx, extension = context(f, kind), projection(f)
    with Session(f["api"]) as session, session.begin():
        qualified = source_mutated(session, ctx, (extension,))
        assert qualified.qualified_at is not None and qualified.qualified_at.tzinfo is not None
        assert extension.plan.challenges[0].id == f["challenge"]
        assert ctx.qualified_at is None and ctx.affected_dates == qualified.affected_dates
        assert "account_generation" not in ctx.__dataclass_fields__


@pytest.mark.parametrize("mutation", ["zone", "soft_delete", "hard_delete"])
def test_active_profile_axis_and_delete_fail_and_rollback(source_accounts, mutation):
    f = source_accounts
    with pytest.raises(DBAPIError) as refused, Session(f["api"]) as session, session.begin():
        if mutation == "zone":
            statement = "UPDATE app.user_profiles SET time_zone='Europe/Warsaw',revision=2"
        elif mutation == "soft_delete":
            statement = "UPDATE app.user_profiles SET deleted_at=clock_timestamp(),revision=2"
        else:
            statement = "DELETE FROM app.user_profiles"
        session.execute(text(statement + " WHERE owner_id=:owner"), {"owner": f["owners"][0]})
        source_mutated(session, context(f, "profile"), (projection(f),))
    assert refused.value.orig.sqlstate == ("42501" if mutation == "hard_delete" else "23514")
    with f["admin"].connect() as c:
        row = c.execute(
            text(
                "SELECT time_zone,deleted_at,revision FROM app.user_profiles WHERE owner_id=:owner"
            ),
            {"owner": f["owners"][0]},
        ).one()
        assert row == ("UTC", None, 1)
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.motivation_accounts WHERE owner_id=:owner"),
                {"owner": f["owners"][0]},
            )
            == 0
        )


@pytest.mark.parametrize("which", ["old", "new"])
@pytest.mark.parametrize("kind", ["meal", "diary_day"])
def test_move_validates_both_dates_before_qualification(source_accounts, which, kind):
    f = source_accounts
    ctx = context(f, kind)
    target = ctx.old_dates[0] if which == "old" else ctx.new_dates[0]
    with pytest.raises(DBAPIError) as refused, Session(f["api"]) as session, session.begin():
        insert_day(session, f, target, "Europe/Warsaw")
        source_mutated(session, ctx, (projection(f),))
    assert refused.value.orig.sqlstate == "23514"
    with f["admin"].connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.diary_days WHERE owner_id=:owner"),
                {"owner": f["owners"][0]},
            )
            == 0
        )


def test_zone_on_unrelated_date_does_not_block_meal(source_accounts):
    f = source_accounts
    with Session(f["api"]) as session, session.begin():
        insert_day(session, f, f["start"] - timedelta(days=30), "Europe/Warsaw")
        qualified = source_mutated(session, context(f), (projection(f),))
        assert qualified.qualified_at is not None


def test_weight_discovery_ignores_source_local_dates_and_zone(source_accounts):
    f = source_accounts
    entity = uuid4()
    local_day = f["start"] - timedelta(days=1)
    # Honolulu local date lies outside the UTC accepted period, while the UTC
    # instant lies inside. The aggregate cannot rely on source local_date.
    occurred = datetime.combine(f["start"], time(5), UTC)
    with Session(f["api"]) as session, session.begin():
        session.execute(
            text("""INSERT INTO app.weights
            (id,owner_id,revision,weight_kg,occurred_at,local_date,time_zone)
            VALUES(:id,:owner,1,80,:occurred,:day,'Pacific/Honolulu')"""),
            {"id": entity, "owner": f["owners"][0], "occurred": occurred, "day": local_day},
        )
        ctx = context(f, "weight", entity_id=entity, old_dates=(), new_dates=(local_day,))
        extension = projection(f)
        qualified = source_mutated(session, ctx, (extension,))
        assert qualified.qualified_at is not None
        assert [row.id for row in extension.plan.challenges] == [f["challenge"]]
        assert (
            session.scalar(text("SELECT time_zone FROM app.weights WHERE id=:id"), {"id": entity})
            == "Pacific/Honolulu"
        )


def test_full_goal_axis_and_weight_discover_sorted_finished_history(source_accounts):
    f = source_accounts
    with f["admin"].begin() as c:
        finished = [
            add_challenge(c, f["owners"], f["epoch"], date(2020, 1, 1), status="finished"),
            add_challenge(c, f["owners"], f["epoch"], date(2020, 2, 1), status="finished"),
        ]
    for kind in ("goal", "weight"):
        with Session(f["api"]) as session, session.begin():
            extension = projection(f)
            qualified = source_mutated(
                session,
                context(f, kind, old_dates=(date(2000, 1, 1),), new_dates=(date(2000, 1, 2),)),
                (extension,),
            )
            assert qualified.qualified_at is not None
            assert [row.id for row in extension.plan.challenges] == sorted(
                [f["challenge"], *finished]
            )


@pytest.mark.parametrize("stale", ["generation", "epoch", "deleting"])
def test_stale_context_fail_closed_before_qualification(source_accounts, stale):
    f = source_accounts
    provenance = SourceProvenance(
        f["owners"][0],
        2 if stale in {"generation", "deleting"} else 1,
        uuid4() if stale == "epoch" else f["epoch"],
    )
    if stale == "deleting":
        with f["admin"].begin() as c:
            c.execute(
                text("UPDATE app.user_accounts SET state='deleting',generation=2 WHERE id=:owner"),
                {"owner": f["owners"][0]},
            )
    with pytest.raises(DBAPIError) as refused, Session(f["api"]) as session, session.begin():
        source_mutated(session, context(f), (NemesisSourceProjection(provenance),))
    assert refused.value.orig.sqlstate == "23514"


def test_apply_failure_rolls_source_motivation_change_and_receipt_back(source_accounts):
    f = source_accounts
    entity, operation = uuid4(), uuid4()
    ctx = context(f, "weight", entity_id=entity, old_dates=(), new_dates=(f["start"],))

    class FailAfterGuard(NemesisSourceProjection):
        def apply(self, session, qualified):
            super().apply(session, qualified)
            raise RuntimeError("private projection writer failure")

    with Session(f["api"]) as session, session.begin():
        session.execute(
            text(
                "UPDATE app.user_profiles SET pseudonym='Before source',revision=2 "
                "WHERE owner_id=:owner"
            ),
            {"owner": f["owners"][0]},
        )
        with (
            pytest.raises(RuntimeError, match="private projection writer failure"),
            session.begin_nested(),
        ):
            session.execute(
                text("""INSERT INTO app.weights
                (id,owner_id,revision,weight_kg,occurred_at,local_date,time_zone)
                VALUES(:id,:owner,1,80,:occurred,:day,'UTC')"""),
                {
                    "id": entity,
                    "owner": f["owners"][0],
                    "day": f["start"],
                    "occurred": datetime.combine(f["start"], time(12), UTC),
                },
            )
            session.execute(
                text("UPDATE app.sync_counters SET position=1 WHERE owner_id=:owner"),
                {"owner": f["owners"][0]},
            )
            session.execute(
                text(
                    "INSERT INTO app.sync_changes(owner_id,position,entity) "
                    "VALUES(:owner,1,CAST(:entity AS jsonb))"
                ),
                {"owner": f["owners"][0], "entity": json.dumps({"id": str(entity)})},
            )
            session.execute(
                text("""INSERT INTO app.sync_receipts
                (owner_id,operation_id,request_hash,source_epoch,entity_type,entity_id,status,revision)
                VALUES(:owner,:operation,:hash,:epoch,'weight',:entity,'accepted',1)"""),
                {
                    "owner": f["owners"][0],
                    "operation": operation,
                    "hash": "a" * 64,
                    "epoch": f["epoch"],
                    "entity": entity,
                },
            )
            source_mutated(
                session, ctx, (FailAfterGuard(SourceProvenance(f["owners"][0], 1, f["epoch"])),)
            )
    with f["admin"].connect() as c:
        assert (
            c.scalar(
                text("SELECT pseudonym FROM app.user_profiles WHERE owner_id=:owner"),
                {"owner": f["owners"][0]},
            )
            == "Before source"
        )
        for table in (
            "weights",
            "sync_changes",
            "sync_receipts",
            "motivation_accounts",
            "motivation_days",
            "motivation_badges",
        ):
            assert (
                c.scalar(
                    text(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"),
                    {"owner": f["owners"][0]},
                )
                == 0
            )
        assert (
            c.scalar(
                text("SELECT position FROM app.sync_counters WHERE owner_id=:owner"),
                {"owner": f["owners"][0]},
            )
            == 0
        )


def test_apply_null_qualification_refuses_without_fabricated_projection(source_accounts):
    f = source_accounts
    with Session(f["api"]) as session, session.begin():
        ctx, extension = context(f), projection(f)
        extension.lock(session, ctx)
        with pytest.raises(DomainError) as refused:
            extension.apply(session, ctx)
        assert refused.value.code == "nemesis_source_unqualified"


def test_historical_goal_zone_is_preserved_and_full_axis_qualified(source_accounts):
    f = source_accounts
    entity = uuid4()
    with Session(f["api"]) as session:
        goal = create_goal(
            session,
            f["owners"][0],
            entity,
            GoalPayload.model_validate(
                {
                    "effective_from": "2000-01-01",
                    "decided_at": "2000-01-01T12:00:00Z",
                    "time_zone": "Pacific/Honolulu",
                    "goal_type": "maintain",
                    "energy_kcal": "2500",
                    "protein_g": None,
                    "fat_g": None,
                    "carbs_g": None,
                    "activity_class": "line",
                    "estimate": None,
                    "timeline_base_revision": 0,
                    "reason": "user_decision",
                    "correction_of": None,
                }
            ),
            expected_generation=1,
        )
        extension = projection(f)
        qualified = source_mutated(
            session,
            context(
                f,
                "goal",
                entity_id=entity,
                old_dates=(),
                new_dates=(date(2000, 1, 1),),
                old_revision=None,
                new_revision=1,
                goal_axis_revision_before=0,
                goal_axis_revision=goal.timeline_revision,
            ),
            (extension,),
        )
        assert qualified.qualified_at is not None
        assert goal.time_zone == "Pacific/Honolulu"
        assert [row.id for row in extension.plan.challenges] == [f["challenge"]]


def test_profile_change_after_end_preserves_historical_period(source_accounts):
    f = source_accounts
    with f["admin"].begin() as c:
        c.execute(
            text(
                "UPDATE app.nemesis_challenges SET status='cancelled', "
                "cancel_reason='sharing_revoked',revision=revision+1 WHERE id=:id"
            ),
            {"id": f["challenge"]},
        )
        c.execute(
            text("DELETE FROM app.nemesis_slots WHERE challenge_id=:id"), {"id": f["challenge"]}
        )
        ended = add_challenge(c, f["owners"], f["epoch"], date(2020, 1, 1))
        before = c.execute(
            text(
                "SELECT start_date,end_date,start_at,end_at,deadline_at "
                "FROM app.nemesis_challenges WHERE id=:id"
            ),
            {"id": ended},
        ).one()
    with Session(f["api"]) as session, session.begin():
        session.execute(
            text(
                "UPDATE app.user_profiles SET time_zone='Europe/Warsaw',revision=2 "
                "WHERE owner_id=:owner"
            ),
            {"owner": f["owners"][0]},
        )
        extension = projection(f)
        qualified = source_mutated(session, context(f, "profile"), (extension,))
        assert qualified.qualified_at is not None
        assert [row.id for row in extension.plan.challenges] == [ended]
    with f["admin"].connect() as c:
        after = c.execute(
            text(
                "SELECT start_date,end_date,start_at,end_at,deadline_at "
                "FROM app.nemesis_challenges WHERE id=:id"
            ),
            {"id": ended},
        ).one()
        assert before == after


def test_source_locks_held_before_qualification_and_through_commit(source_accounts, monkeypatch):
    from calorie_app.modules.analytics.motivation import repository

    f = source_accounts
    with f["admin"].begin() as c:
        finished = [
            add_challenge(c, f["owners"], f["epoch"], date(2020, 1, 1), status="finished"),
            add_challenge(c, f["owners"], f["epoch"], date(2020, 2, 1), status="finished"),
        ]
    expected = sorted([f["challenge"], *finished])
    extension = projection(f)
    real_refresh = repository.refresh

    def assert_all_locked():
        assert [row.id for row in extension.plan.challenges] == expected
        for identifier in expected:
            with pytest.raises(DBAPIError) as blocked, f["admin"].begin() as other:
                other.execute(
                    text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": identifier},
                )
            assert blocked.value.orig.sqlstate == "55P03"

    def refresh_after_complete_lock(session, owner, dates=None, batch=256):
        assert_all_locked()
        return real_refresh(session, owner, dates, batch)

    monkeypatch.setattr(repository, "refresh", refresh_after_complete_lock)
    with Session(f["api"]) as session, session.begin():
        qualified = source_mutated(session, context(f, "goal"), (extension,))
        assert qualified.qualified_at is not None
        assert_all_locked()
    with f["admin"].begin() as c:
        for identifier in expected:
            assert (
                c.scalar(
                    text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": identifier},
                )
                == 1
            )


def test_apply_after_source_savepoint_rollback_is_fail_closed(source_accounts):
    f = source_accounts
    ctx, extension = context(f), projection(f)
    with Session(f["api"]) as session, session.begin():
        with session.begin_nested() as savepoint:
            extension.lock(session, ctx)
            qualified = replace(ctx, qualified_at=session.scalar(text("SELECT clock_timestamp()")))
            extension.apply(session, qualified)
            savepoint.rollback()
        with pytest.raises(DomainError) as refused:
            extension.apply(session, qualified)
        assert refused.value.code == "nemesis_source_unqualified"
