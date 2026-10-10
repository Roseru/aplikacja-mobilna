"""Provision an independent deletion login without sending its plaintext password.

Run with the backend's Python/psycopg environment. Standard libpq PG* variables,
service configuration or pgpass supply the administrator connection; the two
DELETION_OPERATOR_* variables supply the new login/password. Never pass secrets
as arguments. PostgreSQL 17's built-in SQL logging is protected for this one
connection from startup, without changing instance/role logging defaults.

The verifier remains confidential: it necessarily exists in server catalogs and
process memory. External audit hooks, proxies and privileged observers require
separate deployment controls; these session settings cannot protect against them.
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

import psycopg

# Apply before the first SQL, including BEGIN and configuration verification.
# Statement logging, both duration samplers, transaction sampling, error statement
# and parameter logging are distinct channels in PostgreSQL 17.
SESSION_SETTINGS = {
    "log_statement": "none",
    "log_duration": "off",
    "log_min_duration_statement": "-1",
    "log_min_duration_sample": "-1",
    "log_statement_sample_rate": "0",
    "log_transaction_sample_rate": "0",
    "log_min_error_statement": "panic",
    "log_parameter_max_length": "0",
    "log_parameter_max_length_on_error": "0",
    "log_error_verbosity": "terse",
    "log_min_messages": "panic",
    "log_statement_stats": "off",
    "log_parser_stats": "off",
    "log_planner_stats": "off",
    "log_executor_stats": "off",
    "track_activities": "off",
    "search_path": "pg_catalog,pg_temp",
}
STARTUP_OPTIONS = " ".join(f"-c {name}={value}" for name, value in SESSION_SETTINGS.items())
PASSWORD_SQL = """
DO $$
BEGIN
  EXECUTE format('ALTER ROLE %I LOGIN INHERIT PASSWORD %L',
                 current_setting('calorie.operator_login'),
                 current_setting('calorie.operator_verifier'));
END $$;
"""


class ProvisionError(Exception):
    """A stable, non-sensitive diagnostic safe to print."""


def configuration(environment: Mapping[str, str]) -> tuple[bytes, bytes]:
    """Validate locally; do not trim or normalize PostgreSQL password input."""
    login = environment.get("DELETION_OPERATOR_LOGIN", "")
    password = environment.get("DELETION_OPERATOR_PASSWORD", "")
    try:
        login_bytes, password_bytes = login.encode("utf-8"), password.encode("utf-8")
    except UnicodeError:
        raise ProvisionError("invalid_configuration") from None
    if (
        not 1 <= len(login_bytes) <= 63
        or not password_bytes
        or b"\x00" in login_bytes
        or b"\x00" in password_bytes
    ):
        raise ProvisionError("invalid_configuration")
    return login_bytes, password_bytes


def verify_session(connection: psycopg.Connection) -> None:
    if not 170000 <= connection.info.server_version < 180000:
        raise ProvisionError("unsupported_server")
    # These statements contain no password/verifier. Verification must finish
    # before generating or transmitting any verifier, and fails closed.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name, setting FROM pg_catalog.pg_settings WHERE name = ANY(%s)",
            (list(SESSION_SETTINGS),),
        )
        if dict(cursor.fetchall()) != SESSION_SETTINGS:
            raise ProvisionError("unsafe_session_configuration")
        cursor.execute("SHOW server_encoding")
        if cursor.fetchone() != ("UTF8",):
            raise ProvisionError("unsupported_server_encoding")


def provision(login_bytes: bytes, password_bytes: bytes) -> None:
    sql_path = Path(__file__).with_name("provision-deletion-operator.sql")
    statements = sql_path.read_text(encoding="utf-8")
    # Explicit options replace PGOPTIONS/service options. They contain no secret.
    # Libpq still resolves other connection details from PG*/service/pgpass.
    with psycopg.connect(
        "",
        autocommit=True,
        options=STARTUP_OPTIONS,
        client_encoding="UTF8",
        application_name="calorie-deletion-provision",
        connect_timeout=10,
    ) as connection:
        verify_session(connection)
        # PQencryptPasswordConn with an explicit algorithm performs encryption
        # locally; algorithm=None would issue SHOW password_encryption first.
        # Libpq owns SASLprep/fallback behavior; do not normalize it in Python.
        verifier = connection.pgconn.encrypt_password(
            password_bytes, login_bytes, algorithm=b"scram-sha-256"
        )
        if not verifier.startswith(b"SCRAM-SHA-256$"):
            raise ProvisionError("unsupported_password_encryption")
        with connection.transaction():
            connection.execute(
                "SELECT set_config('calorie.operator_login', %s, true)",
                (login_bytes.decode("utf-8"),),
            )
            connection.execute(statements)
            # Bind keeps the verifier out of client SQL text; startup settings
            # separately prevent parameter/duration/error logs from exposing it.
            connection.execute(
                "SELECT set_config('calorie.operator_verifier', %s, true)",
                (verifier.decode("ascii"),),
            )
            connection.execute(PASSWORD_SQL)
        # No raw query, connection object, verifier or provider error is printed.


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise ProvisionError("invalid_arguments")
        provision(*configuration(os.environ))
    except ProvisionError as error:
        print(str(error), file=sys.stderr)
        return 3 if str(error) in {"invalid_configuration", "invalid_arguments"} else 1
    except Exception:  # noqa: BLE001 - this boundary must redact all provider diagnostics
        # PostgreSQL diagnostics can include query text, bound parameters or DSN.
        # Do not emit them, even when startup options or authentication fail.
        print("provisioning_failed", file=sys.stderr)
        return 1
    print("Operator provisioning and effective ACL verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
