from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.db.models import Product, ProductSource, ProductVersion, UserAccount
from calorie_app.health import EXPECTED_REVISION
from calorie_app.main import create_app

pytestmark = pytest.mark.integration


def test_migration_and_database_readiness(database):
    engine, migrate, url = database
    assert set(inspect(engine).get_table_names(schema="app")) == {
        "alembic_version",
        "energy_axes",
        "energy_versions",
        "energy_changes",
        "energy_analyses",
        "energy_receipts",
        "user_accounts",
        "products",
        "product_sources",
        "product_versions",
        "product_search_metadata",
        "rations",
        "ration_versions",
        "ration_components",
        "offline_channels",
        "offline_packages",
        "offline_package_products",
        "offline_package_rations",
        "offline_package_sources",
        "ration_page_tokens",
        "ration_page_token_tombstones",
        "catalog_timestamp_recoveries",
        "installation_state",
        "online_receipts",
        "user_profiles",
        "user_consents",
        "goal_timelines",
        "goal_versions",
        "diary_days",
        "meals",
        "meal_items",
        "weights",
        "product_drafts",
        "sync_counters",
        "sync_receipts",
        "sync_changes",
        "sync_reservations",
        "sync_recovery_mappings",
        "sync_sessions",
        "sync_session_items",
        "account_deletion_jobs",
        "deletion_ledger_source",
        "deletion_ledger_events",
        "deletion_ledger_operations",
        "deletion_ledger_receipts",
        "deletion_ledger_restore_receipts",
        "_ledger_account_context",
        "deleted_subjects",
        "_deletion_context",
        "read_admissions",
        "read_sessions",
        "read_session_items",
        "community_catalog_state",
        "community_products",
        "community_versions",
        "community_authors",
        "community_publication_bindings",
        "community_votes",
        "community_reports",
        "community_audit",
        "community_receipts",
        "community_quotas",
        "ai_controls",
        "ai_pools",
        "ai_analyses",
        "ai_jobs",
        "ai_photo_consents",
        "ai_decisions",
        "ai_receipts",
        "ai_admissions",
        "ai_energy_admissions",
        "ai_attempts",
        "ai_transport_permits",
        "ai_cleanup_intents",
        "motivation_accounts",
        "motivation_days",
        "motivation_badges",
        "ranking_affirmations",
        "ranking_sessions",
        "ranking_cursors",
        "nemesis_control",
        "nemesis_releases",
        "nemesis_challenges",
        "nemesis_slots",
        "nemesis_share_codes",
        "nemesis_receipts",
        "nemesis_admissions",
        "nemesis_cursors",
        "nemesis_projection_seeds",
        "nemesis_day_projections",
        "nemesis_final_results",
        "nemesis_runtime_contract",
    }
    migrate("check")
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/ready").status_code == 200
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE app.alembic_version SET version_num='0024_e9_history_graph'")
            )
        assert client.get("/health/ready").status_code == 503
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE app.alembic_version SET version_num=:revision"),
                {"revision": EXPECTED_REVISION},
            )


def test_identity_unique_and_transaction_rollback(database):
    engine, _, _ = database
    subject = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(UserAccount(id=uuid4(), issuer="https://example.test", subject=subject))
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(UserAccount(id=uuid4(), issuer="https://example.test", subject=subject))
    rolled_back_id = uuid4()
    with Session(engine) as session:
        session.add(
            UserAccount(id=rolled_back_id, issuer="https://example.test", subject="rollback")
        )
        session.flush()
        session.rollback()
    with Session(engine) as session:
        assert session.get(UserAccount, rolled_back_id) is None


def test_numeric_precision_null_and_constraints(database):
    engine, _, _ = database
    product_id, source_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add_all([Product(id=product_id), ProductSource(id=source_id, description="Demo")])
    row = dict(
        product_id=product_id,
        revision=1,
        source_id=source_id,
        name="Demo",
        basis_unit="ml",
        energy_kcal=Decimal("42.123456"),
        protein_g=None,
        fat_g=None,
        carbs_g=None,
    )
    with engine.begin() as connection:
        connection.execute(insert(ProductVersion).values(**row))
    with Session(engine) as session:
        version = session.get(ProductVersion, (product_id, 1))
        assert version.energy_kcal == Decimal("42.123456")
        assert version.protein_g is None
    for bad in (
        {"revision": 2, "energy_kcal": -1},
        {"revision": 2, "source_id": uuid4()},
        {"revision": 2, "basis_unit": "kg"},
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert(ProductVersion).values(**(row | bad)))


def test_runtime_role_has_no_ddl_and_can_read_health(database):
    engine, _, _ = database
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE ROLE e1_runtime_probe NOLOGIN")
        connection.exec_driver_sql("GRANT USAGE ON SCHEMA app TO e1_runtime_probe")
        connection.exec_driver_sql("GRANT SELECT ON ALL TABLES IN SCHEMA app TO e1_runtime_probe")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE e1_runtime_probe")
            assert connection.scalar(text("SELECT version_num FROM app.alembic_version"))
        with pytest.raises(ProgrammingError), engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE e1_runtime_probe")
            connection.exec_driver_sql("CREATE TABLE app.forbidden(id int)")
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP OWNED BY e1_runtime_probe")
            connection.exec_driver_sql("DROP ROLE e1_runtime_probe")


def test_initial_downgrade_then_upgrade(historical_database):
    engine, migrate, url = historical_database
    # E4 retains durable evidence and supports a compatible E3 image rollback;
    # dropping the foundation underneath those FKs is no longer a valid rollback.
    migrate("downgrade", "0008_diary_delete")
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/ready").status_code == 503
    migrate("upgrade", EXPECTED_REVISION)
    migrate("check")
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/ready").status_code == 200
