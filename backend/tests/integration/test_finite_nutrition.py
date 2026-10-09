from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import CheckViolation, NumericValueOutOfRange
from sqlalchemy import CheckConstraint, delete, insert, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError

from calorie_app.core.config import Settings
from calorie_app.db.models import Product, ProductSource, ProductVersion, UserAccount
from calorie_app.health import EXPECTED_REVISION
from calorie_app.main import create_app

pytestmark = pytest.mark.integration

NUTRITION_COLUMNS = ("energy_kcal", "protein_g", "fat_g", "carbs_g")
CHECK_NAME = "ck_product_versions_finite_nutrition"
OLD_CHECK_NAME = "ck_product_versions_nonnegative_nutrition"
VALID_VALUES = (None, Decimal("0"), Decimal("42.123456"), Decimal("999999.999999"))


def nutrition_row(connection):
    product_id, source_id = uuid4(), uuid4()
    connection.execute(insert(Product).values(id=product_id))
    connection.execute(
        insert(ProductSource).values(id=source_id, description="E1 test", status="unverified")
    )
    return dict(
        product_id=product_id,
        revision=1,
        source_id=source_id,
        name="E1 test",
        basis_unit="g",
        **dict.fromkeys(NUTRITION_COLUMNS),
    )


@pytest.fixture(params=("calorie_app_api", "calorie_app_worker"))
def runtime_connection(database, request):
    engine, _, _ = database
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            # Role names are fixed fixture parameters, never external input.
            connection.exec_driver_sql(f"SET LOCAL ROLE {request.param}")
            assert connection.scalar(text("SELECT current_user")) == request.param
            yield connection
        finally:
            transaction.rollback()


@pytest.mark.parametrize("column", NUTRITION_COLUMNS)
@pytest.mark.parametrize("value", VALID_VALUES, ids=("null", "zero", "six_places", "maximum"))
def test_runtime_accepts_valid_nutrition(runtime_connection, column, value):
    row = nutrition_row(runtime_connection) | {column: value}
    runtime_connection.execute(insert(ProductVersion).values(**row))
    stored = runtime_connection.execute(
        select(*(getattr(ProductVersion, name) for name in NUTRITION_COLUMNS)).where(
            ProductVersion.product_id == row["product_id"]
        )
    ).one()
    assert tuple(stored) == tuple(row[name] for name in NUTRITION_COLUMNS)


@pytest.mark.parametrize("column", NUTRITION_COLUMNS)
@pytest.mark.parametrize("value", (Decimal("NaN"), Decimal("-0.000001")), ids=("nan", "negative"))
def test_runtime_rejects_nutrition_by_check(runtime_connection, column, value):
    row = nutrition_row(runtime_connection) | {column: value}
    with pytest.raises(IntegrityError) as rejected:
        runtime_connection.execute(insert(ProductVersion).values(**row))
    assert isinstance(rejected.value.orig, CheckViolation)
    assert rejected.value.orig.sqlstate == "23514"
    assert rejected.value.orig.diag.constraint_name == CHECK_NAME


@pytest.mark.parametrize("column", NUTRITION_COLUMNS)
@pytest.mark.parametrize(
    "value",
    (Decimal("1000000"), Decimal("Infinity"), Decimal("-Infinity")),
    ids=("overflow", "infinity", "negative_infinity"),
)
def test_runtime_rejects_nutrition_by_numeric_precision(runtime_connection, column, value):
    row = nutrition_row(runtime_connection) | {column: value}
    with pytest.raises(DataError) as rejected:
        runtime_connection.execute(insert(ProductVersion).values(**row))
    assert isinstance(rejected.value.orig, NumericValueOutOfRange)
    assert rejected.value.orig.sqlstate == "22003"
    assert rejected.value.orig.diag.constraint_name is None


def test_actual_nutrition_check_matches_model(database):
    engine, _, _ = database
    checks = {
        item["name"]: item
        for item in inspect(engine).get_check_constraints("product_versions", schema="app")
    }
    assert set(checks) == {
        CHECK_NAME,
        "ck_product_versions_basis_unit",
        "ck_product_versions_positive_revision",
    }
    model_check = next(
        item
        for item in ProductVersion.__table__.constraints
        if isinstance(item, CheckConstraint) and item.name == CHECK_NAME
    )
    # Evaluate both predicates on unconstrained NUMERIC as well: the upper bound
    # must be in the CHECK itself, even where NUMERIC(12,6) would reject first.
    columns_sql = ", ".join(f"CAST(:{name} AS numeric) AS {name}" for name in NUTRITION_COLUMNS)
    predicate_sql = text(
        f"SELECT ({checks[CHECK_NAME]['sqltext']}), ({model_check.sqltext}) "
        f"FROM (SELECT {columns_sql}) AS nutrition"
    )
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conrelid='app.product_versions'::regclass AND conname=:name"
            ),
            {"name": CHECK_NAME},
        )
        for column in NUTRITION_COLUMNS:
            for value in (
                *VALID_VALUES,
                Decimal("NaN"),
                Decimal("-0.000001"),
                Decimal("1000000"),
                Decimal("Infinity"),
                Decimal("-Infinity"),
            ):
                result = connection.execute(
                    predicate_sql, dict.fromkeys(NUTRITION_COLUMNS) | {column: value}
                ).one()
                expected = value is None or (
                    value.is_finite() and 0 <= value <= Decimal("999999.999999")
                )
                assert tuple(result) == (expected, expected)


def data_snapshot(connection):
    # Decimal NaN does not equal itself in Python. Text keeps it comparable and
    # checks that even the invalid legacy value is preserved after a failed DDL.
    return {
        model.__tablename__: [
            tuple(str(value) if isinstance(value, Decimal) else value for value in row)
            for row in connection.execute(
                select(model.__table__).order_by(*model.__table__.primary_key)
            )
        ]
        for model in (UserAccount, ProductSource, Product, ProductVersion)
    }


@pytest.fixture
def legacy_database(database):
    engine, migrate, url = database
    migrate("downgrade", "0001_foundation")
    with engine.begin() as connection:
        row = nutrition_row(connection)
    try:
        yield engine, migrate, url, row
    finally:
        # Delete only records created by this test, including its legacy NaN.
        with engine.begin() as connection:
            connection.execute(
                delete(ProductVersion).where(ProductVersion.product_id == row["product_id"])
            )
            connection.execute(delete(Product).where(Product.id == row["product_id"]))
            connection.execute(delete(ProductSource).where(ProductSource.id == row["source_id"]))
        migrate("upgrade", "head")


@pytest.mark.parametrize("column", NUTRITION_COLUMNS)
def test_upgrade_preserves_data_and_readiness(legacy_database, column):
    engine, migrate, url, row = legacy_database
    with engine.begin() as connection:
        for revision, value in enumerate(VALID_VALUES, start=1):
            connection.execute(
                insert(ProductVersion).values(**(row | {"revision": revision, column: value}))
            )
        before = data_snapshot(connection)
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == "0001_foundation"
        )
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        migrate("upgrade", "head")
        assert client.get("/health/ready").status_code == 200
    with engine.connect() as connection:
        assert data_snapshot(connection) == before
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == EXPECTED_REVISION
        )
    migrate("check")


@pytest.mark.parametrize("column", NUTRITION_COLUMNS)
def test_upgrade_refuses_legacy_nan_without_partial_changes(legacy_database, column):
    engine, migrate, url, row = legacy_database
    with engine.begin() as connection:
        connection.execute(insert(ProductVersion).values(**(row | {column: Decimal("NaN")})))
        before = data_snapshot(connection)
    checks_before = inspect(engine).get_check_constraints("product_versions", schema="app")
    assert OLD_CHECK_NAME in {item["name"] for item in checks_before}
    with pytest.raises(IntegrityError) as rejected:
        migrate("upgrade", "head")
    assert isinstance(rejected.value.orig, CheckViolation)
    assert rejected.value.orig.diag.constraint_name == CHECK_NAME
    with engine.connect() as connection:
        assert data_snapshot(connection) == before
        assert (
            connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            == "0001_foundation"
        )
    assert inspect(engine).get_check_constraints("product_versions", schema="app") == checks_before
    with TestClient(create_app(Settings(database_url=url), engine=engine)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
