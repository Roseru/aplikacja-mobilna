"""Real minimal SCRAM deletion COMMIT, frozen checker and migration safety.

Each case owns an ephemeral *_test DB; it does not erase shared deletion history.
The photo/provider are synthetic; no IdP or Google service is contacted.
"""

import json
import os
import secrets
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_e4_deletion import example, seed
from test_e7_runtime import METADATA, image, private_root, role_engine

from calorie_app.core.config import Settings
from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.ai.service import create_analysis
from calorie_app.modules.analytics.motivation.ranking import ranking_page
from calorie_app.modules.diary.service import save_weight
from calorie_app.modules.profiles.schemas import ConsentInput, ProfilePayload
from calorie_app.modules.profiles.service import put_consents, save_profile
from tests.support.deletion_regression import begin, resume

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
PARENT = "0016_e8_motivation"
REPAIR = "0017_e8_purge_commit"


def execute(connection, statement, **parameters):
    return connection.execute(text(statement), parameters)


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table: list(
                connection.scalars(
                    text(
                        'SELECT to_jsonb(t)::text FROM app."'
                        + table
                        + '" t ORDER BY to_jsonb(t)::text'
                    )
                )
            )
            for table in inspect(connection).get_table_names(schema="app")
            if table != "alembic_version"
        }


def checker(engine):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT "
                "p.proowner::regrole::text,p.prosrc,p.proconfig,p.proacl::text,p.prosecdef,"
                "(SELECT "
                "jsonb_agg(jsonb_build_array(t.tgrelid::regclass::text,t.tgname,t.tgtype,"
                "t.tgdeferrable,t.tginitdeferred,t.tgenabled) ORDER BY t.tgrelid) "
                "FROM pg_trigger t WHERE t.tgfoid=p.oid) FROM pg_proc p "
                "WHERE p.oid='app.diary_aggregate_count()'::regprocedure"
            )
        ).one()


@pytest.fixture
def purge_database(database):
    catalog, _, url = database

    @contextmanager
    def create(revision=REPAIR):
        name = "e8_purge_commit_" + secrets.token_hex(6) + "_test"
        parsed = catalog.url.set(database=name)
        with catalog.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(
                sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator")
                .format(sql.Identifier(name))
                .as_string(connection.connection.driver_connection)
            )
        engine = create_engine(parsed, hide_parameters=True)
        runtimes, logins = [], []
        config = Config(str(ROOT / "backend/alembic.ini"))

        def migrate(action, target):
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
                config.attributes["connection"] = connection
                try:
                    getattr(command, action)(config, target)
                finally:
                    config.attributes.pop("connection", None)

        def login(role):
            runtime, identity = role_engine((engine, migrate, parsed), role)
            runtimes.append(runtime)
            logins.append(identity)
            return runtime

        def provision_operator():
            identity, password = "e8_purge_op_" + secrets.token_hex(6), secrets.token_urlsafe(32)
            environment = os.environ | {
                "PGHOST": parsed.host,
                "PGPORT": str(parsed.port or 5432),
                "PGDATABASE": name,
                "PGUSER": parsed.username,
                "PGPASSWORD": parsed.password,
                "DELETION_OPERATOR_LOGIN": identity,
                "DELETION_OPERATOR_PASSWORD": password,
            }
            result = subprocess.run(
                [sys.executable, str(ROOT / "infra/local/provision_deletion_operator.py")],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            runtime = create_engine(
                parsed.set(username=identity, password=password), hide_parameters=True
            )
            runtimes.append(runtime)
            logins.append(identity)
            return runtime

        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("REVOKE ALL ON DATABASE " + name + " FROM PUBLIC")
                connection.exec_driver_sql(
                    "GRANT CONNECT ON DATABASE " + name + " TO calorie_app_api,calorie_app_worker"
                )
                connection.exec_driver_sql("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
                connection.exec_driver_sql(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT "
                    "SELECT,INSERT,UPDATE,DELETE ON TABLES TO "
                    "calorie_app_api,calorie_app_worker"
                )
            migrate("upgrade", revision)
            yield {
                "admin": engine,
                "migrate": migrate,
                "login": login,
                "operator": provision_operator,
                "url": parsed,
            }
        finally:
            for runtime in runtimes:
                runtime.dispose()
            with engine.begin() as connection:
                pg = connection.connection.driver_connection
                for identity in logins:
                    connection.exec_driver_sql(
                        sql.SQL("DROP OWNED BY {}").format(sql.Identifier(identity)).as_string(pg)
                    )
                    connection.exec_driver_sql(
                        sql.SQL("DROP ROLE {}").format(sql.Identifier(identity)).as_string(pg)
                    )
            engine.dispose()
            with catalog.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)")
                    .format(sql.Identifier(name))
                    .as_string(connection.connection.driver_connection)
                )

    return create


def source_accounts(state):
    people = [
        Principal("https://purge-commit.test/realm", str(uuid4()), frozenset({"user"}))
        for _ in range(2)
    ]
    owners = [seed(state["admin"], person) for person in people]
    return people, owners


def operator_denials(operator):
    with operator.connect() as connection:
        assert connection.scalar(text("SELECT current_user=session_user"))
        for table in ("meals", "meal_items", "motivation_accounts", "ai_analyses"):
            assert not connection.scalar(
                text("SELECT has_table_privilege(current_user,:table,'SELECT')"),
                {"table": "app." + table},
            )
        assert not connection.scalar(
            text(
                "SELECT "
                "has_function_privilege(current_user,'app.diary_aggregate_count()','EXECUTE')"
            )
        )
    with pytest.raises(DBAPIError) as error, operator.begin() as connection:
        connection.exec_driver_sql("SELECT app.diary_aggregate_count()")
    assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("start", [PARENT, REPAIR])
def test_live_graph_real_scram_purge_commit_rollback_retry_and_chain(
    purge_database, tmp_path, start
):
    with purge_database(start) as state:
        people, owners = source_accounts(state)
        owner, partner = owners
        api = state["login"]("calorie_app_api")
        photos = private_root(tmp_path / "photos")
        settings = Settings(
            database_url=state["url"].render_as_string(hide_password=False),
            environment="test",
            ai_photo_root=photos,
        )
        with state["admin"].connect() as connection:
            epoch = connection.scalar(
                text("SELECT sync_epoch FROM app.installation_state WHERE id=1")
            )
        analyses = []
        for person in people:
            result = create_analysis(api, person, epoch, uuid4(), METADATA, image(), settings)
            assert result.status == 202
            analyses.append(UUID(result.payload["analysis_id"]))
        with Session(api) as session, session.begin():
            for target, pseudonym in zip(owners, ("A", "Z"), strict=True):
                profile_id = session.scalar(
                    text("SELECT id FROM app.user_profiles WHERE owner_id=:owner"),
                    {"owner": target},
                )
                save_profile(
                    session,
                    target,
                    profile_id,
                    ProfilePayload(
                        pseudonym=pseudonym, time_zone="UTC", height_cm=None, activity_class="line"
                    ),
                    1,
                )
                put_consents(
                    session,
                    target,
                    ConsentInput(ranking=True, automatic_energy_adjustment=False),
                    1,
                    uuid4(),
                    ranking_consent_epoch=epoch,
                )
        with Session(api) as session, session.begin():
            for target in owners:
                for day in range(1, 5):
                    save_weight(
                        session,
                        target,
                        uuid4(),
                        example("weight")
                        | {
                            "local_date": f"2020-01-{day:02d}",
                            "occurred_at": f"2020-01-{day:02d}T12:00:00Z",
                            "time_zone": "UTC",
                        },
                    )
        with state["admin"].begin() as connection:
            for target in owners:
                execute(connection, "SELECT app.e8_refresh(:owner,NULL,256)", owner=target)
                assert (
                    execute(
                        connection, "SELECT app.e8_process(:owner,256)", owner=target
                    ).scalar_one()["backfill_state"]
                    == "ready"
                )
                assert (
                    execute(
                        connection,
                        "SELECT count(*) FROM app.motivation_badges "
                        "WHERE owner_id=:owner AND active",
                        owner=target,
                    ).scalar_one()
                    == 1
                )
        with Session(api) as session, session.begin():
            token = ranking_page(session, partner, 1)["next_page_token"]
            assert token
        operator = state["operator"]()
        operator_denials(operator)
        operation = uuid4()
        with operator.begin() as connection:
            begin(connection, owner, operation, 1)
        with operator.begin() as connection:
            execute(connection, "SELECT app.confirm_account_deletion(:op)", op=operation)
        before = snapshot(state["admin"])
        original = checker(state["admin"])
        if start == PARENT:
            # Regression oracle: canonical SECDEF purge returns, real caller COMMIT fails.
            with pytest.raises(DBAPIError) as error, operator.begin() as connection:
                execute(connection, "SELECT app.purge_deleted_account(:op)", op=operation)
            assert error.value.orig.sqlstate == "42501"
            assert "diary_aggregate_count" in error.value.orig.diag.context
            assert snapshot(state["admin"]) == before
            state["migrate"]("upgrade", REPAIR)
            assert snapshot(state["admin"]) == before
            repaired = checker(state["admin"])
            assert (
                repaired[:4] == original[:4] and repaired[4] is True and repaired[5] == original[5]
            )
        else:
            assert original[4] is True
        operator_denials(operator)
        with pytest.raises(RuntimeError, match="after real purge"), operator.begin() as connection:
            execute(connection, "SELECT app.purge_deleted_account(:op)", op=operation)
            raise RuntimeError("after real purge before commit")
        assert snapshot(state["admin"]) == before

        class NoProvider:
            def delete_and_confirm(self, *_):
                raise AssertionError("confirmation already durable")

        job = resume(operator, operation, NoProvider())
        assert job["purged_at"] is not None
        assert resume(operator, operation, NoProvider()) == job
        operator_denials(operator)
        with state["admin"].connect() as connection:
            assert (
                execute(
                    connection,
                    "SELECT count(*) FROM app.user_accounts WHERE id=:owner",
                    owner=owner,
                ).scalar_one()
                == 0
            )
            assert (
                execute(
                    connection, "SELECT count(*) FROM app.ai_analyses WHERE id=:id", id=analyses[0]
                ).scalar_one()
                == 0
            )
            assert (
                execute(
                    connection, "SELECT count(*) FROM app.ai_analyses WHERE id=:id", id=analyses[1]
                ).scalar_one()
                == 1
            )
            assert (
                execute(
                    connection,
                    "SELECT count(*) FROM app.motivation_accounts WHERE owner_id=:owner",
                    owner=owner,
                ).scalar_one()
                == 0
            )
            assert (
                execute(
                    connection,
                    "SELECT count(*) FROM app.deleted_subjects WHERE issuer=:issuer "
                    "AND subject=:subject",
                    issuer=people[0].issuer,
                    subject=people[0].subject,
                ).scalar_one()
                == 1
            )
            assert connection.scalar(text("SELECT count(*) FROM app.ai_cleanup_intents")) == 1
        after = snapshot(state["admin"])
        for table, rows in before.items():
            # Compare actual rows of the untouched partner, not only their count.
            retained = [row for row in rows if str(partner) in row]
            assert all(row in after[table] for row in retained)
        with pytest.raises(DomainError) as error, Session(api) as session, session.begin():
            ranking_page(session, partner, 1, token)
        assert error.value.code == "ranking_cursor_restart_required"
        retained = checker(state["admin"])
        state["migrate"]("downgrade", PARENT)
        assert checker(state["admin"]) == retained and snapshot(state["admin"]) == after
        assert resume(operator, operation, NoProvider()) == job
        state["migrate"]("upgrade", REPAIR)
        assert checker(state["admin"]) == retained and snapshot(state["admin"]) == after


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
def test_purge_preserves_caller_constraint_modes_without_flushing_other_queue(purge_database, mode):
    with purge_database() as state:
        _, (owner, _) = source_accounts(state)
        operator = state["operator"]()
        operation = uuid4()
        with operator.begin() as connection:
            begin(connection, owner, operation, 1)
        with operator.begin() as connection:
            execute(connection, "SELECT app.confirm_account_deletion(:op)", op=operation)
        with state["admin"].begin() as connection:
            connection.exec_driver_sql(
                "CREATE TEMP TABLE constraint_mode_probe(value integer, "
                "CONSTRAINT e8_probe_unique UNIQUE(value) DEFERRABLE INITIALLY DEFERRED) "
                "ON COMMIT DROP"
            )
            connection.exec_driver_sql("SET CONSTRAINTS e8_probe_unique " + mode)
            connection.exec_driver_sql("INSERT INTO constraint_mode_probe VALUES(1)")
            if mode == "DEFERRED":
                connection.exec_driver_sql("INSERT INTO constraint_mode_probe VALUES(1)")
            execute(connection, "SELECT app.purge_deleted_account(:op)", op=operation)
            if mode == "IMMEDIATE":
                with pytest.raises(DBAPIError) as error, connection.begin_nested():
                    connection.exec_driver_sql("INSERT INTO constraint_mode_probe VALUES(1)")
                assert error.value.orig.sqlstate == "23505"
            else:
                connection.exec_driver_sql("INSERT INTO constraint_mode_probe VALUES(1)")
                connection.exec_driver_sql("DELETE FROM constraint_mode_probe")
        assert resume(operator, operation, None)["purged_at"] is not None


def test_explicit_immediate_diary_purge_is_checked_then_default_retry_succeeds(purge_database):
    with purge_database() as state:
        _, (owner, _) = source_accounts(state)
        operator = state["operator"]()
        operation = uuid4()
        with operator.begin() as connection:
            begin(connection, owner, operation, 1)
        with operator.begin() as connection:
            execute(connection, "SELECT app.confirm_account_deletion(:op)", op=operation)
        before = snapshot(state["admin"])
        with pytest.raises(DBAPIError) as error, operator.begin() as connection:
            connection.exec_driver_sql("SET CONSTRAINTS app.diary_aggregate_count IMMEDIATE")
            execute(connection, "SELECT app.purge_deleted_account(:op)", op=operation)
        assert error.value.orig.sqlstate == "23514"
        assert "diary_aggregate_count" in error.value.orig.diag.context
        assert snapshot(state["admin"]) == before
        assert resume(operator, operation, None)["purged_at"] is not None


@pytest.mark.parametrize("count", [0, 100, 101])
def test_checker_cardinality_constraints_still_enforced(purge_database, count):
    with purge_database() as state:
        _, (owner, _) = source_accounts(state)
        api = state["login"]("calorie_app_api")
        before = snapshot(state["admin"])

        def change(connection):
            if count == 0:
                execute(connection, "DELETE FROM app.meal_items WHERE owner_id=:owner", owner=owner)
            else:
                execute(
                    connection,
                    "INSERT INTO app.meal_items SELECT "
                    "(jsonb_populate_record(NULL::app.meal_items,to_jsonb(item)||jsonb_build_object('position',n,'item_id',gen_random_uuid()))).*"
                    " FROM app.meal_items item CROSS JOIN generate_series(2,:count) n "
                    "WHERE item.owner_id=:owner AND item.position=1",
                    owner=owner,
                    count=count,
                )

        if count == 100:
            with api.begin() as connection:
                change(connection)
            with state["admin"].connect() as connection:
                assert (
                    execute(
                        connection,
                        "SELECT count(*) FROM app.meal_items WHERE owner_id=:owner",
                        owner=owner,
                    ).scalar_one()
                    == 100
                )
        else:
            with pytest.raises(DBAPIError) as error, api.begin() as connection:
                change(connection)
            assert error.value.orig.sqlstate == "23514"
            assert snapshot(state["admin"]) == before
        # 101 normally fails the position CHECK immediately; only this transactional
        # diagnostic removes that outer CHECK to reach the checker's upper bound.
        if count == 101:
            position = next(
                c["name"]
                for c in inspect(state["admin"]).get_check_constraints("meal_items", schema="app")
                if "position_range" in c["name"]
            )
            with pytest.raises(DBAPIError) as error, state["admin"].begin() as connection:
                connection.exec_driver_sql(
                    sql.SQL("ALTER TABLE app.meal_items DROP CONSTRAINT {}")
                    .format(sql.Identifier(position))
                    .as_string(connection.connection.driver_connection)
                )
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
                change(connection)
            assert error.value.orig.sqlstate == "23514"
            assert "diary_aggregate_count" in error.value.orig.diag.context
            assert snapshot(state["admin"]) == before
            assert position in {
                c["name"]
                for c in inspect(state["admin"]).get_check_constraints("meal_items", schema="app")
            }


@pytest.mark.parametrize(
    "tamper",
    [
        "owner",
        "path",
        "body",
        "public_execute",
        "api_execute",
        "operator_execute",
        "owner_superuser",
        "trigger_timing",
    ],
)
def test_upgrade_rejects_unreviewed_checker_metadata_atomically(purge_database, tamper):
    with purge_database(PARENT) as state:
        admin, migrate = state["admin"], state["migrate"]
        source = snapshot(admin)
        original = checker(admin)
        with admin.connect() as connection:
            definition = connection.scalar(
                text("SELECT pg_get_functiondef('app.diary_aggregate_count()'::regprocedure)")
            )
        try:
            with admin.begin() as connection:
                if tamper == "owner":
                    connection.exec_driver_sql(
                        "ALTER FUNCTION app.diary_aggregate_count() OWNER TO calorie_app_api"
                    )
                elif tamper == "path":
                    connection.exec_driver_sql(
                        "ALTER FUNCTION app.diary_aggregate_count() SET search_path=public,pg_temp"
                    )
                elif tamper == "body":
                    connection.exec_driver_sql(
                        "CREATE OR REPLACE FUNCTION app.diary_aggregate_count() RETURNS "
                        "trigger LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$"
                        " BEGIN RETURN NULL; END $$"
                    )
                elif tamper.endswith("execute"):
                    role = {
                        "public_execute": "PUBLIC",
                        "api_execute": "calorie_app_api",
                        "operator_execute": "calorie_app_deletion_operator",
                    }[tamper]
                    connection.exec_driver_sql(
                        "GRANT EXECUTE ON FUNCTION app.diary_aggregate_count() TO " + role
                    )
                elif tamper == "owner_superuser":
                    connection.exec_driver_sql("ALTER ROLE calorie_app_migrator SUPERUSER")
                else:
                    connection.exec_driver_sql(
                        "ALTER TABLE app.meals DISABLE TRIGGER diary_aggregate_count"
                    )
            with pytest.raises(DBAPIError) as error:
                migrate("upgrade", REPAIR)
            assert error.value.orig.sqlstate == "23514"
            with admin.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM app.alembic_version")) == PARENT
                )
            assert snapshot(admin) == source
        finally:
            with admin.begin() as connection:
                connection.exec_driver_sql("ALTER ROLE calorie_app_migrator NOSUPERUSER")
                connection.exec_driver_sql(
                    "ALTER FUNCTION app.diary_aggregate_count() OWNER TO calorie_app_migrator"
                )
                connection.exec_driver_sql(definition)
                connection.exec_driver_sql(
                    "REVOKE ALL ON FUNCTION app.diary_aggregate_count() FROM "
                    "PUBLIC,calorie_app_api,calorie_app_deletion_operator"
                )
                connection.exec_driver_sql(
                    "ALTER TABLE app.meals ENABLE TRIGGER diary_aggregate_count"
                )
        assert checker(admin) == original
        migrate("upgrade", REPAIR)


def test_empty_downgrade_retains_repair_and_reupgrade_is_idempotent(purge_database):
    with purge_database() as state:
        original, rows = checker(state["admin"]), snapshot(state["admin"])
        assert original[4] is True
        for _ in range(2):
            state["migrate"]("downgrade", PARENT)
            assert checker(state["admin"]) == original
            state["migrate"]("upgrade", REPAIR)
            assert checker(state["admin"]) == original and snapshot(state["admin"]) == rows


def test_hardened_operator_cli_begin_resume_retry(purge_database, tmp_path):
    with purge_database() as state:
        _, (owner, partner) = source_accounts(state)
        operator = state["operator"]()
        operator_denials(operator)
        operation = uuid4()
        configuration = tmp_path / "synthetic-keycloak.json"
        configuration.write_text("[]", encoding="utf-8")
        environment = os.environ | {
            "DELETION_DATABASE_URL": operator.url.render_as_string(hide_password=False),
            "KEYCLOAK_ADMIN_CONFIG": str(configuration),
        }

        def cli(action, *extra):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "calorie_app.modules.identity.deletion",
                    action,
                    "--operation-id",
                    str(operation),
                    *extra,
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        assert (
            cli("begin", "--account-id", str(owner), "--expected-generation", "1")["purged_at"]
            is None
        )
        with operator.begin() as connection:
            execute(connection, "SELECT app.confirm_account_deletion(:op)", op=operation)
        job = cli("resume")
        assert job["purged_at"] is not None and cli("resume") == job and cli("status") == job
        with state["admin"].connect() as connection:
            assert (
                execute(
                    connection, "SELECT count(*) FROM app.meals WHERE owner_id=:owner", owner=owner
                ).scalar_one()
                == 0
            )
            assert (
                execute(
                    connection,
                    "SELECT count(*) FROM app.meals WHERE owner_id=:owner",
                    owner=partner,
                ).scalar_one()
                == 1
            )
        operator_denials(operator)
