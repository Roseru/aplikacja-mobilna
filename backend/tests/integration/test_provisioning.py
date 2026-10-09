import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from calorie_app.core.config import Settings
from calorie_app.main import create_app

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("role", ("calorie_app_api", "calorie_app_worker"))
def test_database_role_isolation(database, role):
    engine, _, _ = database
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT has_database_privilege(:role, 'calorie_app', 'CONNECT')"), {"role": role}
        )
        assert not connection.scalar(
            text("SELECT has_database_privilege(:role, 'keycloak', 'CONNECT')"), {"role": role}
        )
        assert not connection.scalar(
            text(
                "SELECT rolcreaterole OR rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=:role"
            ),
            {"role": role},
        )
        assert not connection.scalar(
            text("SELECT has_schema_privilege(:role, 'app', 'CREATE')"), {"role": role}
        )


def test_runtime_cannot_forge_migration_history(database):
    engine, _, _ = database
    with engine.connect() as connection:
        for role in ("calorie_app_api", "calorie_app_worker"):
            assert connection.scalar(
                text("SELECT has_table_privilege(:role, 'app.alembic_version', 'SELECT')"),
                {"role": role},
            )
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege(:role, 'app.alembic_version', :privilege)"),
                    {"role": role, "privilege": privilege},
                )


@pytest.mark.parametrize("role", ("calorie_app_api", "calorie_app_worker"))
@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO app.alembic_version VALUES ('forbidden')",
        "UPDATE app.alembic_version SET version_num='forbidden'",
        "DELETE FROM app.alembic_version",
        "CREATE TABLE app.forbidden(id int)",
    ),
)
def test_runtime_write_and_ddl_are_denied(database, role, statement):
    engine, _, _ = database
    with pytest.raises(ProgrammingError) as rejected, engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        connection.exec_driver_sql(statement)
    assert isinstance(rejected.value.orig, InsufficientPrivilege)
    assert rejected.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("role", ("calorie_app_api", "calorie_app_worker"))
def test_runtime_readiness(database, role):
    _, _, url = database
    runtime_engine = create_engine(url, pool_size=1, max_overflow=0, hide_parameters=True)
    try:
        with runtime_engine.begin() as connection:
            connection.exec_driver_sql(f"SET ROLE {role}")
        with runtime_engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == role
        with TestClient(create_app(Settings(database_url=url), engine=runtime_engine)) as client:
            assert client.get("/health/ready").status_code == 200
    finally:
        runtime_engine.dispose()
