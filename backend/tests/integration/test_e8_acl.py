"""Effective table, column and function privileges with real SCRAM LOGIN roles."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_e7_runtime import role_engine
from test_e8_migration import e8_empty as e8_empty_fixture
from test_e8_migration import seed_owner

pytestmark = pytest.mark.integration
e8_empty = e8_empty_fixture
ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "motivation_provision_pg", ROOT / "infra/local/provision_motivation_worker.py"
)
provisioner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisioner)


@pytest.fixture
def e8_worker(e8_empty):
    engine, _, _ = e8_empty
    worker, login = role_engine(e8_empty, "calorie_app_motivation_worker")
    yield engine, worker, login
    worker.dispose()
    with engine.begin() as connection:
        pg = connection.connection.driver_connection
        connection.exec_driver_sql(
            sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
        )
        connection.exec_driver_sql(
            sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
        )


@pytest.mark.parametrize(
    "role",
    [
        "calorie_app_api",
        "calorie_app_worker",
        "calorie_app_ai_worker",
        "calorie_app_motivation_worker",
    ],
)
def test_raw_point_column_and_table_mutation_forbidden(e8_empty, role):
    engine, _, _ = e8_empty
    for operation in ("UPDATE(total_points)", "UPDATE", "INSERT", "DELETE", "TRUNCATE", "MAINTAIN"):
        with engine.connect() as connection:
            permission = (
                "has_column_privilege(:role,'app.motivation_accounts','total_points','UPDATE')"
                if "(" in operation
                else "has_table_privilege(:role,'app.motivation_accounts',:operation)"
            )
            assert (
                connection.scalar(
                    text("SELECT " + permission), {"role": role, "operation": operation}
                )
                is False
            )
    with engine.begin() as connection:
        owner = seed_owner(connection)
        connection.execute(
            text("SELECT app.e8_refresh(:owner,ARRAY[]::date[],256)"), {"owner": owner}
        )
    with pytest.raises(DBAPIError) as error, engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE " + role)
        connection.execute(
            text("UPDATE app.motivation_accounts SET total_points=999 WHERE owner_id=:owner"),
            {"owner": owner},
        )
    assert error.value.orig.sqlstate == "42501"


def test_real_scram_worker_can_process_but_cannot_read_sources_or_internal_helper(e8_worker):
    engine, worker, _ = e8_worker
    with engine.begin() as connection:
        owner = seed_owner(connection)
        connection.execute(
            text("SELECT app.e8_refresh(:owner,ARRAY[]::date[],256)"), {"owner": owner}
        )
    with worker.begin() as connection:
        assert (
            connection.scalar(text("SELECT app.e8_process(:owner,1)"), {"owner": owner})[
                "processed"
            ]
            == 0
        )
        assert connection.scalar(text("SELECT app.e8_status()"))["pending_backfill"] == 0
        assert list(connection.scalars(text("SELECT app.e8_candidates(1)"))) == []
        assert connection.scalar(text("SELECT app.e8_prune_ranking_sessions(1)")) == 0
    for forbidden in (
        "SELECT * FROM app.diary_days",
        "SELECT weight_kg FROM app.weights",
        "SELECT * FROM app.motivation_accounts",
        "SELECT app.e8_refresh(gen_random_uuid(),ARRAY[]::date[],1)",
        "SELECT app.e8_write_dates(gen_random_uuid(),ARRAY[]::date[],clock_timestamp())",
        "SELECT app.purge_deleted_account(gen_random_uuid())",
        "CREATE TABLE app.e8_attack(id integer)",
    ):
        with pytest.raises(DBAPIError) as error, worker.begin() as connection:
            connection.execute(text(forbidden))
        assert error.value.orig.sqlstate == "42501"


def test_e8_functions_revoke_public_and_close_search_path(e8_empty):
    engine, _, _ = e8_empty
    with engine.connect() as connection:
        functions = connection.execute(
            text(
                "SELECT p.oid,p.proname,p.prosecdef,p.proconfig FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND left(p.proname,3)='e8_'"
            )
        ).all()
        assert functions
        for function in functions:
            assert "search_path=pg_catalog, pg_temp" in function.proconfig
            assert (
                connection.scalar(
                    text(
                        "SELECT NOT EXISTS(SELECT 1 FROM pg_proc p,LATERAL "
                        "aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                        "WHERE p.oid=:id AND a.grantee=0 AND a.privilege_type='EXECUTE')"
                    ),
                    {"id": function.oid},
                )
                is True
            )


def test_login_provisioner_verifies_effective_acl_and_hostile_column(e8_worker):
    engine, _, login = e8_worker
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('calorie.motivation_worker_login',:login,true)"),
            {"login": login},
        )
        connection.exec_driver_sql(provisioner.VERIFY_ACL_SQL)
    try:
        with engine.begin() as connection:
            pg = connection.connection.driver_connection
            connection.exec_driver_sql(
                sql.SQL("GRANT SELECT(weight_kg) ON app.weights TO {}")
                .format(sql.Identifier(login))
                .as_string(pg)
            )
        with pytest.raises(DBAPIError) as error, engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('calorie.motivation_worker_login',:login,true)"),
                {"login": login},
            )
            connection.exec_driver_sql(provisioner.VERIFY_ACL_SQL)
        assert error.value.orig.sqlstate == "23514"
    finally:
        with engine.begin() as connection:
            pg = connection.connection.driver_connection
            connection.exec_driver_sql(
                sql.SQL("REVOKE SELECT(weight_kg) ON app.weights FROM {}")
                .format(sql.Identifier(login))
                .as_string(pg)
            )


def test_pending_ranking_session_cleanup_is_bounded(e8_worker):
    engine, worker, _ = e8_worker
    with engine.begin() as connection:
        owner = seed_owner(connection)
        for _ in range(3):
            connection.execute(
                text(
                    "INSERT INTO app.ranking_sessions "
                    "SELECT :id,:owner,1,sync_epoch,1,'ranking_v1',"
                    "TIMESTAMPTZ '2020-01-01T00:10:00Z',TIMESTAMPTZ '2020-01-01T00:00:00Z' "
                    "FROM app.installation_state WHERE id=1"
                ),
                {"id": uuid4(), "owner": owner},
            )
    with worker.begin() as connection:
        assert connection.scalar(text("SELECT app.e8_prune_ranking_sessions(2)")) == 2
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app.ranking_sessions")) == 1
    with worker.begin() as connection:
        assert connection.scalar(text("SELECT app.e8_prune_ranking_sessions(2)")) == 1
        assert connection.scalar(text("SELECT app.e8_prune_ranking_sessions(2)")) == 0
