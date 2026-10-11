"""Real PostgreSQL 17 server-log regression, with SCRAM including the admin.

This suite owns a temporary cluster (native Windows binaries or a pinned Linux
Docker image); missing tools fail. It never reads a shared application database.
No raw server/client log, password, verifier or password-bearing DSN is reported,
including failure paths. Run pytest without --showlocals and with --tb=short.
"""

import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "infra/local/provision_deletion_operator.py"
IMAGE = (
    "public.ecr.aws/docker/library/postgres:17@"
    "sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)
LOGGING = {
    "log_statement": "all",
    "log_duration": "on",
    "log_min_duration_statement": "0",
    "log_min_duration_sample": "0",
    "log_statement_sample_rate": "1",
    "log_transaction_sample_rate": "1",
    "log_min_error_statement": "error",
    "log_parameter_max_length": "-1",
    "log_parameter_max_length_on_error": "-1",
    "log_error_verbosity": "verbose",
    "track_activities": "on",
}
VERIFIER = re.compile(r"SCRAM-SHA-256\$\d+:[A-Za-z0-9+/]+=*\$[A-Za-z0-9+/]+=*:[A-Za-z0-9+/]+=*")


def require(condition, message):
    """Deliberately avoid pytest assertion rewriting of confidential values."""
    if not condition:
        pytest.fail(message, pytrace=False)


def run(arguments, *, environment=None, timeout=60, capture=True):
    try:
        return subprocess.run(
            arguments,
            env=environment,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        raise pytest.fail.Exception(
            "Required isolated PostgreSQL test process failed (output withheld)", pytrace=False
        ) from None


@dataclass(repr=False)
class Cluster:
    port: int
    password: str = field(repr=False)
    binary: Path | None = None
    data: Path | None = None
    container: str | None = None
    confidential: list[str] = field(default_factory=list, repr=False)

    def connect(self, database="postgres", *, login="postgres", password=None):
        return psycopg.connect(
            host="127.0.0.1",
            port=self.port,
            user=login,
            password=self.password if password is None else password,
            dbname=database,
            connect_timeout=3,
            autocommit=True,
        )

    @contextmanager
    def session(self, database="postgres"):
        try:
            with self.connect(database) as connection:
                yield connection
        except psycopg.Error:
            raise pytest.fail.Exception(
                "Isolated PostgreSQL operation failed (details withheld)", pytrace=False
            ) from None

    def log(self):
        # The boundary also proves that the collector has caught up. Reading
        # a fixed nonrotating file avoids relying on the client's output.
        marker = "e4_secret_boundary_" + secrets.token_hex(12)
        with self.session() as connection:
            connection.execute(sql.SQL("SELECT {}").format(sql.Literal(marker)))
            for _ in range(100):
                content = connection.execute(
                    "SELECT pg_read_file(pg_current_logfile())"
                ).fetchone()[0]
                if marker in content:
                    return content
                time.sleep(0.02)
        pytest.fail("PostgreSQL logging collector did not reach the test boundary", pytrace=False)

    def protect_output(self, output):
        leaked = any(value and value in output for value in self.confidential)
        require(not leaked, "Provisioner client output contains confidential material")
        require(not VERIFIER.search(output), "Provisioner client output contains a verifier")

    def verify_logs(self):
        content = self.log()
        leaked = any(value and value in content for value in self.confidential)
        require(not leaked, "PostgreSQL server log contains confidential material")
        require(not VERIFIER.search(content), "PostgreSQL server log contains a verifier")

    def provision(self, database, login, password, *, success=True, extra=None, helper=HELPER):
        if password:
            self.confidential.extend((password, password.replace("'", "''")))
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("PG") and not key.startswith("DELETION_OPERATOR_")
        }
        environment |= {
            "PGHOST": "127.0.0.1",
            "PGPORT": str(self.port),
            "PGUSER": "postgres",
            "PGDATABASE": database,
            "PGPASSWORD": self.password,
            "PGCLIENTENCODING": "UTF8",
            "DELETION_OPERATOR_LOGIN": login,
            "DELETION_OPERATOR_PASSWORD": password,
        }
        environment |= extra or {}
        # A private copy of the historical SQL can be selected only for local
        # red reproduction. CI always runs the production helper.
        original = os.environ.get("E4_TEST_ORIGINAL_PROVISION_SQL")
        if original:
            executable = str(self.binary / "psql.exe") if self.binary else shutil.which("psql")
            require(bool(executable), "Original SQL reproduction requires psql")
            arguments = [executable, "-X", "-w", "-f", original]
        else:
            arguments = [sys.executable, str(helper)]
        result = run(arguments, environment=environment)
        self.protect_output(result.stdout + result.stderr)
        require(
            (result.returncode == 0) == success,
            "Provisioner returned an unexpected exit status (output withheld)",
        )
        self.verify_logs()
        return result

    def authenticated(self, database, login, password):
        # Every attempt is a new libpq connection; no engine/pool is used.
        try:
            with self.connect(database, login=login, password=password) as connection:
                return connection.execute("SELECT session_user=current_user").fetchone()[0]
        except psycopg.OperationalError:
            return False


@pytest.fixture(scope="module")
def logging_cluster():
    password = secrets.token_urlsafe(40)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    if os.name == "nt":
        binary = Path(os.environ.get("E4_SECRET_PG_BIN", ROOT / ".tools/postgresql-17/pgsql/bin"))
        require(
            (binary / "initdb.exe").exists(), "Secret regression requires PostgreSQL 17 binaries"
        )
        state = ROOT / ".tools/e4-secret-tests" / ("run_" + secrets.token_hex(6))
        state.mkdir(parents=True)
        password_file = state / "admin-password"
        password_file.write_text(password, encoding="utf-8")
        data = state / "data"
        initialized = run(
            [
                str(binary / "initdb.exe"),
                "-D",
                str(data),
                "-U",
                "postgres",
                "-A",
                "scram-sha-256",
                "--encoding=UTF8",
                "--locale=C",
                "--pwfile",
                str(password_file),
            ]
        )
        password_file.unlink(missing_ok=True)
        require(initialized.returncode == 0, "Isolated PostgreSQL initdb failed (output withheld)")
        configuration = {
            **LOGGING,
            "port": str(port),
            "listen_addresses": "127.0.0.1",
            "logging_collector": "on",
            "log_destination": "stderr",
            "log_directory": "log",
            "log_filename": "secret-regression.log",
            "log_rotation_age": "0",
            "log_rotation_size": "0",
        }
        with (data / "postgresql.conf").open("a", encoding="utf-8") as target:
            target.write(
                "\n" + "\n".join(f"{key}='{value}'" for key, value in configuration.items())
            )
        cluster = Cluster(port, password, binary=binary, data=data)
        started = run(
            [
                str(binary / "pg_ctl.exe"),
                "-D",
                str(data),
                "-l",
                str(state / "startup.log"),
                "-w",
                "start",
            ],
            capture=False,
        )
        require(started.returncode == 0, "Isolated PostgreSQL startup failed (output withheld)")
    else:
        docker = shutil.which("docker")
        require(bool(docker), "Secret regression requires Docker; missing tooling is a failure")
        require(
            run([docker, "info"]).returncode == 0,
            "Secret regression requires a running Docker daemon",
        )
        name = "e4-secret-regression-" + secrets.token_hex(8)
        configuration = {
            **LOGGING,
            "logging_collector": "on",
            "log_destination": "stderr",
            "log_directory": "log",
            "log_filename": "secret-regression.log",
            "log_rotation_age": "0",
            "log_rotation_size": "0",
        }
        arguments = [
            docker,
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            f"127.0.0.1:{port}:5432",
            "--env",
            "POSTGRES_PASSWORD",
            "--env",
            "POSTGRES_INITDB_ARGS",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD",
            IMAGE,
        ]
        for key, value in configuration.items():
            arguments.extend(["-c", f"{key}={value}"])
        environment = os.environ | {
            "POSTGRES_PASSWORD": password,
            "POSTGRES_INITDB_ARGS": "--auth=scram-sha-256 --encoding=UTF8",
            "POSTGRES_HOST_AUTH_METHOD": "scram-sha-256",
        }
        started = run(arguments, environment=environment, timeout=180)
        require(
            started.returncode == 0,
            "Isolated PostgreSQL container startup failed (output withheld)",
        )
        cluster = Cluster(port, password, container=name)
    cluster.confidential.append(password)
    try:
        for _ in range(100):
            try:
                with cluster.connect():
                    break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            pytest.fail("Isolated PostgreSQL did not become ready", pytrace=False)
        with cluster.session() as connection:
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
            require(170000 <= version < 180000, "Secret regression requires PostgreSQL 17")
            rules = connection.execute(
                "SELECT auth_method FROM pg_hba_file_rules WHERE type IS NOT NULL"
            ).fetchall()
            require(
                bool(rules) and all(row[0] == "scram-sha-256" for row in rules),
                "All test authentication must require SCRAM",
            )
            for role in (
                "calorie_app_migrator",
                "calorie_app_api",
                "calorie_app_worker",
                "keycloak",
            ):
                connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        require(
            not cluster.authenticated("postgres", "postgres", secrets.token_urlsafe(32)),
            "Wrong administrator password was accepted",
        )
        yield cluster
        cluster.verify_logs()
    finally:
        if cluster.container:
            stopped = run([shutil.which("docker"), "rm", "--force", cluster.container])
        else:
            stopped = run(
                [
                    str(cluster.binary / "pg_ctl.exe"),
                    "-D",
                    str(cluster.data),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ]
            )
        require(stopped.returncode == 0, "Owned PostgreSQL test cluster could not be stopped")


def digest(connection):
    rows = []
    names = connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='app' ORDER BY tablename"
    ).fetchall()
    for (name,) in names:
        values = connection.execute(
            sql.SQL("SELECT to_jsonb(t)::text FROM app.{} t ORDER BY to_jsonb(t)::text").format(
                sql.Identifier(name)
            )
        ).fetchall()
        rows.append((name, values))
    return hashlib.sha256(repr(rows).encode()).digest()


@pytest.fixture(scope="module", params=("fresh", "e3"))
def secret_installation(logging_cluster, request):
    cluster = logging_cluster
    database = "e4_secret_" + secrets.token_hex(8) + "_test"
    login, password = "e4_secret_" + secrets.token_hex(8), secrets.token_urlsafe(40)
    with cluster.session() as connection:
        # Existing E3 has no operator role; fresh bootstrap has its NOLOGIN role.
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
        config = Config(str(ROOT / "backend/alembic.ini"))

        def migrate(revision):
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
                    config.attributes["connection"] = connection
                    command.upgrade(config, revision)
            except Exception:
                raise pytest.fail.Exception(
                    "Isolated test migration failed (details withheld)", pytrace=False
                ) from None
            finally:
                config.attributes.pop("connection", None)

        migrate("head" if request.param == "fresh" else "0008_diary_delete")
        owner = uuid4()
        with cluster.session(database) as connection:
            connection.execute(
                "INSERT INTO app.user_accounts(id,issuer,subject) VALUES(%s,%s,%s)",
                (owner, "https://secret.test/realms/e4", str(owner)),
            )
            connection.execute(
                "INSERT INTO app.weights VALUES(%s,%s,1,81.5,'2026-10-01T10:00:00Z',"
                "'2026-10-01','Europe/Warsaw',NULL)",
                (uuid4(), owner),
            )
            before = digest(connection)
        cluster.provision(database, login, password)
        cluster.provision(database, login, password)
        with cluster.session(database) as connection:
            require(digest(connection) == before, "Provisioning changed application data")
        migrate("head")
        with cluster.session(database) as connection:
            after_upgrade = digest(connection)
        cluster.provision(database, login, password)
        with cluster.session(database) as connection:
            require(
                digest(connection) == after_upgrade,
                "Post-upgrade provisioning changed application data",
            )
        yield cluster, database, login, password
    finally:
        engine.dispose()
        with cluster.session() as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))
            connection.execute("DROP ROLE IF EXISTS calorie_app_deletion_operator")


def test_server_logging_remains_enabled_and_admin_is_scram(logging_cluster):
    with logging_cluster.session() as connection:
        for key, expected in LOGGING.items():
            actual = connection.execute(sql.SQL("SHOW {}").format(sql.Identifier(key))).fetchone()[
                0
            ]
            require(actual == expected, "Global aggressive server logging was changed")
        scram = connection.execute(
            "SELECT left(rolpassword,5)='SCRAM' FROM pg_authid WHERE rolname='postgres'"
        ).fetchone()[0]
        require(scram, "Administrator verifier must use SCRAM")


def test_replay_rotation_new_connections_and_log_confidentiality(secret_installation):
    cluster, database, login, original = secret_installation
    require(
        cluster.authenticated(database, login, original), "Provisioned operator cannot authenticate"
    )
    require(
        not cluster.authenticated(database, login, secrets.token_urlsafe(32)),
        "Wrong operator password was accepted",
    )
    replacement = secrets.token_urlsafe(40) + "'\"Zażółć 🥘"
    cluster.provision(database, login, replacement)
    require(
        cluster.authenticated(database, login, replacement),
        "Rotated Unicode operator password rejected",
    )
    require(
        not cluster.authenticated(database, login, original),
        "Previous operator password remains valid after rotation",
    )
    require(
        not cluster.authenticated(database, login, replacement + "wrong"),
        "Wrong rotated operator password was accepted",
    )
    cluster.provision(database, login, replacement)
    require(
        cluster.authenticated(database, login, replacement),
        "Repeated provisioning changed the intended password",
    )
    # Retain the installation's shared credential for the remaining tests.
    cluster.provision(database, login, original)
    cluster.verify_logs()


@pytest.mark.parametrize("variant", ("quotes", "unicode", "spaces", "saslprep"))
def test_valid_passwords_are_not_trimmed_or_normalized(secret_installation, variant):
    cluster, database, _, _ = secret_installation
    login = "e4_password_" + secrets.token_hex(8)
    suffix = {
        "quotes": "'\"",
        "unicode": "Zażółć Ελληνικά 🥘",
        "spaces": "  ",
        "saslprep": "I\u00adX\u00a0",
    }[variant]
    password = "  " + secrets.token_urlsafe(32) + suffix
    try:
        cluster.provision(database, login, password)
        require(
            cluster.authenticated(database, login, password),
            "Valid password failed real SCRAM authentication",
        )
        if variant == "spaces":
            require(
                not cluster.authenticated(database, login, password.strip()),
                "Provisioner trimmed password whitespace",
            )
    finally:
        with cluster.session() as connection:
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))


@pytest.mark.parametrize(
    "invalid",
    (
        "empty_login",
        "long_login",
        "empty_password",
        "reserved",
        "public_connect",
        "membership",
        "table_acl",
        "public_table_acl",
    ),
)
def test_bad_configuration_rolls_back_and_never_logs_secret(secret_installation, invalid):
    cluster, database, login, original = secret_installation
    replacement = secrets.token_urlsafe(40) + "'\"Żółć"
    with cluster.session(database) as connection:
        before = digest(connection)
        state = connection.execute(
            "SELECT rolpassword,rolcanlogin FROM pg_authid WHERE rolname=%s", (login,)
        ).fetchone()
        before_memberships = connection.execute(
            "SELECT roleid,member,admin_option,inherit_option,set_option "
            "FROM pg_auth_members ORDER BY roleid,member"
        ).fetchall()
    submitted_login = {
        "empty_login": "",
        "long_login": "Ż" * 32,
        "reserved": "calorie_app_api",
        "public_table_acl": "e4_rollback_" + secrets.token_hex(8),
    }.get(invalid, login)
    submitted_password = "" if invalid == "empty_password" else replacement
    try:
        with cluster.session(database) as connection:
            if invalid == "public_connect":
                connection.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO PUBLIC").format(
                        sql.Identifier(database)
                    )
                )
            elif invalid == "membership":
                connection.execute(
                    sql.SQL("GRANT calorie_app_api TO {}").format(sql.Identifier(login))
                )
            elif invalid == "table_acl":
                connection.execute(
                    sql.SQL("GRANT SELECT ON app.user_accounts TO {}").format(sql.Identifier(login))
                )
            elif invalid == "public_table_acl":
                connection.execute("GRANT SELECT ON app.user_accounts TO PUBLIC")
        cluster.provision(database, submitted_login, submitted_password, success=False)
        with cluster.session(database) as connection:
            after_state = connection.execute(
                "SELECT rolpassword,rolcanlogin FROM pg_authid WHERE rolname=%s", (login,)
            ).fetchone()
            require(
                after_state == state, "Rejected provisioning changed the existing role/password"
            )
            if invalid == "public_table_acl":
                require(
                    not connection.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)",
                        (submitted_login,),
                    ).fetchone()[0],
                    "Rejected provisioning did not roll back a newly created login",
                )
            require(digest(connection) == before, "Rejected provisioning changed application data")
        require(
            cluster.authenticated(database, login, original),
            "Rollback invalidated the previous password",
        )
        require(
            not cluster.authenticated(database, login, replacement),
            "Rejected replacement password became active",
        )
    finally:
        with cluster.session(database) as connection:
            if invalid == "public_connect":
                connection.execute(
                    sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(database)
                    )
                )
            elif invalid == "membership":
                connection.execute(
                    sql.SQL("REVOKE calorie_app_api FROM {}").format(sql.Identifier(login))
                )
            elif invalid == "table_acl":
                connection.execute(
                    sql.SQL("REVOKE SELECT ON app.user_accounts FROM {}").format(
                        sql.Identifier(login)
                    )
                )
            elif invalid == "public_table_acl":
                connection.execute("REVOKE SELECT ON app.user_accounts FROM PUBLIC")
            after_memberships = connection.execute(
                "SELECT roleid,member,admin_option,inherit_option,set_option "
                "FROM pg_auth_members ORDER BY roleid,member"
            ).fetchall()
            require(
                after_memberships == before_memberships,
                "Rejected provisioning left role membership changes",
            )


def test_error_after_password_sql_rolls_back_and_keeps_logs_clean(secret_installation, tmp_path):
    cluster, database, login, original = secret_installation
    replacement = secrets.token_urlsafe(40) + "'\"Żółć"
    # Inject a deterministic failure only into a private copy. Production has
    # no test hook. The real protected session, SQL and ALTER run unchanged;
    # division by zero immediately after ALTER proves password rollback and
    # error-log protection before commit.
    source = HELPER.read_text(encoding="utf-8")
    anchor = "connection.execute(PASSWORD_SQL)"
    require(source.count(anchor) == 1, "Rollback probe requires one final password statement")
    probe = tmp_path / HELPER.name
    probe.write_text(
        source.replace(anchor, anchor + '\n            connection.execute("SELECT 1/0")'),
        encoding="utf-8",
    )
    shutil.copyfile(
        HELPER.with_name("provision-deletion-operator.sql"),
        probe.with_name("provision-deletion-operator.sql"),
    )
    with cluster.session(database) as connection:
        before = digest(connection)
        role_before = connection.execute(
            "SELECT rolpassword,rolcanlogin FROM pg_authid WHERE rolname=%s", (login,)
        ).fetchone()
    cluster.provision(database, login, replacement, helper=probe, success=False)
    with cluster.session(database) as connection:
        role_after = connection.execute(
            "SELECT rolpassword,rolcanlogin FROM pg_authid WHERE rolname=%s", (login,)
        ).fetchone()
        require(role_before == role_after, "SQL error after ALTER did not roll back the verifier")
        require(digest(connection) == before, "SQL error after ALTER changed application data")
    require(
        cluster.authenticated(database, login, original),
        "Password rollback lost the old credential",
    )
    require(
        not cluster.authenticated(database, login, replacement),
        "Failed transaction committed the new credential",
    )
    cluster.verify_logs()


def test_inherited_logging_options_cannot_unprotect_provisioner(secret_installation):
    cluster, database, login, password = secret_installation
    cluster.provision(
        database,
        login,
        password,
        extra={
            "PGOPTIONS": "-c log_statement=all -c log_parameter_max_length=-1 "
            "-c log_min_duration_statement=0"
        },
    )
    require(
        cluster.authenticated(database, login, password),
        "Inherited options broke the operator login",
    )


def test_operator_connect_and_effective_acl_are_preserved(secret_installation):
    cluster, database, login, password = secret_installation
    try:
        with cluster.connect(database, login=login, password=password) as connection:
            require(
                connection.execute("SELECT session_user,current_user").fetchone() == (login, login),
                "Operator is not a real independent LOGIN",
            )
            require(
                not connection.execute(
                    "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR "
                    "rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone()[0],
                "Operator received administrative role attributes",
            )
            require(
                connection.execute(
                    "SELECT has_database_privilege(current_user,current_database(),'CONNECT') "
                    "AND NOT has_database_privilege("
                    "current_user,current_database(),'CREATE,TEMP')"
                ).fetchone()[0],
                "Operator database ACL is not CONNECT-only",
            )
            for role in ("calorie_app_api", "calorie_app_worker", "calorie_app_migrator"):
                require(
                    not connection.execute(
                        "SELECT pg_has_role(current_user,%s,'MEMBER')", (role,)
                    ).fetchone()[0],
                    "Operator inherited another technical role",
                )
            for statement in (
                "DELETE FROM app.user_accounts",
                "TRUNCATE app.user_accounts CASCADE",
                "CREATE TABLE app.secret_forbidden(id int)",
                "CREATE SCHEMA secret_forbidden",
                "CREATE TEMP TABLE secret_forbidden(id int)",
            ):
                try:
                    connection.execute(statement)
                except psycopg.Error as error:
                    require(
                        error.sqlstate == "42501", "Operator ACL failure has an unexpected SQLSTATE"
                    )
                else:
                    pytest.fail("Operator performed forbidden DML/DDL/TRUNCATE", pytrace=False)
    except psycopg.Error:
        raise pytest.fail.Exception(
            "Real operator connection failed (details withheld)", pytrace=False
        ) from None
    with cluster.session(database) as connection:
        for role in ("calorie_app_api", "calorie_app_worker"):
            require(
                not connection.execute(
                    "SELECT pg_has_role(%s,'calorie_app_deletion_operator','MEMBER')", (role,)
                ).fetchone()[0],
                "Runtime role became an operator member",
            )
            for function in (
                "app.begin_account_deletion(uuid,uuid,integer)",
                "app.confirm_account_deletion(uuid)",
                "app.purge_deleted_account(uuid)",
            ):
                require(
                    not connection.execute(
                        "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                    ).fetchone()[0],
                    "Runtime role can execute a deletion function",
                )
    cluster.verify_logs()
