from alembic import context

from calorie_app.core.config import Settings
from calorie_app.db.base import Base
from calorie_app.db.models import UserAccount  # noqa: F401
from calorie_app.db.session import make_engine
from calorie_app.modules.catalog import models as catalog_models  # noqa: F401
from calorie_app.modules.diary import models as diary_models  # noqa: F401
from calorie_app.modules.identity import deletion_models  # noqa: F401
from calorie_app.modules.profiles import models as profile_models  # noqa: F401
from calorie_app.modules.sync import models as sync_models  # noqa: F401
from calorie_app.modules.sync import snapshot_models  # noqa: F401

target_metadata = Base.metadata


def apply_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="app",
        include_schemas=True,
    )
    with context.begin_transaction():
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS app")
        context.run_migrations()
        # Explicit read-only privileges, even without runtime default grants.
        connection.exec_driver_sql(
            "GRANT USAGE ON SCHEMA app TO calorie_app_api, calorie_app_worker"
        )
        connection.exec_driver_sql(
            "GRANT SELECT ON TABLE app.alembic_version TO calorie_app_api, calorie_app_worker"
        )
        connection.exec_driver_sql(
            "REVOKE INSERT, UPDATE, DELETE ON TABLE app.alembic_version "
            "FROM calorie_app_api, calorie_app_worker"
        )


def run_migrations_online():
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        apply_migrations(supplied)
        return
    engine = make_engine(Settings())
    try:
        with engine.connect() as connection:
            apply_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Use online migrations with the migrator's DATABASE_URL")
run_migrations_online()
