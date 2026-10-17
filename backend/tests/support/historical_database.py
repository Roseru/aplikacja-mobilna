"""Dedicated pre-ledger migration regression DB, never a downgrade of live evidence."""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


@contextmanager
def historical_database_fixture(base):
    admin_engine, _, base_url = base
    name = "ledger_history_" + uuid4().hex[:12] + "_test"
    admin = create_engine(
        admin_engine.url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}" OWNER calorie_app_migrator')
        connection.exec_driver_sql(f'REVOKE ALL ON DATABASE "{name}" FROM PUBLIC')
        connection.exec_driver_sql(
            f'GRANT CONNECT ON DATABASE "{name}" TO calorie_app_api,'
            "calorie_app_worker,calorie_app_deletion_operator"
        )
    engine = create_engine(admin_engine.url.set(database=name), hide_parameters=True)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))

    def migrate(action, *args):
        # Explicitly historical head for old migration tests. New0024->0025 and
        # downgrade/reupgrade are verified separately by deletion-ledger tests.
        args = tuple("0024_e9_history_graph" if value == "head" else value for value in args)
        with engine.begin() as connection:
            if action == "check":
                from alembic.autogenerate import compare_metadata
                from alembic.migration import MigrationContext

                from calorie_app.db.base import Base

                changes = compare_metadata(
                    MigrationContext.configure(
                        connection, opts={"include_schemas": True, "version_table_schema": "app"}
                    ),
                    Base.metadata,
                )
                assert changes == []
                return
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            config.attributes["connection"] = connection
            try:
                getattr(command, action)(config, *args)
            finally:
                config.attributes.pop("connection", None)

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        connection.exec_driver_sql(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT "
            "SELECT,INSERT,UPDATE,DELETE ON TABLES TO "
            "calorie_app_api,calorie_app_worker"
        )
    try:
        migrate("upgrade", "head")
        yield engine, migrate, engine.url.render_as_string(hide_password=False)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH(FORCE)')
        admin.dispose()
