from alembic import context

from calorie_app.core.config import Settings
from calorie_app.db.base import Base
from calorie_app.db.models import UserAccount  # noqa: F401
from calorie_app.db.session import make_engine
from calorie_app.modules.ai import models as ai_models  # noqa: F401
from calorie_app.modules.analytics.motivation import models as motivation_models  # noqa: F401
from calorie_app.modules.catalog import models as catalog_models  # noqa: F401
from calorie_app.modules.catalog.community import models as community_models  # noqa: F401
from calorie_app.modules.diary import models as diary_models  # noqa: F401
from calorie_app.modules.diary import read_models  # noqa: F401
from calorie_app.modules.energy import models as energy_models  # noqa: F401
from calorie_app.modules.identity import deletion_models  # noqa: F401
from calorie_app.modules.jobs import models as job_models  # noqa: F401
from calorie_app.modules.nemesis import models as nemesis_models  # noqa: F401
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
        # These private tables are defined/changed exclusively by versioned SQL.
        include_object=lambda obj, name, kind, reflected, compare_to: (
            not (
                kind == "table"
                and name
                in {
                    "deletion_ledger_source",
                    "deletion_ledger_events",
                    "deletion_ledger_operations",
                    "deletion_ledger_receipts",
                    "deletion_ledger_restore_receipts",
                    "_ledger_account_context",
                }
            )
        ),
    )
    with context.begin_transaction():
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS app")
        context.run_migrations()
        # Explicit read-only privileges, even without runtime default grants.
        connection.exec_driver_sql(
            "GRANT USAGE ON SCHEMA app TO calorie_app_api, calorie_app_worker"
        )
        # E7 has a separate minimal role; historic worker grants stay unchanged.
        if connection.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_ai_worker')"
        ).scalar():
            connection.exec_driver_sql("GRANT USAGE ON SCHEMA app TO calorie_app_ai_worker")
            connection.exec_driver_sql(
                "GRANT SELECT ON app.alembic_version TO calorie_app_ai_worker"
            )
        if connection.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_motivation_worker')"
        ).scalar():
            connection.exec_driver_sql("GRANT USAGE ON SCHEMA app TO calorie_app_motivation_worker")
            connection.exec_driver_sql(
                "GRANT SELECT ON app.alembic_version TO calorie_app_motivation_worker"
            )
        if connection.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_worker')"
        ).scalar():
            connection.exec_driver_sql("GRANT USAGE ON SCHEMA app TO calorie_app_nemesis_worker")
            connection.exec_driver_sql(
                "GRANT SELECT ON app.alembic_version TO calorie_app_nemesis_worker"
            )
        if connection.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer')"
        ).scalar():
            connection.exec_driver_sql("GRANT USAGE ON SCHEMA app TO calorie_app_nemesis_finalizer")
            connection.exec_driver_sql(
                "GRANT SELECT ON app.alembic_version TO calorie_app_nemesis_finalizer"
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
