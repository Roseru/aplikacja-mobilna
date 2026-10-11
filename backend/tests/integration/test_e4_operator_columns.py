"""Effective column ACL regression using real SCRAM and aggressive server logs.

The shared logging fixture owns its cluster; this module never reads a shared
database. Confidential state is compared through hashes and safe diagnostics.
"""

import hashlib
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from test_e4_operator_secrets import HELPER, LOGGING, ROOT, digest, require
from test_e4_operator_secrets import logging_cluster as logging_cluster

pytestmark = pytest.mark.integration
GROUP = "calorie_app_deletion_operator"
STAGES = ("fresh", "e3_before_0011", "e3_after_0011")
GRANTEES = ("login", "public", "operator_role")


def state_digest(connection):
    """Compare all role state and effective ACL sources without exposing secrets."""
    statements = (
        "SELECT * FROM pg_authid ORDER BY oid",
        "SELECT * FROM pg_auth_members ORDER BY roleid,member",
        "SELECT oid,datacl FROM pg_database ORDER BY oid",
        "SELECT oid,nspacl FROM pg_namespace ORDER BY oid",
        "SELECT c.oid,c.relacl FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='app' ORDER BY c.oid",
        "SELECT a.attrelid,a.attnum,a.attacl FROM pg_attribute a "
        "JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='app' ORDER BY a.attrelid,a.attnum",
        "SELECT p.oid,p.proacl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='app' ORDER BY p.oid",
    )
    rows = [connection.execute(statement).fetchall() for statement in statements]
    return hashlib.sha256(repr(rows).encode()).digest(), digest(connection)


def grantee_sql(kind, login):
    return (
        sql.SQL("PUBLIC")
        if kind == "public"
        else sql.Identifier(GROUP if kind == "operator_role" else login)
    )


def column_acl(connection, action, privilege, table, column, kind, login):
    connection.execute(
        sql.SQL("{} {} ({}) ON app.{} {} {}").format(
            sql.SQL(action),
            sql.SQL(privilege),
            sql.Identifier(column),
            sql.Identifier(table),
            sql.SQL("TO" if action == "GRANT" else "FROM"),
            grantee_sql(kind, login),
        )
    )


def effective_column_only(connection, login, table, privilege):
    table_right, column_right = connection.execute(
        "SELECT has_table_privilege(%s,%s,%s),has_any_column_privilege(%s,%s,%s)",
        (login, "app." + table, privilege, login, "app." + table, privilege),
    ).fetchone()
    require(not table_right, "Regression requires no table-level grant")
    require(column_right, "Column grant must be effective through the real login")


@contextmanager
def real_login(cluster, database, login, password):
    try:
        with cluster.connect(database, login=login, password=password) as connection:
            require(
                connection.execute("SELECT session_user,current_user").fetchone() == (login, login),
                "Regression must use a real independent SCRAM LOGIN",
            )
            yield connection
    except psycopg.Error:
        raise pytest.fail.Exception(
            "Real column regression LOGIN failed (details withheld)", pytrace=False
        ) from None


def read_weight(connection):
    values = connection.execute("SELECT weight_kg FROM app.weights").fetchall()
    require(len(values) == 1 and str(values[0][0]) == "81.500000", "Private weight was not read")


def denied(connection, statement):
    try:
        connection.execute(statement)
    except psycopg.Error as error:
        require(error.sqlstate == "42501", "ACL denial returned an unexpected SQLSTATE")
    else:
        pytest.fail("Operator executed a forbidden statement", pytrace=False)


@pytest.fixture(scope="module", params=STAGES)
def column_installation(logging_cluster, request):
    cluster = logging_cluster
    database = "e4_column_" + secrets.token_hex(8) + "_test"
    login, password = "e4_column_" + secrets.token_hex(8), secrets.token_urlsafe(40)
    with cluster.session() as connection:
        if request.param == "fresh":
            connection.execute("CREATE ROLE calorie_app_deletion_operator NOLOGIN NOINHERIT")
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator").format(
                sql.Identifier(database)
            )
        )
    url = URL.create(
        "postgresql+psycopg",
        username="postgres",
        password=cluster.password,
        host="127.0.0.1",
        port=cluster.port,
        database=database,
    )
    engine = create_engine(url, hide_parameters=True)
    config = Config(str(ROOT / "backend/alembic.ini"))

    def migrate(revision):
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
        except Exception:
            raise pytest.fail.Exception(
                "Column regression migration failed (details withheld)", pytrace=False
            ) from None
        finally:
            config.attributes.pop("connection", None)

    try:
        with cluster.session(database) as connection:
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            connection.execute("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
            connection.execute("SET ROLE calorie_app_migrator")
            connection.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT,INSERT,UPDATE,DELETE "
                "ON TABLES TO calorie_app_api,calorie_app_worker"
            )
        if request.param != "fresh":
            migrate("0008_diary_delete")
            cluster.provision(database, login, password)
        if request.param != "e3_before_0011":
            migrate("head")
        cluster.provision(database, login, password)
        owner = uuid4()
        with cluster.session(database) as connection:
            # E3 has no deletion function's schema grant yet. An otherwise
            # harmless USAGE grant makes its column SELECT observable too.
            connection.execute("GRANT USAGE ON SCHEMA app TO calorie_app_deletion_operator")
            connection.execute(
                "INSERT INTO app.user_accounts(id,issuer,subject) VALUES(%s,%s,%s)",
                (owner, "https://column.test/realms/e4", str(owner)),
            )
            connection.execute(
                "INSERT INTO app.weights VALUES(%s,%s,1,81.5,'2026-10-01T10:00:00Z',"
                "'2026-10-01','Europe/Warsaw',NULL)",
                (uuid4(), owner),
            )
        yield cluster, database, login, password, request.param
    finally:
        engine.dispose()
        with cluster.session() as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))
            connection.execute("DROP ROLE IF EXISTS calorie_app_deletion_operator")


@pytest.mark.parametrize("grantee", GRANTEES)
@pytest.mark.parametrize("privilege", ("SELECT", "INSERT", "UPDATE", "REFERENCES"))
def test_effective_column_grant_rejected_with_full_rollback(
    column_installation, grantee, privilege
):
    cluster, database, login, original, _ = column_installation
    replacement = secrets.token_urlsafe(40) + "'\"Zażółć 🥘"
    with cluster.session(database) as connection:
        column_acl(connection, "GRANT", privilege, "weights", "weight_kg", grantee, login)
        effective_column_only(connection, login, "weights", privilege)
        if privilege == "SELECT":
            with real_login(cluster, database, login, original) as operator:
                read_weight(operator)
        # The helper must roll back its own membership/CONNECT repairs too.
        connection.execute(
            sql.SQL("REVOKE calorie_app_deletion_operator FROM {}").format(sql.Identifier(login))
        )
        connection.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM calorie_app_deletion_operator").format(
                sql.Identifier(database)
            )
        )
        before = state_digest(connection)
    try:
        helper = Path(os.environ.get("E4_COLUMN_BASELINE_HELPER", str(HELPER)))
        result = cluster.provision(database, login, replacement, helper=helper, success=False)
        require(result.stderr.strip() == "provisioning_failed", "ACL error must have safe output")
        with cluster.session(database) as connection:
            require(
                state_digest(connection) == before, "Rejected provisioning changed role/ACL/data"
            )
            # Restore only the fixture's intentionally removed connection and
            # membership. Keep the unexpected column grant until admin REVOKE.
            connection.execute(
                sql.SQL(
                    "GRANT calorie_app_deletion_operator TO {} "
                    "WITH INHERIT TRUE, SET TRUE, ADMIN FALSE"
                ).format(sql.Identifier(login))
            )
            connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO calorie_app_deletion_operator").format(
                    sql.Identifier(database)
                )
            )
            effective_column_only(connection, login, "weights", privilege)
        require(
            cluster.authenticated(database, login, original), "Rollback invalidated old password"
        )
        require(
            not cluster.authenticated(database, login, replacement),
            "Rejected provisioning activated replacement password",
        )
        with cluster.session(database) as connection:
            column_acl(connection, "REVOKE", privilege, "weights", "weight_kg", grantee, login)
            before_data = digest(connection)
        cluster.provision(database, login, replacement)
        with cluster.session(database) as connection:
            require(
                digest(connection) == before_data, "Correct provisioning changed application data"
            )
        require(cluster.authenticated(database, login, replacement), "New SCRAM password rejected")
        require(not cluster.authenticated(database, login, original), "Rotation kept old password")
        with real_login(cluster, database, login, replacement) as operator:
            denied(operator, "SELECT weight_kg FROM app.weights")
            denied(operator, "CREATE TEMP TABLE column_forbidden(id int)")
            denied(operator, "SET ROLE calorie_app_api")
    finally:
        with cluster.session(database) as connection:
            column_acl(connection, "REVOKE", privilege, "weights", "weight_kg", grantee, login)
            connection.execute(
                sql.SQL(
                    "GRANT calorie_app_deletion_operator TO {} "
                    "WITH INHERIT TRUE, SET TRUE, ADMIN FALSE"
                ).format(sql.Identifier(login))
            )
        cluster.provision(database, login, original)
    cluster.verify_logs()


@pytest.mark.parametrize("grantee", GRANTEES)
@pytest.mark.parametrize("privilege", ("INSERT", "UPDATE", "REFERENCES"))
@pytest.mark.parametrize("column_installation", ("fresh", "e3_after_0011"), indirect=True)
def test_deletion_job_columns_do_not_receive_write_exception(
    column_installation, grantee, privilege
):
    cluster, database, login, original, _ = column_installation
    replacement = secrets.token_urlsafe(40)
    with cluster.session(database) as connection:
        column_acl(
            connection, "GRANT", privilege, "account_deletion_jobs", "operation_id", grantee, login
        )
        effective_column_only(connection, login, "account_deletion_jobs", privilege)
        before = state_digest(connection)
    try:
        result = cluster.provision(database, login, replacement, success=False)
        require(result.stderr.strip() == "provisioning_failed", "Job ACL error must be safe")
        with cluster.session(database) as connection:
            require(state_digest(connection) == before, "Rejected job ACL changed role/ACL/data")
        require(
            cluster.authenticated(database, login, original), "Job ACL rollback lost old password"
        )
        require(
            not cluster.authenticated(database, login, replacement),
            "Job ACL failure activated replacement password",
        )
    finally:
        with cluster.session(database) as connection:
            column_acl(
                connection,
                "REVOKE",
                privilege,
                "account_deletion_jobs",
                "operation_id",
                grantee,
                login,
            )
    cluster.provision(database, login, original)
    cluster.verify_logs()


@pytest.mark.parametrize("grantee", GRANTEES)
@pytest.mark.parametrize("column_installation", ("fresh", "e3_after_0011"), indirect=True)
def test_deletion_job_column_select_and_table_select_remain_allowed(column_installation, grantee):
    cluster, database, login, password, _ = column_installation
    with cluster.session(database) as connection:
        column_acl(
            connection, "GRANT", "SELECT", "account_deletion_jobs", "operation_id", grantee, login
        )
        before_data = digest(connection)
    try:
        cluster.provision(database, login, password)
        with real_login(cluster, database, login, password) as operator:
            require(
                operator.execute("SELECT operation_id FROM app.account_deletion_jobs").fetchall()
                == [],
                "Allowed deletion-job column SELECT failed",
            )
            require(
                operator.execute("SELECT * FROM app.account_deletion_jobs").fetchall() == [],
                "Allowed deletion-job table SELECT failed",
            )
        with cluster.session(database) as connection:
            require(
                digest(connection) == before_data, "Allowed job SELECT provisioning changed data"
            )
    finally:
        with cluster.session(database) as connection:
            column_acl(
                connection,
                "REVOKE",
                "SELECT",
                "account_deletion_jobs",
                "operation_id",
                grantee,
                login,
            )
    cluster.verify_logs()


@pytest.mark.parametrize("grantee", ("public", "operator_role"))
def test_bad_inherited_column_acl_rolls_back_new_login(column_installation, grantee):
    cluster, database, existing, password, _ = column_installation
    login, new_password = "e4_new_column_" + secrets.token_hex(8), secrets.token_urlsafe(40)
    with cluster.session(database) as connection:
        column_acl(connection, "GRANT", "SELECT", "weights", "weight_kg", grantee, existing)
        connection.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM calorie_app_deletion_operator").format(
                sql.Identifier(database)
            )
        )
        before = state_digest(connection)
    try:
        cluster.provision(database, login, new_password, success=False)
        with cluster.session(database) as connection:
            require(state_digest(connection) == before, "Rejected new LOGIN changed roles/ACL/data")
            require(
                not connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)", (login,)
                ).fetchone()[0],
                "Unexpected column ACL left a newly created LOGIN",
            )
            column_acl(connection, "REVOKE", "SELECT", "weights", "weight_kg", grantee, existing)
            before_data = digest(connection)
        cluster.provision(database, login, new_password)
        require(cluster.authenticated(database, login, new_password), "Correct new LOGIN rejected")
        require(
            cluster.authenticated(database, existing, password), "Existing password was changed"
        )
        with cluster.session(database) as connection:
            require(
                digest(connection) == before_data, "Correct new LOGIN provisioning changed data"
            )
        with real_login(cluster, database, login, new_password) as operator:
            denied(operator, "SELECT weight_kg FROM app.weights")
    finally:
        with cluster.session(database) as connection:
            column_acl(connection, "REVOKE", "SELECT", "weights", "weight_kg", grantee, existing)
            # A successful direct helper grant is deliberately retained only
            # until this fixture's administrative cleanup.
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))
        cluster.provision(database, existing, password)
    cluster.verify_logs()


def test_column_update_is_still_blocked_by_private_account_guard(column_installation):
    cluster, database, login, password, _ = column_installation
    with cluster.session(database) as connection:
        column_acl(connection, "GRANT", "UPDATE", "weights", "weight_kg", "login", login)
        effective_column_only(connection, login, "weights", "UPDATE")
        before_data = digest(connection)
    try:
        with real_login(cluster, database, login, password) as operator:
            try:
                operator.execute("UPDATE app.weights SET weight_kg=82")
            except psycopg.Error as error:
                require(error.sqlstate == "42501", "Private account guard returned wrong SQLSTATE")
                require("user_accounts" in str(error), "Expected private account guard denial")
            else:
                pytest.fail("Column UPDATE bypassed the private account guard", pytrace=False)
        with cluster.session(database) as connection:
            require(digest(connection) == before_data, "Blocked UPDATE changed application data")
    finally:
        with cluster.session(database) as connection:
            column_acl(connection, "REVOKE", "UPDATE", "weights", "weight_kg", "login", login)
    cluster.verify_logs()


def test_column_regression_retains_global_logging_and_admin_scram(logging_cluster):
    with logging_cluster.session() as connection:
        for setting, expected in LOGGING.items():
            actual = connection.execute(
                sql.SQL("SHOW {}").format(sql.Identifier(setting))
            ).fetchone()[0]
            require(actual == expected, "Column regression changed global logging")
        require(
            connection.execute(
                "SELECT left(rolpassword,5)='SCRAM' FROM pg_authid WHERE rolname='postgres'"
            ).fetchone()[0],
            "Column regression admin must use SCRAM",
        )
    logging_cluster.verify_logs()
