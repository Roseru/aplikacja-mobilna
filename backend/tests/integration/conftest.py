import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture(autouse=True)
def cursor_secret(monkeypatch):
    # Synthetic test-only secret; deployment must supply its own persistent secret.
    monkeypatch.setenv("CATALOG_PAGE_TOKEN_SECRET", "e2" * 32)


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "Integration requires TEST_DATABASE_URL pointing to a dedicated *_test database"
        )
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg" or not parsed.database.endswith("_test"):
        pytest.fail("Refusing destructive tests outside a dedicated PostgreSQL *_test database")
    engine = create_engine(url, hide_parameters=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE "
            "rolname='calorie_app_deletion_exporter') THEN CREATE ROLE "
            "calorie_app_deletion_exporter NOLOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT; END IF; END $$"
        )
        version = int(connection.scalar(text("SHOW server_version_num")))
        assert 170000 <= version < 180000, "Tests must run on PostgreSQL 17"
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS app CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        # Mirror bootstrap grants, so removing the metadata REVOKE fails the test.
        connection.exec_driver_sql(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA app "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
            "TO calorie_app_api, calorie_app_worker"
        )
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))

    def migrate(action, *args):
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            config.attributes["connection"] = connection
            try:
                getattr(command, action)(config, *args)
            finally:
                config.attributes.pop("connection", None)

    migrate("upgrade", "head")
    from tests.support.deletion_regression import harness

    harness(engine)
    yield engine, migrate, url
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA app CASCADE")
    engine.dispose()
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="session", autouse=True)
def nemesis_evidence_servers(tmp_path_factory, request):
    from tests.support.e8_3_ci import configured_servers, explicit_credentials_complete

    if explicit_credentials_complete(os.environ):
        yield
        return
    requires_nemesis = any(
        item.path.name.startswith("test_e8_3_") for item in request.session.items
    )
    if not requires_nemesis:
        yield
        return
    if not os.environ.get("CI"):
        pytest.fail("Nemesis integration requires complete owned source/audit/deletion credentials")
    with configured_servers(tmp_path_factory.mktemp("nemesis-postgres")):
        yield


@pytest.fixture
def historical_database(database):
    from tests.support.historical_database import historical_database_fixture

    with historical_database_fixture(database) as private:
        yield private
