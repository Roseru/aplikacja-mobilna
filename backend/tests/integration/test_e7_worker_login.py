"""Own database/roles, real SCRAM worker login and strict effective ACL checks.

No use of the destructive shared database fixture. No cluster shutdown, global
role alteration or changes to other databases. All owned resources are removed.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "infra/local/provision_ai_worker.py"


def require(condition, message):
    if not condition:
        pytest.fail(message, pytrace=False)


def admin_configuration():
    if "TEST_DATABASE_URL" in os.environ:
        url = make_url(os.environ["TEST_DATABASE_URL"])
        require(
            url.drivername == "postgresql+psycopg" and url.database.endswith("_test"),
            "Worker LOGIN tests require a dedicated test-cluster admin context",
        )
        return {
            "host": url.host,
            "port": url.port or 5432,
            "user": url.username,
            "password": url.password or "",
        }
    # Authorized local author harness; never print the credential file or DSN.
    state = ROOT / "backend/var/e7-runtime"
    require(
        (state / "credentials.json").is_file(), "Dedicated PG17 author configuration is missing"
    )
    credentials = json.loads((state / "credentials.json").read_text(encoding="utf-8"))
    environment = json.loads((state / "environment.json").read_text(encoding="utf-8"))
    require(
        environment["host"] == "127.0.0.1" and int(environment["port"]) == 15547,
        "Refusing an unexpected local PostgreSQL author context",
    )
    return {
        "host": environment["host"],
        "port": environment["port"],
        "user": environment["user"],
        "password": credentials["admin"],
    }


def load_helper():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ai_worker_provision_login", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def session(data, *, database=None, login=None, password=None):
    helper = data["helper"]
    cfg = data["admin"] | {"dbname": database or data["database"]}
    if login is not None:
        cfg.update(user=login, password=password)
    # Worker cannot apply superuser-only logging settings; its queries contain
    # no verifier/password. Administrative sessions always use the 17 guards.
    if login is None:
        cfg.update(options=helper.STARTUP_OPTIONS)
    try:
        with psycopg.connect(**cfg, autocommit=True, connect_timeout=10) as connection:
            if login is None:
                helper.verify_session(connection)
            yield connection
    except psycopg.Error as error:
        raise pytest.fail.Exception(
            "Own PG17 LOGIN test failed; SQLSTATE=" + (error.sqlstate or "unknown"), pytrace=False
        ) from None


def provision(data, login, password, success=True, database=None):
    cfg = data["admin"]
    environment = os.environ | {
        "PGHOST": cfg["host"],
        "PGPORT": str(cfg["port"]),
        "PGUSER": cfg["user"],
        "PGPASSWORD": cfg["password"],
        "PGDATABASE": database or data["database"],
        "AI_WORKER_LOGIN": login,
        "AI_WORKER_PASSWORD": password,
    }
    result = subprocess.run(
        [sys.executable, str(HELPER)],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    require(
        password not in result.stdout + result.stderr
        and "SCRAM-SHA-256$" not in result.stdout + result.stderr,
        "Worker provisioner diagnostics exposed confidential material",
    )
    require((result.returncode == 0) is success, "Unexpected provision outcome; output withheld")
    return result


def utility(connection, source, *identifiers):
    connection.execute(sql.SQL(source).format(*(sql.Identifier(value) for value in identifiers)))


def fingerprint(connection):
    tables = (
        "ai_controls",
        "ai_pools",
        "ai_attempts",
        "ai_transport_permits",
        "ai_cleanup_intents",
    )
    rows = [
        connection.execute(
            sql.SQL("SELECT to_jsonb(t)::text FROM app.{} t ORDER BY to_jsonb(t)::text").format(
                sql.Identifier(table)
            )
        ).fetchall()
        for table in tables
    ]
    return hashlib.sha256(repr(rows).encode()).digest()


def role_fingerprint(connection, login):
    rows = connection.execute(
        "SELECT rolpassword,rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
        "rolbypassrls,rolinherit,rolcanlogin FROM pg_authid WHERE rolname=%s",
        (login,),
    ).fetchall()
    return hashlib.sha256(repr(rows).encode()).digest()


@pytest.fixture(scope="module")
def installation():
    suffix = secrets.token_hex(7)
    data = {
        "admin": admin_configuration(),
        "helper": load_helper(),
        "database": "e7_login_" + suffix + "_test",
        "roles": [],
        "databases": [],
    }
    engine = None
    with session(data, database="postgres") as connection:
        utility(connection, "CREATE DATABASE {} OWNER calorie_app_migrator", data["database"])
    data["databases"].append(data["database"])
    try:
        data["keycloak_probe_database"] = "e7_login_" + suffix + "_keycloak_test"
        with session(data, database="postgres") as connection:
            utility(
                connection,
                "CREATE DATABASE {} OWNER calorie_app_migrator",
                data["keycloak_probe_database"],
            )
            data["databases"].append(data["keycloak_probe_database"])
            utility(
                connection, "REVOKE ALL ON DATABASE {} FROM PUBLIC", data["keycloak_probe_database"]
            )
        with session(data, database=data["keycloak_probe_database"]) as connection:
            connection.execute(
                "CREATE TABLE public.identity_probe(id integer PRIMARY KEY, subject text)"
            )
            connection.execute(
                "INSERT INTO public.identity_probe VALUES(1,'synthetic-private-realm-subject')"
            )
        with session(data) as connection:
            utility(connection, "REVOKE ALL ON DATABASE {} FROM PUBLIC", data["database"])
            connection.execute("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
            connection.execute("SET ROLE calorie_app_migrator")
            connection.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT,INSERT,UPDATE,DELETE "
                "ON TABLES TO calorie_app_api,calorie_app_worker"
            )
        cfg = data["admin"]
        engine = create_engine(
            URL.create(
                "postgresql+psycopg",
                username=cfg["user"],
                password=cfg["password"],
                host=cfg["host"],
                port=int(cfg["port"]),
                database=data["database"],
            ),
            hide_parameters=True,
        )
        config = Config(str(ROOT / "backend/alembic.ini"))
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            config.attributes["connection"] = connection
            try:
                command.upgrade(config, "head")
            finally:
                config.attributes.pop("connection", None)
        with session(data) as connection:
            connection.execute(
                "INSERT INTO app.ai_attempts(id,pool_scope,purpose,kind,ordinal,dispatched_at,"
                "pacific_day,reserved_tokens,status,worker_token_hash) VALUES(%s,"
                "'mock:local:mock-food-v1:local','food_photo','generate',1,clock_timestamp(),"
                "(clock_timestamp() AT TIME ZONE 'America/Los_Angeles')::date,10240,'unknown',%s)",
                (uuid4(), hashlib.sha256(b"own-unit-worker-token").hexdigest()),
            )
        yield data
    finally:
        if engine is not None:
            engine.dispose()
        with session(data, database="postgres") as connection:
            for database in reversed(data["databases"]):
                require(database.startswith("e7_login_"), "Refusing cleanup of an unowned database")
                utility(connection, "DROP DATABASE {} WITH (FORCE)", database)
            for login in data["roles"]:
                require(login.startswith("e7_worker_"), "Refusing cleanup of an unowned role")
                utility(connection, "DROP ROLE IF EXISTS {}", login)


def new_login(data):
    login = "e7_worker_" + secrets.token_hex(8)
    data["roles"].append(login)
    return login


def denied(connection, statement):
    try:
        connection.execute(statement)
    except psycopg.Error as error:
        require(
            error.sqlstate == "42501", "Forbidden worker operation returned unexpected SQLSTATE"
        )
    else:
        pytest.fail("AI LOGIN executed a forbidden statement", pytrace=False)


def test_real_scram_login_inherits_only_e7_functions_and_read_columns(installation):
    data = installation
    login, password = new_login(data), secrets.token_urlsafe(40)
    with session(data) as connection:
        before = fingerprint(connection)
    provision(data, login, password)
    provision(data, login, password)
    with session(data, login=login, password=password) as connection:
        require(
            connection.execute("SELECT session_user,current_user").fetchone() == (login, login),
            "Expected a real independent SCRAM LOGIN",
        )
        membership = connection.execute(
            "SELECT p.rolname,m.inherit_option,m.set_option,m.admin_option "
            "FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
            "JOIN pg_roles p ON p.oid=m.roleid "
            "WHERE r.rolname=current_user"
        ).fetchall()
        require(
            membership == [("calorie_app_ai_worker", True, False, False)],
            "Worker membership was broadened",
        )
        require(
            connection.execute("SELECT app.e7_claim(%s,%s)", (uuid4(), uuid4())).fetchone()
            == (None,),
            "Inherited claim function did not execute",
        )
        require(
            connection.execute("SELECT app.e7_finish_context(%s,%s)", (uuid4(), uuid4())).fetchone()
            == (False,),
            "Inherited context function did not execute",
        )
        connection.execute(
            "SELECT id,purpose,state,next_attempt_at,lease_until FROM app.ai_jobs LIMIT 1"
        )
        connection.execute("SELECT count(*) FROM app.ai_attempts")
        for statement in (
            "SELECT * FROM app.meals",
            "SELECT * FROM app.products",
            "SELECT * FROM app.user_accounts",
            "SELECT owner_id FROM app.ai_jobs",
            "SELECT fence FROM app.ai_jobs",
            "UPDATE app.meals SET title=title",
            "DELETE FROM app.ai_attempts",
            "TRUNCATE app.ai_jobs",
            "CREATE TABLE app.worker_escape(id integer)",
            "CREATE TEMP TABLE worker_escape(id integer)",
            "SET ROLE calorie_app_worker",
            "SET ROLE calorie_app_api",
            "SET ROLE calorie_app_migrator",
            "SET ROLE calorie_app_deletion_operator",
            "SET ROLE calorie_app_ai_worker",
            "SELECT app.e7_admit(NULL,'receipts')",
            "SELECT app.purge_deleted_account(NULL)",
        ):
            denied(connection, statement)
    with session(data) as connection:
        require(fingerprint(connection) == before, "Provisioning changed quota/permit/control data")
        require(
            connection.execute(
                "SELECT rolpassword LIKE 'SCRAM-SHA-256$%%' FROM pg_authid WHERE rolname=%s",
                (login,),
            ).fetchone()
            == (True,),
            "Worker verifier is not SCRAM",
        )


def test_rotation_preserves_role_and_pool_and_old_password_stops_authenticating(installation):
    data = installation
    login = new_login(data)
    first, second = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    provision(data, login, first)
    with session(data) as connection:
        before = fingerprint(connection)
        original_oid = connection.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (login,)
        ).fetchone()
    provision(data, login, second)
    with session(data, login=login, password=second) as connection:
        require(
            connection.execute("SELECT current_user").fetchone() == (login,),
            "Rotated SCRAM LOGIN failed",
        )
    cfg = data["admin"] | {"dbname": data["database"], "user": login, "password": first}
    try:
        connection = psycopg.connect(**cfg, connect_timeout=10)
    except psycopg.OperationalError:
        pass
    else:
        connection.close()
        pytest.fail("Old worker password remained valid after rotation", pytrace=False)
    with session(data) as connection:
        require(fingerprint(connection) == before, "Rotation reset quota/permit/control state")
        require(
            connection.execute("SELECT oid FROM pg_roles WHERE rolname=%s", (login,)).fetchone()
            == original_oid,
            "Rotation replaced role identity",
        )


@pytest.mark.parametrize(
    "kind", ["foreign", "legacy", "createdb", "column_acl", "api_function", "child_role"]
)
def test_existing_foreign_or_broad_role_is_not_taken_over(installation, kind):
    data = installation
    login, password = new_login(data), secrets.token_urlsafe(40)
    if kind in {"column_acl", "api_function", "child_role"}:
        provision(data, login, password)
    with session(data) as connection:
        if kind in {"foreign", "legacy", "createdb"}:
            utility(
                connection,
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS",
                login,
            )
            if kind == "foreign":
                utility(
                    connection,
                    "GRANT calorie_app_ai_worker TO {} WITH INHERIT TRUE, SET FALSE, ADMIN FALSE",
                    login,
                )
            elif kind == "legacy":
                utility(connection, "GRANT calorie_app_worker TO {}", login)
            else:
                utility(connection, "ALTER ROLE {} CREATEDB", login)
        elif kind == "column_acl":
            utility(connection, "GRANT UPDATE(title) ON app.meals TO {}", login)
        elif kind == "api_function":
            utility(connection, "GRANT EXECUTE ON FUNCTION app.e7_admit(uuid,text) TO {}", login)
        else:
            child = new_login(data)
            utility(connection, "CREATE ROLE {} NOLOGIN", child)
            utility(connection, "GRANT {} TO {}", login, child)
        role_before, pool_before = role_fingerprint(connection, login), fingerprint(connection)
    provision(data, login, secrets.token_urlsafe(40), success=False)
    with session(data) as connection:
        require(
            role_fingerprint(connection, login) == role_before,
            "Refusal changed existing role/password",
        )
        require(fingerprint(connection) == pool_before, "Refusal changed AI state")


def test_wrong_database_and_other_private_connect_are_fail_closed(installation):
    data = installation
    wrong = "e7_login_" + secrets.token_hex(7) + "_wrong"
    private = "e7_login_" + secrets.token_hex(7) + "_private_test"
    with session(data, database="postgres") as connection:
        for name in (wrong, private):
            utility(connection, "CREATE DATABASE {} OWNER calorie_app_migrator", name)
            data["databases"].append(name)
            utility(connection, "REVOKE ALL ON DATABASE {} FROM PUBLIC", name)
    login, password = new_login(data), secrets.token_urlsafe(40)
    provision(data, login, password, success=False, database=wrong)
    with session(data) as connection:
        require(
            connection.execute(
                "SELECT count(*) FROM pg_roles WHERE rolname=%s", (login,)
            ).fetchone()
            == (0,),
            "Bad-context provisioning created a login",
        )
    provision(data, login, password)
    with session(data) as connection:
        utility(connection, "GRANT CONNECT ON DATABASE {} TO {}", private, login)
        before = role_fingerprint(connection, login)
    provision(data, login, secrets.token_urlsafe(40), success=False)
    with session(data) as connection:
        require(
            role_fingerprint(connection, login) == before,
            "Private-context refusal rotated password",
        )


def test_connect_grants_only_owned_target_and_keeps_keycloak_inaccessible(installation):
    data = installation
    login, password = new_login(data), secrets.token_urlsafe(40)
    provision(data, login, password)
    with session(data) as connection:
        direct = connection.execute(
            "SELECT d.datname,a.privilege_type FROM pg_database d,"
            "LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a "
            "JOIN pg_roles r ON r.oid=a.grantee "
            "WHERE r.rolname=%s ORDER BY d.datname,a.privilege_type",
            (login,),
        ).fetchall()
        require(
            direct == [(data["database"], "CONNECT")],
            "Worker received unrelated direct database grants",
        )
        require(
            not connection.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname LIKE 'keycloak%%' "
                "AND has_database_privilege(%s,oid,'CONNECT'))",
                (login,),
            ).fetchone()[0],
            "Worker can connect to Keycloak",
        )
        require(
            not connection.execute(
                "SELECT has_database_privilege(%s,%s,'CONNECT')",
                (login, data["keycloak_probe_database"]),
            ).fetchone()[0],
            "Worker can connect to the owned private identity database",
        )
    cfg = data["admin"] | {
        "dbname": data["keycloak_probe_database"],
        "user": login,
        "password": password,
    }
    connect_denied = False
    try:
        forbidden = psycopg.connect(**cfg, connect_timeout=10)
    except psycopg.OperationalError as error:
        # Libpq connection-startup failures do not populate psycopg SQLSTATE.
        # Metadata already proves effective ACL=false; this independently checks
        # the server's actual CONNECT denial without printing its diagnostic.
        connect_denied = error.sqlstate in {None, "42501"} and (
            "permission denied for database" in str(error) and "CONNECT privilege" in str(error)
        )
    else:
        forbidden.close()
    require(connect_denied, "Private identity DB did not deny actual CONNECT")
