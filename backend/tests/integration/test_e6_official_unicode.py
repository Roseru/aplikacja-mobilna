"""NFKC/casefold/whitespace official selection without rewriting sealed history."""

import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_catalog_delivery import catalog_db, synthetic_official  # noqa: F401
from test_e5_upgrade import _discard_e8_upgrade_placeholders
from test_e6_community_publication import boot, community_db, draft, publication  # noqa: F401

from calorie_app.core.config import Settings
from calorie_app.health import EXPECTED_REVISION
from calorie_app.main import create_app
from calorie_app.modules.catalog.community.service import match_draft
from calorie_app.modules.catalog.export import export_package, publish_package
from calorie_app.modules.catalog.models import ProductSearchMetadata
from calorie_app.modules.catalog.service import import_catalog
from calorie_app.modules.diary.service import save_meal
from calorie_app.modules.identity.dependencies import current_principal

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
E8_TABLES = {
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
    "energy_axes",
    "energy_versions",
    "energy_changes",
    "energy_analyses",
    "energy_receipts",
}
CASES = [
    ("Straße Suppe", [], "STRASSE SUPPE"),
    ("Ｒｏｓｏｌ", [], "Rosol"),
    ("Different name", ["Straße Suppe"], "STRASSE SUPPE"),
    ("Different name", ["Ｆｕｌｌｗｉｄｔｈ"], "Fullwidth"),
    ("Straße\u00a0\u2003Suppe", [], "STRASSE SUPPE"),
    ("Straße Suppe", [], "Straße\u2009Suppe"),
] + [
    (
        "Different name",
        [f"Distinct alias {i}" for i in range(count - 1)] + ["Straße Suppe"],
        "STRASSE SUPPE",
    )
    for count in (50, 51, 100)
]


def package(name, aliases):
    value = synthetic_official(count=1)
    value["products"][0].update(name=name, aliases=aliases)
    return value


@pytest.mark.parametrize("name,aliases,query", CASES)
def test_official_normalized_candidates_real_api_and_runtime_acl(
    request, tmp_path, name, aliases, query
):
    engine = request.getfixturevalue("community_db")
    who, owner, epoch = boot(engine)
    value = package(name, aliases)
    imported = import_catalog(engine, value)
    assert not import_catalog(engine, value).created
    with Session(engine) as session:
        metadata = session.get(ProductSearchMetadata, (value["products"][0]["product_id"], 1))
        assert len(metadata.normalized_names) == len(aliases) + 1
    publish_package(engine, imported.package_id, 1, tmp_path)
    entity, _ = draft(engine, owner, name=query)
    data = publication(entity, aliases=[])
    settings = Settings(
        database_url=str(engine.url), environment="test", catalog_page_token_secret="e6" * 32
    )
    app = create_app(settings, engine=engine)
    app.dependency_overrides[current_principal] = lambda: who
    body = data.model_dump(mode="json", exclude={"selected_product", "confirm_new"})
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/products/matches", json=body, headers={"X-Sync-Epoch": str(epoch)}
        )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    result = response.json()
    assert result["decision"] == "manual_candidates"
    assert result["existing_product"] is None
    found = next(
        item
        for item in result["candidates"]
        if item["product"]["product_id"] == value["products"][0]["product_id"]
    )
    assert found["product"]["revision"] == 1
    assert found["provenance"] == "official" and found["high_confidence"] is False
    assert "shared_name" in found["reasons"] and "missing_composition" in found["reasons"]
    # Execute the same service with the actual restricted DB role, not superuser.
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL ROLE calorie_app_api"))
        assert match_draft(session, who, data, epoch)["candidates"] == result["candidates"]


def test_official_limit21_truncation_deterministic_and_indexed(request, tmp_path):
    engine = request.getfixturevalue("community_db")
    who, owner, epoch = boot(engine)
    value = package("Straße Suppe", [])
    base = value["products"][0]
    products = []
    products.append(copy.deepcopy(base))
    for _ in range(26):
        products.append(copy.deepcopy(base) | {"product_id": str(uuid4())})
    value["products"] = products
    value["counts"]["products"] = len(products)
    imported = import_catalog(engine, value)
    publish_package(engine, imported.package_id, 1, tmp_path)
    entity, _ = draft(engine, owner, name="STRASSE SUPPE")
    data = publication(entity, aliases=[])
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT") and "product_search_metadata" in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as session, session.begin():
            result = match_draft(session, who, data, epoch)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["decision"] == "manual_candidates" and result["truncated"] is True
    assert len(result["candidates"]) == 20
    assert [c["product"]["product_id"] for c in result["candidates"]] == sorted(
        p["product_id"] for p in products
    )[:20]
    assert len(statements) == 1
    sql, parameters = statements[0]
    assert "normalized_name_hashes &&" in sql and "search_text" in sql and "LIMIT" in sql
    assert 21 in parameters.values()
    assert "product_versions.name ILIKE" not in sql
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL enable_seqscan=off")
        # A tiny active package can choose exact PK lookups for the full join.
        # Prove GIN availability on its same selector without fixing join order.
        plan = connection.execute(
            text(
                "EXPLAIN SELECT product_id,revision FROM app.product_search_metadata WHERE "
                "(normalized_name_hashes && CAST(:h AS varchar[]) "
                "AND normalized_names && CAST(:n AS text[])) "
                "OR search_text ILIKE :q OR search_text % :v"
            ),
            {
                "h": [hashlib.sha256(b"strasse suppe").hexdigest()],
                "n": ["strasse suppe"],
                "q": "%strasse suppe%",
                "v": "strasse suppe",
            },
        ).all()
    details = "\n".join(row[0] for row in plan)
    assert "ix_product_search_metadata_names" in details, details
    assert "ix_product_search_metadata_trgm" in details, details


def frozen_table_rows(connection):
    tables = [
        name
        for name in inspect(connection).get_table_names(schema="app")
        if name not in ({"alembic_version", "product_search_metadata"} | E8_TABLES)
        and not name.startswith("ai_")
    ]
    return {
        name: list(
            connection.scalars(
                text(
                    'SELECT to_jsonb(t)::text FROM app."' + name + '" t ORDER BY to_jsonb(t)::text'
                )
            )
        )
        for name in tables
    }


def test_upgrade0013_backfill_down_reup_bytes_hash_history_readiness(request, tmp_path):
    engine = request.getfixturevalue("community_db")
    _, migrate, url = request.getfixturevalue("database")
    migrate("downgrade", "0013_e6_community")
    try:
        value = package(
            "Straße\u00a0Suppe", [f"Legacy alias {i}" for i in range(99)] + ["Ｆｕｌｌｗｉｄｔｈ"]
        )
        base = value["products"][0]
        value["products"].extend(
            copy.deepcopy(base)
            | {"product_id": str(uuid4()), "name": f"Batch fixture {i}", "aliases": []}
            for i in range(16)
        )
        value["counts"]["products"] = 17
        imported = import_catalog(engine, value)
        manifest = publish_package(engine, imported.package_id, 1, tmp_path)
        artifact = export_package(engine, imported.package_id, 1)
        who, owner, epoch = boot(engine)
        entity, _ = draft(engine, owner, name="Fullwidth")
        matching_request = publication(entity, aliases=[])
        meal = json.loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
        product = value["products"][0]
        meal["items"][0].update(
            name=product["name"],
            product={"product_id": product["product_id"], "revision": 1},
            nutrition_origin="catalog_snapshot",
            nutrition_per_100=product["nutrition_per_100"],
            quantity={"amount": "100", "unit": "ml"},
            basis_unit="ml",
        )
        with Session(engine) as session, session.begin():
            save_meal(session, owner, uuid4(), meal)
        rawfile = next(tmp_path.rglob("*.json.gz")).read_bytes()
        with engine.connect() as connection:
            before = frozen_table_rows(connection)
            assert len(before["meal_items"]) == 1 and len(before["meals"]) == 1
        settings = Settings(
            database_url=url, environment="test", catalog_page_token_secret="e6" * 32
        )
        with TestClient(create_app(settings, engine=engine)) as client:
            assert client.get("/health/ready").status_code == 503
        migrate("upgrade", "head")
        migrate("check")
        with engine.connect() as connection:
            assert frozen_table_rows(connection) == before
            assert connection.scalar(text("SELECT count(*) FROM app.product_search_metadata")) == 17
            row = connection.execute(
                select(ProductSearchMetadata).where(
                    ProductSearchMetadata.product_id == value["products"][0]["product_id"]
                )
            ).one()
            assert row.normalized_names == sorted(
                ["fullwidth", "strasse suppe"] + [f"legacy alias {i}" for i in range(99)]
            )
            assert len(row.normalized_names) == 101
            assert row.normalized_name_hashes == [
                hashlib.sha256(v.encode()).hexdigest() for v in row.normalized_names
            ]
        app = create_app(settings, engine=engine)
        app.dependency_overrides[current_principal] = lambda: who
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/products/matches",
                json=matching_request.model_dump(
                    mode="json", exclude={"selected_product", "confirm_new"}
                ),
                headers={"X-Sync-Epoch": str(epoch)},
            )
        assert response.status_code == 200
        result = response.json()
        assert result["decision"] == "manual_candidates"
        assert result["candidates"][0]["product"] == {
            "product_id": product["product_id"],
            "revision": 1,
        }
        assert result["candidates"][0]["high_confidence"] is False
        with engine.connect() as connection:
            assert frozen_table_rows(connection) == before
        assert export_package(engine, imported.package_id, 1) == artifact
        assert publish_package(engine, imported.package_id, 1, tmp_path) == manifest
        assert next(tmp_path.rglob("*.json.gz")).read_bytes() == rawfile
        assert not import_catalog(engine, value).created
        # No motivation worker/source hook runs in this pre-E8 fixture. Keep
        # every old source column and published byte in the assertions, and
        # discard only verified unprocessed E8 placeholders before its down/up.
        with engine.begin() as connection:
            _discard_e8_upgrade_placeholders(connection)
        migrate("downgrade", "0013_e6_community")
        with engine.connect() as connection:
            assert frozen_table_rows(connection) == before
        migrate("upgrade", "head")
        with engine.connect() as connection:
            assert frozen_table_rows(connection) == before
        with TestClient(create_app(settings, engine=engine)) as client:
            assert client.get("/health/ready").status_code == 200
        assert EXPECTED_REVISION == "0024_e9_history_graph"
    finally:
        migrate("upgrade", "head")


@pytest.mark.parametrize(
    "role", ["calorie_app_api", "calorie_app_worker", "calorie_app_deletion_operator"]
)
@pytest.mark.parametrize(
    "command",
    [
        "INSERT INTO app.product_search_metadata SELECT * FROM app.product_search_metadata",
        "UPDATE app.product_search_metadata SET search_text='spoof' WHERE false",
        "DELETE FROM app.product_search_metadata WHERE false",
        "TRUNCATE app.product_search_metadata",
    ],
)
def test_search_metadata_effective_runtime_acl(request, role, command):
    engine = request.getfixturevalue("community_db")
    with pytest.raises(DBAPIError) as failure, engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE " + role)
        connection.exec_driver_sql(command)
    assert failure.value.orig.sqlstate == "42501"
    with engine.connect() as connection:
        assert not connection.scalar(
            text(
                "SELECT has_any_column_privilege(:r,'app.product_search_metadata',"
                "'INSERT,UPDATE,REFERENCES')"
            ),
            {"r": role},
        )
        for column in (
            "product_id",
            "revision",
            "normalized_names",
            "normalized_name_hashes",
            "search_text",
        ):
            assert not connection.scalar(
                text(
                    "SELECT has_column_privilege(:r,'app.product_search_metadata',:c,"
                    "'INSERT,UPDATE,REFERENCES')"
                ),
                {"r": role, "c": column},
            )


def test_old_importer_on0014_is_atomically_fenced_without_metadata(request):
    engine = request.getfixturevalue("community_db")
    value = package("Straße Suppe", [])
    with patch("calorie_app.modules.catalog.service.metadata_installed", return_value=False):
        with pytest.raises(DBAPIError):
            import_catalog(engine, value)
    with engine.connect() as connection:
        for table in ("offline_packages", "product_versions", "product_sources", "products"):
            assert connection.scalar(text("SELECT count(*) FROM app." + table)) == 0
    assert import_catalog(engine, value).created


def test_exact_metadata_immutable_and_public_no_grants(request):
    engine = request.getfixturevalue("community_db")
    value = package("Straße Suppe", [])
    import_catalog(engine, value)
    for command in (
        "UPDATE app.product_search_metadata SET search_text='new'",
        "DELETE FROM app.product_search_metadata",
    ):
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.exec_driver_sql(command)
    with engine.connect() as connection:
        assert not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_class p, "
                "LATERAL aclexplode(coalesce(p.relacl,acldefault('r',p.relowner))) a "
                "WHERE p.oid='app.product_search_metadata'::regclass AND a.grantee=0)"
            )
        )
        for function in ("product_search_immutable_guard()", "catalog_search_membership_guard()"):
            assert not connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_proc p, "
                    "LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                    "WHERE p.oid=CAST(:f AS regprocedure) AND a.grantee=0 "
                    "AND a.privilege_type='EXECUTE')"
                ),
                {"f": "app." + function},
            )


def test_new_official_revision_uses_exact_metadata_without_rewriting_old_release(request, tmp_path):
    engine = request.getfixturevalue("community_db")
    who, owner, epoch = boot(engine)
    first = package("Straße Suppe", [])
    original = import_catalog(engine, first)
    publish_package(engine, original.package_id, 1, tmp_path)
    old_export = export_package(engine, original.package_id, 1)
    second = copy.deepcopy(first)
    second["release"] = 2
    second["products"][0].update(revision=2, name="Ｒｏｓｏｌ")
    second["rations"][0]["revision"] = 2
    second["rations"][0]["components"][0]["product"]["revision"] = 2
    current = import_catalog(engine, second)
    assert not import_catalog(engine, second).created
    publish_package(engine, current.package_id, 2, tmp_path)
    entity, _ = draft(engine, owner, name="Rosol")
    old_entity, _ = draft(engine, owner, name="STRASSE SUPPE")
    with Session(engine) as session, session.begin():
        result = match_draft(session, who, publication(entity, aliases=[]), epoch)
        old_result = match_draft(session, who, publication(old_entity, aliases=[]), epoch)
        versions = session.execute(
            select(ProductSearchMetadata.revision, ProductSearchMetadata.normalized_names).order_by(
                ProductSearchMetadata.revision
            )
        ).all()
    assert result["decision"] == "manual_candidates"
    assert result["candidates"][0]["product"] == {
        "product_id": first["products"][0]["product_id"],
        "revision": 2,
    }
    assert result["candidates"][0]["high_confidence"] is False
    assert old_result["candidates"] == []
    assert versions == [(1, ["strasse suppe"]), (2, ["rosol"])]
    assert export_package(engine, original.package_id, 1) == old_export
