import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_database_role_isolation(database):
    engine, _, _ = database
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT has_database_privilege('calorie_app_api', 'calorie_app', 'CONNECT')")
        )
        assert not connection.scalar(
            text("SELECT has_database_privilege('calorie_app_api', 'keycloak', 'CONNECT')")
        )
        assert not connection.scalar(
            text("SELECT rolcreaterole OR rolsuper FROM pg_roles WHERE rolname='calorie_app_api'")
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
