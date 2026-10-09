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
        "user_accounts",
        "products",
        "product_sources",
        "product_versions",
    }
    migrate("check")
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/ready").status_code == 200
        with engine.begin() as connection:
            connection.execute(text("UPDATE app.alembic_version SET version_num='wrong_revision'"))
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


def test_initial_downgrade_then_upgrade(database):
    engine, migrate, url = database
    migrate("downgrade", "base")
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/ready").status_code == 503
    migrate("upgrade", "head")
    migrate("check")
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/ready").status_code == 200
