"""Current real orchestrator regression on isolated PG21; frozen parent20 untouched."""

import json
import os
import secrets
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.motivation.context import SourceMutationContext
from calorie_app.modules.analytics.motivation.service import source_mutated
from calorie_app.modules.diary import service as diary_service
from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection, SourceProvenance
from calorie_app.modules.profiles.models import Profile
from calorie_app.modules.profiles.schemas import GoalPayload
from calorie_app.modules.profiles.service import create_goal
from calorie_app.modules.sync import repository as sync_repository
from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
TERMS = {
    "rule_version": "regularity_v1",
    "duration_days": 7,
    "time_zone": "UTC",
    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
}


@contextmanager
def isolated_current_database(folder):
    """Own named DB21 on explicitly supplied source cluster; never migrate parent20."""
    base = PrivatePostgres.from_environment()
    name = "e8_3_current_" + uuid4().hex[:12] + "_test"
    private = replace(
        base,
        **{
            field: make_url(getattr(base, field))
            .set(database=name)
            .render_as_string(hide_password=False)
            for field in base.__dataclass_fields__
        },
    )
    admin = base.engine("admin")
    with admin.begin() as c:
        role = c.execute(
            text(
                "SELECT "
                "rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,"
                "rolreplication,rolbypassrls FROM pg_roles "
                "WHERE rolname='calorie_app_nemesis_finalizer'"
            )
        ).one_or_none()
        if role is None:
            c.execute(
                text(
                    "CREATE ROLE calorie_app_nemesis_finalizer NOLOGIN NOINHERIT NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE"
                )
            )
        else:
            assert role == (False, False, False, False, False, False, False)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        raw = c.connection.driver_connection
        for statement in (
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator").format(sql.Identifier(name)),
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)),
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO "
                "calorie_app_api,calorie_app_worker,e8_3_nemesis_worker_login"
            ).format(sql.Identifier(name)),
        ):
            c.exec_driver_sql(statement.as_string(raw))
    migrator = private.engine()
    try:
        with migrator.begin() as c:
            c.execute(text("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator"))
            c.execute(text("GRANT USAGE ON SCHEMA app TO calorie_app_api,calorie_app_worker"))
            c.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT,INSERT,UPDATE,DELETE "
                    "ON TABLES TO calorie_app_api,calorie_app_worker"
                )
            )
        private.migrate("0021_e8_nemesis_results")
        yield private
    finally:
        migrator.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(
                sql.SQL("DROP DATABASE {} WITH (FORCE)")
                .format(sql.Identifier(name))
                .as_string(c.connection.driver_connection)
            )
        with admin.connect() as c:
            assert (
                c.scalar(text("SELECT version_num FROM app.alembic_version"))
                == "0020_e8_nemesis_integration"
            )
        admin.dispose()


@contextmanager
def isolated_deletion_operator(private, folder):
    """Actual hardened CLI provisions one random SCRAM LOGIN bound to this DB."""
    admin = make_url(private.admin_url)
    login, password = "e8_3_current_delete_" + uuid4().hex[:12], secrets.token_urlsafe(40)
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(
        PGHOST=admin.host,
        PGPORT=str(admin.port),
        PGDATABASE=admin.database,
        PGUSER=admin.username,
        PGPASSWORD=admin.password,
        DELETION_OPERATOR_LOGIN=login,
        DELETION_OPERATOR_PASSWORD=password,
    )
    script = Path(__file__).resolve().parents[3] / "infra/local/provision_deletion_operator.py"
    result = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise RuntimeError("owned current-source deletion provision failed")
    file = Path(folder) / "current-deletion.private.json"
    url = admin.set(username=login, password=password).render_as_string(hide_password=False)
    file.write_text(json.dumps({"operator_url": url}), encoding="utf-8")
    file.chmod(0o600)
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as c:
            assert c.scalar(text("SELECT session_user")) == login
            assert c.scalar(text("SELECT current_user=session_user"))
        yield engine
    finally:
        engine.dispose()
        owner = private.engine("admin")
        with owner.begin() as c:
            raw = c.connection.driver_connection
            c.exec_driver_sql(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(raw)
            )
            c.exec_driver_sql(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(raw))
        owner.dispose()
        file.unlink()


@pytest.fixture
def private_pg(tmp_path):
    with isolated_current_database(tmp_path) as private:
        admin, api = private.engine("admin"), private.engine("api")
        with admin.connect() as c:
            assert 170000 <= int(c.scalar(text("SHOW server_version_num"))) < 180000
            assert (
                c.scalar(text("SELECT version_num FROM app.alembic_version"))
                == "0021_e8_nemesis_results"
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
            "status": "active",
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
    c.execute(
        text("SELECT app.e8n_initialize(:id,:q)"),
        {"id": identifier, "q": start_at - timedelta(hours=12)},
    )
    if status == "finished":
        c.execute(
            text(
                "UPDATE app.nemesis_challenges SET status='finished',revision=revision+1 WHERE "
                "id=:id"
            ),
            {"id": identifier},
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
    # The following private_pg teardown drops only this test's named database.


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


def append_source_context(session, fixture, kind, entity_id, *, old_dates=(), old_revision=None):
    counter = sync_repository.lock_counter(session, fixture["owners"][0])
    before = counter.position
    value = sync_repository.entity(session, fixture["owners"][0], kind, entity_id)
    sync_repository.append_change(session, counter, value)
    row = sync_repository.owned(session, fixture["owners"][0], kind, entity_id)
    day = () if kind == "profile" else (row.effective_from if kind == "goal" else row.local_date,)
    return SourceMutationContext(
        owner_id=fixture["owners"][0],
        source_kind=kind,
        entity_id=entity_id,
        old_dates=old_dates,
        new_dates=day,
        old_revision=old_revision,
        new_revision=row.revision,
        source_position_before=before,
        source_position=counter.position,
        goal_axis_changed=kind == "goal",
        goal_axis_revision_before=row.timeline_revision - 1 if kind == "goal" else None,
        goal_axis_revision=row.timeline_revision if kind == "goal" else None,
    )


def produce_context(session, fixture, kind="meal", *, day=None):
    """The production domain writer and source serializer produce genuine rows."""
    owner = fixture["owners"][0]
    identifier = uuid4()
    day = day or fixture["start"] + timedelta(days=1)
    examples = Path(__file__).resolve().parents[3] / "contracts/examples/valid"
    filename = "diary-day" if kind == "diary_day" else kind
    payload = json.loads((examples / (filename + ".json")).read_text())
    old_revision = None
    if kind == "profile":
        row = session.query(Profile).filter_by(owner_id=owner).one()
        identifier = row.id
        old_revision = row.revision
        row.pseudonym = "Edited fixture"
        row.revision += 1
        session.flush()
    elif kind == "goal":
        payload.update(
            effective_from=day.isoformat(),
            decided_at=datetime.combine(day, time(12), UTC).isoformat().replace("+00:00", "Z"),
            time_zone="UTC",
        )
        payload["timeline_base_revision"] = (
            session.scalar(
                text("SELECT revision FROM app.goal_timelines WHERE owner_id=:owner"),
                {"owner": owner},
            )
            or 0
        )
        create_goal(
            session, owner, identifier, GoalPayload.model_validate(payload), expected_generation=1
        )
    else:
        payload.update(local_date=day.isoformat(), time_zone="UTC")
        if kind != "diary_day":
            payload["occurred_at"] = (
                datetime.combine(day, time(12), UTC).isoformat().replace("+00:00", "Z")
            )
        getattr(diary_service, "save_" + kind)(
            session, owner, identifier, payload, expected_generation=1
        )
    return append_source_context(session, fixture, kind, identifier, old_revision=old_revision)


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
    extension = projection(f)
    with Session(f["api"]) as session, session.begin():
        ctx = produce_context(session, f, kind)
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
        qualified = source_mutated(session, produce_context(session, f), (projection(f),))
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
        ctx = append_source_context(session, f, "weight", entity)
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
                produce_context(session, f, kind, day=date(2000, 1, 2)),
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
    ctx = context(
        f,
        "weight",
        entity_id=entity,
        old_dates=(),
        new_dates=(f["start"],),
        old_revision=None,
        new_revision=1,
    )

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
                {
                    "owner": f["owners"][0],
                    "entity": json.dumps(
                        {"entity_id": str(entity), "entity_type": "weight", "revision": 1}
                    ),
                },
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
            append_source_context(session, f, "goal", entity),
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
        profile_id = session.scalar(
            text("SELECT id FROM app.user_profiles WHERE owner_id=:owner"),
            {"owner": f["owners"][0]},
        )
        qualified = source_mutated(
            session,
            append_source_context(session, f, "profile", profile_id, old_revision=1),
            (extension,),
        )
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
    f = source_accounts
    with f["admin"].begin() as c:
        finished = [
            add_challenge(c, f["owners"], f["epoch"], date(2020, 1, 1), status="finished"),
            add_challenge(c, f["owners"], f["epoch"], date(2020, 2, 1), status="finished"),
        ]
    expected = sorted([f["challenge"], *finished])
    extension = projection(f)
    real_refresh = NemesisSourceProjection.refresh

    def assert_all_locked():
        assert [row.id for row in extension.plan.challenges] == expected
        for identifier in expected:
            with pytest.raises(DBAPIError) as blocked, f["admin"].begin() as other:
                other.execute(
                    text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": identifier},
                )
            assert blocked.value.orig.sqlstate == "55P03"

    def refresh_after_complete_lock(self, session, context):
        assert_all_locked()
        return real_refresh(self, session, context)

    monkeypatch.setattr(NemesisSourceProjection, "refresh", refresh_after_complete_lock)
    with Session(f["api"]) as session, session.begin():
        qualified = source_mutated(session, produce_context(session, f, "goal"), (extension,))
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
    extension = projection(f)
    with Session(f["api"]) as session, session.begin():
        with session.begin_nested() as savepoint:
            ctx = produce_context(session, f)
            qualified = source_mutated(session, ctx, (extension,))
            savepoint.rollback()
        with pytest.raises(DomainError) as refused:
            extension.apply(session, qualified)
        assert refused.value.code == "nemesis_source_unqualified"
