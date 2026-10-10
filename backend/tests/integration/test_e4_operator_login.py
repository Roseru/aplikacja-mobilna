"""Provisioning and deletion CLI through a real independent PostgreSQL LOGIN.

Each module fixture creates its own database; it never uses the destructive
shared ``database`` fixture. The HTTP provider below verifies CLI wiring only;
the separate Keycloak suite supplies real-provider evidence.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
PROVISION = ROOT / "infra/local/provision-deletion-operator.sql"


def utility(connection, statement, *arguments):
    connection.exec_driver_sql(
        sql.SQL(statement).format(*arguments).as_string(connection.connection.driver_connection)
    )


def provision(url, login, password, *, expect_success=True):
    executable = os.environ.get("PSQL") or shutil.which("psql")
    if executable is None:
        local = ROOT / ".tools/postgresql-17/pgsql/bin/psql.exe"
        executable = str(local) if local.exists() else None
    assert executable, "Operator provisioning regression requires PostgreSQL 17 psql"
    parsed = make_url(url)
    environment = os.environ | {
        "PGPASSWORD": parsed.password or "",
        "PGCLIENTENCODING": "UTF8",
        "DELETION_OPERATOR_LOGIN": login,
        "DELETION_OPERATOR_PASSWORD": password,
    }
    result = subprocess.run(
        [
            executable,
            "-X",
            "-w",
            "--host",
            parsed.host or "localhost",
            "--port",
            str(parsed.port or 5432),
            "--username",
            parsed.username,
            "--dbname",
            parsed.database,
            "--file",
            str(PROVISION),
        ],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert password not in result.stdout + result.stderr
    if expect_success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
    return result


def snapshot(connection):
    return {
        table: connection.exec_driver_sql(
            f"SELECT to_jsonb(t)::text FROM app.{table} t ORDER BY to_jsonb(t)::text"
        )
        .scalars()
        .all()
        for table in ("installation_state", "user_accounts", "weights")
    }


@pytest.fixture(scope="module", params=("fresh", "e3"))
def operator_installation(request):
    parsed = make_url(os.environ["TEST_DATABASE_URL"])
    assert parsed.drivername == "postgresql+psycopg" and parsed.database.endswith("_test")
    database_name = "e4_operator_" + secrets.token_hex(6) + "_test"
    login, password = "e4_operator_" + secrets.token_hex(6), secrets.token_urlsafe(32)
    admin = create_engine(
        parsed.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    with admin.connect() as connection:
        assert (
            170000 <= int(connection.exec_driver_sql("SHOW server_version_num").scalar()) < 180000
        )
        utility(
            connection,
            "CREATE DATABASE {} OWNER calorie_app_migrator",
            sql.Identifier(database_name),
        )
    url = parsed.set(database=database_name)
    engine = create_engine(url, hide_parameters=True)
    operator = None
    try:
        with engine.begin() as connection:
            utility(
                connection, "REVOKE ALL ON DATABASE {} FROM PUBLIC", sql.Identifier(database_name)
            )
            utility(
                connection,
                "GRANT CONNECT ON DATABASE {} TO calorie_app_api,calorie_app_worker",
                sql.Identifier(database_name),
            )
            connection.exec_driver_sql("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            connection.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA app "
                "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO calorie_app_api,calorie_app_worker"
            )
        config = Config(str(ROOT / "backend/alembic.ini"))

        def migrate(revision):
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
                config.attributes["connection"] = connection
                try:
                    command.upgrade(config, revision)
                finally:
                    config.attributes.pop("connection", None)

        before = None
        if request.param == "e3":
            migrate("0008_diary_delete")
            with engine.begin() as connection:
                owner = uuid4()
                connection.execute(
                    text(
                        "INSERT INTO app.user_accounts(id,issuer,subject) "
                        "VALUES(:id,:issuer,:subject)"
                    ),
                    {
                        "id": owner,
                        "issuer": "https://operator.test/realms/e3",
                        "subject": str(owner),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO app.weights VALUES(:id,:owner,1,81.5,"
                        "'2026-10-01T10:00:00Z','2026-10-01','Europe/Warsaw',NULL)"
                    ),
                    {"id": uuid4(), "owner": owner},
                )
                before = snapshot(connection)
        # First reproduce the actual failure with a real LOGIN, never SET ROLE.
        with engine.begin() as connection:
            utility(
                connection,
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE",
                sql.Identifier(login),
            )
            connection.exec_driver_sql("SET LOCAL password_encryption='scram-sha-256'")
            # Authenticate successfully before probing the missing CONNECT ACL,
            # including CI clusters whose host rule requires SCRAM.
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(login), sql.Literal(password)
                    )
                )
            utility(connection, "GRANT calorie_app_deletion_operator TO {}", sql.Identifier(login))
            assert not connection.scalar(
                text("SELECT has_database_privilege(:login,current_database(),'CONNECT')"),
                {"login": login},
            )
        operator_url = url.set(username=login, password=password)
        operator = create_engine(operator_url, hide_parameters=True)
        with pytest.raises(OperationalError) as denied:
            with operator.connect():
                pass
        assert "CONNECT" in str(denied.value.orig)
        operator.dispose()
        provision(url, login, password)
        provision(url, login, password)  # Repeated pre-upgrade provisioning is safe.
        migrate("head")
        provision(url, login, password)  # Also verifies post-upgrade effective ACL.
        with engine.connect() as connection:
            if before is not None:
                assert snapshot(connection) == before
            assert connection.exec_driver_sql(
                "SELECT version_num FROM app.alembic_version"
            ).scalar()
        operator = create_engine(operator_url, hide_parameters=True)
        yield engine, operator, url, operator_url, login, password
    finally:
        if operator is not None:
            operator.dispose()
        engine.dispose()
        with admin.connect() as connection:
            utility(connection, "DROP DATABASE {} WITH (FORCE)", sql.Identifier(database_name))
            utility(connection, "DROP ROLE IF EXISTS {}", sql.Identifier(login))
        admin.dispose()


def test_real_login_has_only_operator_membership_and_connect(operator_installation):
    engine, operator, _, _, login, _ = operator_installation
    with operator.connect() as connection:
        assert connection.exec_driver_sql("SELECT session_user,current_user").one() == (
            login,
            login,
        )
        assert not connection.scalar(
            text(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user"
            )
        )
        assert connection.exec_driver_sql(
            "SELECT parent.rolname FROM pg_auth_members m "
            "JOIN pg_roles member ON member.oid=m.member "
            "JOIN pg_roles parent ON parent.oid=m.roleid WHERE member.rolname=current_user"
        ).scalars().all() == ["calorie_app_deletion_operator"]
        for parent in ("calorie_app_api", "calorie_app_worker", "calorie_app_migrator"):
            assert not connection.scalar(
                text("SELECT pg_has_role(current_user,:role,'MEMBER')"), {"role": parent}
            )
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname=:login"),
            {"login": login},
        )
        assert not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_database d,LATERAL aclexplode(d.datacl) a "
                "WHERE d.datname=current_database() AND a.grantee=0 AND a.privilege_type='CONNECT')"
            )
        )


@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO app.account_deletion_jobs(operation_id) VALUES(gen_random_uuid())",
        "UPDATE app.account_deletion_jobs SET purged_at=clock_timestamp()",
        "DELETE FROM app.user_accounts",
        "TRUNCATE app.user_accounts CASCADE",
        "CREATE TABLE app.operator_forbidden(id int)",
        "CREATE SCHEMA operator_forbidden",
        "CREATE TEMP TABLE operator_forbidden(id int)",
        "SET ROLE calorie_app_api",
        "SET ROLE calorie_app_worker",
        "SET ROLE calorie_app_migrator",
    ),
)
def test_real_operator_login_denies_dml_ddl_truncate_and_other_roles(
    operator_installation, statement
):
    _, operator, _, _, _, _ = operator_installation
    with pytest.raises(DBAPIError) as rejected, operator.begin() as connection:
        connection.exec_driver_sql(statement)
    assert rejected.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("role", ("calorie_app_api", "calorie_app_worker"))
def test_runtime_has_no_operator_membership_or_entry_points(operator_installation, role):
    engine, _, _, _, _, _ = operator_installation
    with engine.connect() as connection:
        assert not connection.scalar(
            text("SELECT pg_has_role(:role,:operator,'MEMBER')"),
            {"role": role, "operator": "calorie_app_deletion_operator"},
        )
        for function in (
            "app.begin_account_deletion(uuid,uuid,integer)",
            "app.confirm_account_deletion(uuid)",
            "app.purge_deleted_account(uuid)",
        ):
            assert not connection.scalar(
                text("SELECT has_function_privilege(:role,:f,'EXECUTE')"),
                {"role": role, "f": function},
            )
    with pytest.raises(DBAPIError) as rejected, engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        connection.execute(
            text("SELECT app.begin_account_deletion(:owner,:op,1)"),
            {"owner": uuid4(), "op": uuid4()},
        )
    assert rejected.value.orig.sqlstate == "42501"


def test_provisioning_creates_new_login_and_rejects_overprivileged_login(operator_installation):
    engine, _, url, _, _, _ = operator_installation
    login, password = "e4_new_operator_" + secrets.token_hex(6), secrets.token_urlsafe(32)
    try:
        provision(url, login, password)
        provision(url, login, password)
        with engine.begin() as connection:
            utility(connection, "GRANT calorie_app_api TO {}", sql.Identifier(login))
        denied = provision(url, login, password, expect_success=False)
        assert "unexpected privileges or memberships" in denied.stderr
    finally:
        with engine.begin() as connection:
            utility(connection, "DROP ROLE IF EXISTS {}", sql.Identifier(login))


def test_cli_begin_status_resume_with_real_operator_login(operator_installation, tmp_path):
    engine, _, _, operator_url, _, _ = operator_installation
    state = {"deleted": False, "requests": []}
    subject, owner, operation = uuid4(), uuid4(), uuid4()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            state["requests"].append(("POST", self.path))
            assert self.path == "/realms/test/protocol/openid-connect/token"
            self.reply(200, {"access_token": "synthetic-cli-test-token"})

        def do_GET(self):
            state["requests"].append(("GET", self.path))
            if self.path.endswith("/users?max=1"):
                self.reply(200, [])
            else:
                assert self.path == "/admin/realms/test/users/" + str(subject)
                self.reply(
                    404 if state["deleted"] else 200,
                    {} if state["deleted"] else {"id": str(subject)},
                )

        def do_DELETE(self):
            state["requests"].append(("DELETE", self.path))
            assert self.path == "/admin/realms/test/users/" + str(subject)
            state["deleted"] = True
            self.reply(204, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:" + str(server.server_port)
        issuer = base + "/realms/test"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:issuer,:subject)"
                ),
                {"id": owner, "issuer": issuer, "subject": str(subject)},
            )
        configuration = tmp_path / "provider.json"
        configuration.write_text(
            json.dumps(
                [
                    {
                        "issuer": issuer,
                        "admin_base_url": base,
                        "realm": "test",
                        "client_id": "operator",
                        "client_secret": "synthetic-cli-test-secret",
                        "allow_local_http": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        environment = os.environ | {
            "DELETION_DATABASE_URL": operator_url.render_as_string(hide_password=False),
            "KEYCLOAK_ADMIN_CONFIG": str(configuration),
        }

        def cli(action, *arguments):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "calorie_app.modules.identity.deletion",
                    action,
                    "--operation-id",
                    str(operation),
                    *arguments,
                ],
                env=environment,
                capture_output=True,
                encoding="utf-8",
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        started = cli("begin", "--account-id", str(owner), "--expected-generation", "1")
        assert started["deleting_generation"] == "2"
        assert cli("status") == started
        assert cli("begin", "--account-id", str(owner), "--expected-generation", "1") == started
        completed = cli("resume")
        assert completed["identity_confirmed_at"] and completed["purged_at"]
        assert cli("status") == completed
        requests_before_retry = list(state["requests"])
        assert cli("resume") == completed
        assert state["requests"] == requests_before_retry
        assert state["deleted"] and any(method == "DELETE" for method, _ in state["requests"])
        with engine.connect() as connection:
            assert not connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM app.user_accounts WHERE id=:id)"), {"id": owner}
            )
            assert connection.scalar(
                text("SELECT app.subject_blocked(:issuer,:subject)"),
                {"issuer": issuer, "subject": str(subject)},
            )
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM app._deletion_context").scalar()
                == 0
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
