"""Real PostgreSQL upgrade, permissions and immutable relational snapshots."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, inspect, select, text, update
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from calorie_app.db.models import Product, ProductSource, ProductVersion, UserAccount
from calorie_app.health import EXPECTED_REVISION
from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    OfflinePackageProduct,
    OfflinePackageRation,
    OfflinePackageSource,
    Ration,
    RationComponent,
    RationPageToken,
    RationVersion,
)

pytestmark = pytest.mark.integration
HASH = "a" * 64


def snapshot(connection):
    tables = {
        "user_accounts": ("id", "issuer", "subject", "state", "generation", "created_at"),
        "product_sources": ("id", "description", "status"),
        "products": ("id",),
        "product_versions": (
            "product_id",
            "revision",
            "source_id",
            "name",
            "basis_unit",
            "energy_kcal",
            "protein_g",
            "fat_g",
            "carbs_g",
        ),
    }
    return {
        table: list(
            connection.exec_driver_sql(
                f"SELECT {', '.join(columns)} FROM app.{table} ORDER BY {columns[0]}"
            )
        )
        for table, columns in tables.items()
    }


def test_upgrade_0002_preserves_legacy_and_finite_nutrition(database):
    engine, migrate, _ = database
    migrate("downgrade", "0002_finite_nutrition")
    account_id, source_id, product_id = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(UserAccount).values(
                    id=account_id, issuer="https://catalog.test", subject=str(account_id)
                )
            )
            connection.execute(
                insert(ProductSource).values(
                    id=source_id, description="E1 preserved", status="verified"
                )
            )
            connection.execute(insert(Product).values(id=product_id))
            connection.execute(
                insert(ProductVersion).values(
                    product_id=product_id,
                    revision=1,
                    source_id=source_id,
                    name="E1 preserved",
                    basis_unit="g",
                    energy_kcal=Decimal("999999.999999"),
                    protein_g=None,
                    fat_g=Decimal("0"),
                    carbs_g=Decimal("42.123456"),
                )
            )
            before = snapshot(connection)
        migrate("upgrade", "head")
        with engine.connect() as connection:
            assert snapshot(connection) == before
            assert (
                connection.scalar(
                    select(ProductSource.content_hash).where(ProductSource.id == source_id)
                )
                is None
            )
            stored = connection.execute(
                select(ProductVersion).where(ProductVersion.product_id == product_id)
            ).one()
            assert stored.package_amount is None
            assert stored.status is None
            assert stored.content_hash is None
            assert connection.scalar(text("SELECT version_num FROM app.alembic_version")) == (
                EXPECTED_REVISION
            )
        checks = {
            item["name"]
            for item in inspect(engine).get_check_constraints("product_versions", schema="app")
        }
        assert "ck_product_versions_finite_nutrition" in checks
        migrate("check")
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                update(ProductVersion)
                .where(ProductVersion.product_id == product_id)
                .values(energy_kcal=Decimal("NaN"))
            )
    finally:
        migrate("upgrade", "head")
        with engine.begin() as connection:
            connection.execute(
                delete(ProductVersion).where(ProductVersion.product_id == product_id)
            )
            connection.execute(delete(Product).where(Product.id == product_id))
            connection.execute(delete(ProductSource).where(ProductSource.id == source_id))
            connection.execute(delete(UserAccount).where(UserAccount.id == account_id))


@pytest.fixture
def catalog_graph(database):
    engine, _, _ = database
    with engine.connect() as connection:
        transaction = connection.begin()
        source_id, product_id, ration_id, package_id = (uuid4() for _ in range(4))
        connection.execute(
            insert(ProductSource).values(
                id=source_id,
                description="Synthetic source",
                status="verified",
                document_id="test",
                basis="per_100_g",
                missing_data=[],
                notes=[],
                content_hash=HASH,
            )
        )
        connection.execute(insert(Product).values(id=product_id))
        connection.execute(
            insert(ProductVersion).values(
                product_id=product_id,
                revision=1,
                source_id=source_id,
                name="Synthetic product",
                basis_unit="g",
                aliases=[],
                package_amount=Decimal("100"),
                package_unit="g",
                source_locator="test row",
                status="verified",
                content_hash=HASH,
            )
        )
        connection.execute(insert(Ration).values(id=ration_id))
        connection.execute(
            insert(RationVersion).values(
                ration_id=ration_id,
                revision=1,
                name="Synthetic ration",
                status="verified",
                source_id=source_id,
                complete=True,
                excluded_items=[],
            )
        )
        connection.execute(
            insert(RationComponent).values(
                ration_id=ration_id,
                ration_revision=1,
                position=1,
                group_name="Meal",
                product_id=product_id,
                product_revision=1,
                amount=Decimal("100"),
                unit="g",
                optional=False,
            )
        )
        connection.execute(
            update(RationVersion)
            .where(RationVersion.ration_id == ration_id)
            .values(content_hash=HASH)
        )
        connection.execute(insert(OfflineChannel).values(package_id=package_id, kind="official"))
        connection.execute(
            insert(OfflinePackage).values(
                package_id=package_id,
                release=1,
                schema_version=1,
                min_reader_version=1,
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
                state="draft",
                content_hash=HASH,
                product_count=1,
                ration_count=1,
                component_count=1,
                source_count=1,
            )
        )
        connection.execute(
            insert(OfflinePackageProduct).values(
                package_id=package_id, release=1, product_id=product_id, product_revision=1
            )
        )
        connection.execute(
            insert(OfflinePackageRation).values(
                package_id=package_id, release=1, ration_id=ration_id, ration_revision=1
            )
        )
        connection.execute(
            insert(OfflinePackageSource).values(
                package_id=package_id, release=1, source_id=source_id
            )
        )
        try:
            yield connection, source_id, product_id, ration_id, package_id
        finally:
            transaction.rollback()


def rejected(connection, statement, exception=IntegrityError):
    with pytest.raises(exception), connection.begin_nested():
        connection.execute(statement)


def test_snapshots_and_ration_components_are_immutable(catalog_graph):
    connection, source_id, product_id, ration_id, _ = catalog_graph
    for model, predicate in (
        (ProductSource, ProductSource.id == source_id),
        (ProductVersion, ProductVersion.product_id == product_id),
        (RationVersion, RationVersion.ration_id == ration_id),
    ):
        rejected(connection, update(model).where(predicate).values(content_hash=None))
        rejected(connection, delete(model).where(predicate))
    rejected(
        connection,
        update(RationComponent)
        .where(RationComponent.ration_id == ration_id)
        .values(amount=Decimal("101")),
    )
    rejected(connection, delete(RationComponent).where(RationComponent.ration_id == ration_id))
    rejected(
        connection,
        insert(RationComponent).values(
            ration_id=ration_id,
            ration_revision=1,
            position=2,
            group_name="Meal",
            product_id=product_id,
            product_revision=1,
            amount=Decimal("1"),
            unit="g",
            optional=False,
        ),
    )
    # The new revision can still be created without touching the old snapshot.
    connection.execute(
        insert(ProductVersion).values(
            product_id=product_id,
            revision=2,
            source_id=source_id,
            name="Revision 2",
            basis_unit="g",
            aliases=[],
            package_amount=Decimal("100"),
            package_unit="g",
            source_locator="test row",
            status="verified",
            content_hash="b" * 64,
        )
    )
    assert (
        connection.scalar(
            select(ProductVersion.name).where(
                ProductVersion.product_id == product_id, ProductVersion.revision == 1
            )
        )
        == "Synthetic product"
    )


def test_package_sealing_publishing_and_channel_are_immutable(catalog_graph):
    connection, _, _, _, package_id = catalog_graph
    predicate = OfflinePackage.package_id == package_id
    rejected(connection, update(OfflinePackage).where(predicate).values(content_hash="b" * 64))
    rejected(
        connection,
        update(OfflineChannel)
        .where(OfflineChannel.package_id == package_id)
        .values(active_release=1),
    )
    connection.execute(update(OfflinePackage).where(predicate).values(sealed=True))
    for model in (OfflinePackageProduct, OfflinePackageRation, OfflinePackageSource):
        rejected(connection, delete(model).where(model.package_id == package_id))
        rejected(connection, update(model).where(model.package_id == package_id).values(release=2))
    rejected(connection, update(OfflinePackage).where(predicate).values(sealed=False))
    connection.execute(
        update(OfflinePackage)
        .where(predicate)
        .values(
            state="published",
            sha256=HASH,
            compressed_bytes=100,
            uncompressed_bytes=1000,
            artifact_path="official/test/base-pl.1.json.gz",
        )
    )
    connection.execute(
        update(OfflineChannel)
        .where(OfflineChannel.package_id == package_id)
        .values(active_release=1)
    )
    rejected(connection, update(OfflinePackage).where(predicate).values(sha256="b" * 64))
    rejected(
        connection,
        update(OfflineChannel)
        .where(OfflineChannel.package_id == package_id)
        .values(active_release=None),
    )
    rejected(
        connection,
        update(OfflineChannel).where(OfflineChannel.package_id == package_id).values(kind="demo"),
    )
    rejected(connection, delete(OfflinePackage).where(predicate))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("0"), Decimal("-1")])
@pytest.mark.parametrize("column", ["package_amount", "density_amount"])
def test_new_numeric_checks_reject_nonfinite_or_nonpositive(catalog_graph, column, value):
    connection, source_id, product_id, _, _ = catalog_graph
    row = dict(
        product_id=product_id,
        revision=2,
        source_id=source_id,
        name="Invalid",
        basis_unit="g",
        **{column: value},
    )
    if column == "package_amount":
        row["package_unit"] = "g"
    else:
        row["density_source_id"] = source_id
    rejected(connection, insert(ProductVersion).values(**row))


@pytest.mark.parametrize("value", [Decimal("Infinity"), Decimal("-Infinity"), Decimal("1000000")])
def test_new_numeric_precision_rejects_overflow(catalog_graph, value):
    connection, source_id, product_id, _, _ = catalog_graph
    rejected(
        connection,
        insert(ProductVersion).values(
            product_id=product_id,
            revision=2,
            source_id=source_id,
            name="Invalid",
            basis_unit="g",
            package_amount=value,
            package_unit="g",
        ),
        DataError,
    )


def test_density_and_package_quantity_require_pairs(catalog_graph):
    connection, source_id, product_id, _, _ = catalog_graph
    row = dict(
        product_id=product_id, revision=2, source_id=source_id, name="Invalid", basis_unit="g"
    )
    for extra in (
        {"package_amount": Decimal("1")},
        {"package_unit": "g"},
        {"density_amount": Decimal("1")},
        {"density_source_id": source_id},
        {"package_amount": Decimal("1"), "package_unit": "kg"},
    ):
        rejected(connection, insert(ProductVersion).values(**(row | extra)))


def test_components_check_amount_unit_and_exact_product_revision(catalog_graph):
    connection, source_id, product_id, ration_id, _ = catalog_graph
    connection.execute(
        insert(RationVersion).values(
            ration_id=ration_id,
            revision=2,
            name="Unsealed revision",
            status="verified",
            source_id=source_id,
            complete=True,
            excluded_items=[],
        )
    )
    row = dict(
        ration_id=ration_id,
        ration_revision=2,
        position=1,
        group_name="Meal",
        product_id=product_id,
        product_revision=1,
        amount=Decimal("1"),
        unit="g",
        optional=False,
    )
    for extra in (
        {"amount": Decimal("NaN")},
        {"amount": Decimal("0")},
        {"amount": Decimal("-1")},
        {"unit": "kg"},
        {"product_revision": 99},
    ):
        rejected(connection, insert(RationComponent).values(**(row | extra)))
    connection.execute(insert(RationComponent).values(**row))


def test_package_seal_rejects_missing_membership_and_legacy_snapshot(catalog_graph):
    connection, source_id, product_id, _, package_id = catalog_graph
    predicate = OfflinePackage.package_id == package_id
    connection.execute(
        delete(OfflinePackageSource).where(OfflinePackageSource.package_id == package_id)
    )
    rejected(connection, update(OfflinePackage).where(predicate).values(sealed=True))
    connection.execute(
        insert(OfflinePackageSource).values(package_id=package_id, release=1, source_id=source_id)
    )
    connection.execute(
        insert(ProductVersion).values(
            product_id=product_id,
            revision=2,
            source_id=source_id,
            name="Legacy skeleton",
            basis_unit="g",
        )
    )
    connection.execute(
        update(OfflinePackageProduct)
        .where(OfflinePackageProduct.package_id == package_id)
        .values(product_revision=2)
    )
    rejected(connection, update(OfflinePackage).where(predicate).values(sealed=True))
    assert connection.scalar(select(OfflinePackage.sealed).where(predicate)) is False


@pytest.mark.parametrize("role", ["calorie_app_api", "calorie_app_worker"])
def test_runtime_permissions_preserve_e1_and_protect_catalog(catalog_graph, role):
    connection, _, _, ration_id, package_id = catalog_graph
    connection.execute(
        update(OfflinePackage).where(OfflinePackage.package_id == package_id).values(sealed=True)
    )
    connection.execute(
        update(OfflinePackage)
        .where(OfflinePackage.package_id == package_id)
        .values(
            state="published",
            sha256=HASH,
            compressed_bytes=100,
            uncompressed_bytes=1000,
            artifact_path="official/test/base-pl.1.json.gz",
        )
    )
    connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
    assert connection.scalar(select(Ration.id).where(Ration.id == ration_id)) == ration_id
    legacy_source, legacy_product = uuid4(), uuid4()
    connection.execute(
        insert(ProductSource).values(
            id=legacy_source, description="E1 runtime", status="unverified"
        )
    )
    connection.execute(insert(Product).values(id=legacy_product))
    connection.execute(
        insert(ProductVersion).values(
            product_id=legacy_product,
            revision=1,
            source_id=legacy_source,
            name="E1 runtime",
            basis_unit="g",
            energy_kcal=None,
        )
    )
    rejected(connection, insert(Ration).values(id=uuid4()), ProgrammingError)
    rejected(
        connection,
        update(ProductSource).where(ProductSource.id == legacy_source).values(content_hash=HASH),
        ProgrammingError,
    )
    token = insert(RationPageToken).values(
        id=uuid4(),
        package_id=package_id,
        release=1,
        after_id=ration_id,
        after_revision=1,
        limit=50,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    rejected(connection, token, ProgrammingError)
    rejected(connection, delete(RationPageToken), ProgrammingError)


def test_token_rejects_unpublished_snapshot(catalog_graph):
    connection, _, _, ration_id, package_id = catalog_graph
    rejected(
        connection,
        insert(RationPageToken).values(
            id=uuid4(),
            package_id=package_id,
            release=1,
            after_id=ration_id,
            after_revision=1,
            limit=50,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
