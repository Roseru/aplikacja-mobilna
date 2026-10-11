"""Complete E4/E6 rowsets and atomic E7 durable-evidence downgrade guards."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_e5_upgrade import _seed_e4
from test_e6_matching_pg import seed
from test_e7_runtime import create
from test_e7_runtime import e7 as e7_fixture

from calorie_app.modules.catalog.community.repository import lock_catalog

pytestmark = pytest.mark.integration
e7 = e7_fixture


def graph(engine, names=None):
    with engine.connect() as connection:
        names = names or [
            n
            for n in inspect(connection).get_table_names(schema="app")
            if not n.startswith("ai_") and n != "alembic_version"
        ]
        return {
            name: list(
                connection.scalars(
                    text(
                        'SELECT to_jsonb(t)::text FROM app."'
                        + name
                        + '" t ORDER BY to_jsonb(t)::text'
                    )
                )
            )
            for name in names
        }


def test_e7_empty_roundtrip_preserves_entire_filled_e4_e6_graph(e7, database, tmp_path):
    admin, migrate, _ = database
    migrate("downgrade", "0014_catalog_search")
    _seed_e4(admin, tmp_path / "catalogue-artifacts")
    with Session(admin) as session, session.begin():
        lock_catalog(session)
        seed(session, "123.456789", "g")
    before = graph(admin)
    for table in (
        "meals",
        "meal_items",
        "weights",
        "product_drafts",
        "sync_receipts",
        "online_receipts",
        "community_products",
        "community_versions",
        "product_sources",
        "offline_packages",
        "product_search_metadata",
    ):
        assert before[table], table
    migrate("upgrade", "head")
    assert graph(admin, list(before)) == before
    migrate("downgrade", "0014_catalog_search")
    assert graph(admin, list(before)) == before
    migrate("upgrade", "head")
    assert graph(admin, list(before)) == before
    migrate("check")


@pytest.mark.parametrize("artifact", ["photo", "cleanup_intent", "admission", "energy_admission"])
def test_e7_durable_evidence_refuses_before_ddl_with_exact_rowsets(e7, database, artifact):
    admin, migrate, _ = database
    owner = UUID(e7["boots"][0]["account_id"])
    if artifact == "photo":
        create(e7)
    else:
        with admin.begin() as connection:
            if artifact == "cleanup_intent":
                connection.execute(
                    text("INSERT INTO app.ai_cleanup_intents(storage_key) VALUES(:key)"),
                    {"key": uuid4().hex},
                )
            elif artifact == "admission":
                connection.execute(
                    text(
                        "INSERT INTO app.ai_admissions(owner_id,day,receipts) "
                        "VALUES(:owner,current_date,1)"
                    ),
                    {"owner": owner},
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO app.ai_energy_admissions(owner_id,accepted_at) "
                        "VALUES(:owner,clock_timestamp())"
                    ),
                    {"owner": owner},
                )
    with admin.connect() as connection:
        names = inspect(connection).get_table_names(schema="app")
    before = graph(admin, names)
    with pytest.raises(DBAPIError) as error:
        migrate("downgrade", "0014_catalog_search")
    assert error.value.orig.sqlstate == "23514"
    assert graph(admin, names) == before
