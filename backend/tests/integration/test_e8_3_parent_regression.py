"""Targeted actual-parent and integrated-source regressions, without E8.4.

The source harness keeps the explicit frozen seam. The operator connects with
its own minimal SCRAM LOGIN. begin uses the actual integrated SQL wrapper;
legacy purge stays the actual upstream chain. No production wrapper, shared
router, common provision or runtime source file is changed by these tests.
"""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_e8_3_source_guard_pg import context, projection
from test_e8_3_source_guard_pg import private_pg as private_pg
from test_e8_3_source_guard_pg import source_accounts as source_accounts

from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.analytics import service as statistics_service
from calorie_app.modules.analytics.motivation.ranking import ranking_publication
from calorie_app.modules.analytics.motivation.service import source_mutated
from calorie_app.modules.catalog import models as catalog_models  # noqa: F401
from calorie_app.modules.diary.service import save_meal
from calorie_app.modules.identity.deletion import begin, resume
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.profiles.schemas import ConsentInput, GoalPayload, ProfilePayload
from calorie_app.modules.profiles.service import create_goal, put_consents, save_profile

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/examples/valid"


def example(name):
    return json.loads(EXAMPLES.joinpath(name + ".json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def operator(private_pg):
    admin, _ = private_pg
    raw = json.loads(
        Path(os.environ["E8_3_PARENT_DELETION_CREDENTIALS"]).read_text(encoding="utf-8")
    )
    url = raw["operator_url"]
    assert make_url(url).database == admin.url.database
    engine = create_engine(url, hide_parameters=True)
    identity = make_url(url).username
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_user=session_user"))
        assert connection.scalar(text("SELECT session_user")) == identity
        for table in ("meals", "meal_items", "motivation_accounts", "nemesis_challenges"):
            assert not connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user,:table,"
                    "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"
                ),
                {"table": "app." + table},
            )
        assert not connection.scalar(
            text(
                "SELECT has_function_privilege(current_user,"
                "'app.diary_aggregate_count()','EXECUTE')"
            )
        )
    with admin.connect() as connection:
        assert connection.scalar(
            text("SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname=:login"),
            {"login": identity},
        )
        assert not connection.scalar(
            text(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole "
                "OR rolreplication OR rolbypassrls FROM pg_roles "
                "WHERE rolname=:login"
            ),
            {"login": identity},
        )
        assert list(
            connection.scalars(
                text(
                    "SELECT parent.rolname FROM pg_auth_members m "
                    "JOIN pg_roles child ON child.oid=m.member "
                    "JOIN pg_roles parent ON parent.oid=m.roleid "
                    "WHERE child.rolname=:login"
                ),
                {"login": identity},
            )
        ) == ["calorie_app_deletion_operator"]
    yield engine
    engine.dispose()


@pytest.mark.parametrize("days", [7, 30, 90])
def test_actual_parent_empty_e5_calendar_keeps_nulls_and_source_counts(source_accounts, days):
    f = source_accounts
    owner = f["owners"][0]

    def counts():
        with f["admin"].connect() as connection:
            return tuple(
                connection.scalar(
                    text(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"),
                    {"owner": owner},
                )
                for table in (
                    "diary_days",
                    "meals",
                    "weights",
                    "motivation_accounts",
                    "motivation_days",
                    "motivation_badges",
                    "sync_changes",
                )
            )

    before = counts()
    repeatable = f["api"].execution_options(isolation_level="REPEATABLE READ")
    with Session(repeatable) as session, session.begin():
        result = statistics_service.statistics(session, owner, days, expected_generation=1)
    assert [row["closed"] for row in result["daily"]] == [True] * (days - 1) + [False]
    assert result["complete_day_count"] == result["in_goal_day_count"] == 0
    assert result["weight"]["change_kg"] is None
    for row in result["daily"]:
        assert row["status"] == "no_data" and not row["effective_complete"]
        assert row["in_goal"] is None and row["preliminary_in_goal"] is None
        assert all(value["known_sum"] is None for value in row["totals"].values())
    assert all(value == {"value": None, "day_count": 0} for value in result["averages"].values())
    assert counts() == before


def test_actual_parent_fresh_affirmation_survives_epoch_reconcile_source_and_backfill(
    source_accounts,
):
    f = source_accounts
    owner, old_epoch, new_epoch = f["owners"][0], f["epoch"], uuid4()
    with f["admin"].begin() as connection:
        connection.execute(
            text("INSERT INTO app.user_consents(owner_id,revision,ranking) VALUES(:owner,1,true)"),
            {"owner": owner},
        )
        connection.execute(
            text(
                "INSERT INTO app.motivation_accounts"
                "(owner_id,sync_epoch,backfill_state,total_points) "
                "VALUES(:owner,:epoch,'ready',99)"
            ),
            {"owner": owner, "epoch": old_epoch},
        )
        connection.execute(
            text(
                "INSERT INTO app.ranking_affirmations"
                "(owner_id,ranking_consent_epoch,source_revision) "
                "VALUES(:owner,:epoch,1)"
            ),
            {"owner": owner, "epoch": old_epoch},
        )
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
            {"epoch": new_epoch},
        )
    with pytest.raises(DBAPIError) as refused, Session(f["api"]) as session, session.begin():
        source_mutated(session, context(f, "weight"), (projection(f),))
    assert refused.value.orig.sqlstate == "23514"
    with f["admin"].begin() as connection:
        assert connection.scalar(text("SELECT app.e8n_restore_cancel(100)")) == 1
        row = connection.execute(
            text("SELECT status,cancel_reason FROM app.nemesis_challenges WHERE id=:id"),
            {"id": f["challenge"]},
        ).one()
        assert row == ("cancelled", "restore")
    consent = ConsentInput(ranking=True, automatic_energy_adjustment=False)
    key = uuid4()
    with Session(f["api"]) as session, session.begin():
        accepted = put_consents(
            session, owner, consent, 1, key, expected_generation=1, ranking_consent_epoch=new_epoch
        )
        state = ranking_publication(session, owner, new_epoch)
        assert state["requested"] and not state["pending_consent_refresh"]
        assert not state["effective"]  # The fresh marker does not pretend backfill is ready.
    current = f | {"epoch": new_epoch}
    with Session(f["api"]) as session, session.begin():
        entity = uuid4()
        day = f["start"] - timedelta(days=30)
        session.execute(
            text("""INSERT INTO app.weights
            (id,owner_id,revision,weight_kg,occurred_at,local_date,time_zone)
            VALUES(:id,:owner,1,80,:instant,:day,'UTC')"""),
            {
                "id": entity,
                "owner": owner,
                "day": day,
                "instant": datetime.combine(day, time(12), UTC),
            },
        )
        extension = projection(current)
        qualified = source_mutated(
            session,
            replace(
                context(current, "weight"),
                entity_id=entity,
                old_revision=None,
                new_revision=1,
                old_dates=(),
                new_dates=(day,),
            ),
            (extension,),
        )
        assert qualified.qualified_at is not None and extension.plan.challenges == ()
        assert not ranking_publication(session, owner, new_epoch)["pending_consent_refresh"]
    with f["admin"].begin() as connection:
        assert (
            connection.scalar(text("SELECT app.e8_process(:owner,256)"), {"owner": owner})[
                "backfill_state"
            ]
            == "ready"
        )
    with Session(f["api"]) as session, session.begin():
        state = ranking_publication(session, owner, new_epoch)
        assert state["effective"] and not state["pending_consent_refresh"]
        assert (
            put_consents(
                session,
                owner,
                consent,
                1,
                key,
                expected_generation=1,
                ranking_consent_epoch=new_epoch,
            )
            == accepted
        )
        assert ranking_publication(session, owner, new_epoch)["effective"]
        assert (
            session.scalar(
                text(
                    "SELECT ranking_consent_epoch FROM app.ranking_affirmations "
                    "WHERE owner_id=:owner"
                ),
                {"owner": owner},
            )
            == new_epoch
        )


def test_actual_parent_begin_helper_cutoff_on_minimal_scram_login(source_accounts, operator):
    f = source_accounts
    owner, operation = f["owners"][0], uuid4()
    with operator.begin() as connection:
        job = begin(connection, owner, operation, 1)
        assert job["deleting_generation"] == 2
        # The production 0020 SECURITY DEFINER entry point invokes its helper
        # atomically. The minimal LOGIN deliberately has no direct helper grant.
        assert not connection.scalar(
            text(
                "SELECT has_function_privilege(current_user,"
                "'app.e8n_delete_helper(uuid,uuid,boolean)','EXECUTE')"
            )
        )
    with f["admin"].connect() as connection:
        row = connection.execute(
            text("SELECT status,cancel_reason FROM app.nemesis_challenges WHERE id=:id"),
            {"id": f["challenge"]},
        ).one()
        assert row == ("cancelled", "deleted")
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE challenge_id=:id"),
                {"id": f["challenge"]},
            )
            == 0
        )
    with Session(f["api"]) as session, session.begin():
        result = session.scalar(
            text("SELECT app.e8n_read(:issuer,:subject,:epoch,:id)"),
            {
                "issuer": "https://source.fixture.invalid",
                "subject": str(f["owners"][1]),
                "epoch": f["epoch"],
                "id": f["challenge"],
            },
        )
        assert not result["ok"] and result["http_status"] == 404


def test_actual_parent_legacy_live_meal_purge_commits_with_minimal_scram_login(
    source_accounts,
    operator,
):
    f = source_accounts
    principal = Principal("https://parent.regression.invalid", str(uuid4()), frozenset({"user"}))
    with Session(f["api"]) as session, session.begin():
        boot = bootstrap(session, principal, uuid4())
        owner = UUID(boot["account_id"])
        save_profile(session, owner, uuid4(), ProfilePayload.model_validate(example("profile")))
        goal_id, meal_id = uuid4(), uuid4()
        create_goal(session, owner, goal_id, GoalPayload.model_validate(example("goal")))
        save_meal(session, owner, meal_id, example("meal") | {"goal_id": str(goal_id)})
    with f["admin"].connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.meal_items WHERE owner_id=:owner"), {"owner": owner}
            )
            > 0
        )
        assert connection.scalar(
            text(
                "SELECT prosecdef FROM pg_proc WHERE "
                "oid='app.diary_aggregate_count()'::regprocedure"
            )
        )
    operation = uuid4()
    with operator.begin() as connection:
        begin(connection, owner, operation, 1)
    with operator.begin() as connection:
        connection.execute(
            text("SELECT app.confirm_account_deletion(:operation)"), {"operation": operation}
        )
    with operator.begin() as connection:
        connection.execute(
            text("SELECT app.purge_deleted_account(:operation)"), {"operation": operation}
        )
        # No SET CONSTRAINTS shortcut: this context exits through the real COMMIT.
    with f["admin"].connect() as connection:
        for table in (
            "user_profiles",
            "user_consents",
            "goal_versions",
            "diary_days",
            "meals",
            "meal_items",
            "sync_changes",
            "online_receipts",
            "motivation_accounts",
        ):
            assert (
                connection.scalar(
                    text(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"),
                    {"owner": owner},
                )
                == 0
            )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.user_accounts WHERE id=:owner"), {"owner": owner}
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.user_accounts WHERE id=ANY(:peers)"),
                {"peers": list(f["owners"])},
            )
            == 2
        )
        assert (
            connection.scalar(
                text(
                    "SELECT purged_at FROM app.account_deletion_jobs WHERE operation_id=:operation"
                ),
                {"operation": operation},
            )
            is not None
        )

    class ProviderMustNotRun:
        def delete_and_confirm(self, *_):
            raise AssertionError("confirmation and purge are already durable")

    assert resume(operator, operation, ProviderMustNotRun())["purged_at"] is not None
