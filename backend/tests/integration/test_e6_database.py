"""Real PostgreSQL E6 ACL, immutable snapshots, admission, purge and rollback."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def payload(name="Synthetic E6 soup", energy="200"):
    snapshot = {
        "name": name,
        "aliases": [],
        "brand": None,
        "variant": None,
        "basis_unit": "g",
        "energy_kcal": energy,
        "protein_g": "2",
        "fat_g": "4",
        "carbs_g": "20",
        "package_amount": "100",
        "package_unit": "g",
        "density_amount": None,
        "density_source_description": None,
        "source_locator": "synthetic recipe",
        "preparation": None,
    }
    identity = {
        "brand": {"state": "not_applicable", "value": None},
        "variant": {"state": "not_applicable", "value": None},
        "composition": {"state": "known", "value": ["water", "rice"]},
    }
    metadata = {
        "source_kind": "recipe",
        "source_description": "synthetic recipe",
        "ingredients": ["water", "rice"],
        "recipe": None,
        "identity": identity,
        "normalized_identity": identity,
        "normalized_names": [name.casefold()],
        "identity_key": "a" * 64,
        "search_text": name.casefold(),
    }
    return snapshot, metadata


def account(connection):
    owner = uuid4()
    connection.execute(
        text("INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:i,:s)"),
        {"id": owner, "i": "https://e6-database.test", "s": str(owner)},
    )
    return owner


def create(connection, product=None, revision=1, *, values=None):
    product, source = product or uuid4(), uuid4()
    snap, meta = values or payload()
    connection.execute(
        text(
            "SELECT app.create_community_version(:p,:r,:s,NULL,CAST(:v AS jsonb),CAST(:m AS jsonb))"
        ),
        {"p": product, "r": revision, "s": source, "v": json.dumps(snap), "m": json.dumps(meta)},
    )
    return product, source


@pytest.fixture
def transaction(database):
    engine, _, _ = database
    with engine.connect() as connection:
        outer = connection.begin()
        yield connection
        outer.rollback()


@pytest.mark.parametrize(
    "role", ["calorie_app_api", "calorie_app_worker", "calorie_app_deletion_operator"]
)
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO app.products(id) VALUES(gen_random_uuid())",
        "INSERT INTO app.product_sources(id,description,status) "
        "VALUES(gen_random_uuid(),'x','unverified')",
        "UPDATE app.product_sources SET description='x' WHERE false",
        "UPDATE app.product_versions SET energy_kcal=1 WHERE false",
        "DELETE FROM app.product_versions WHERE false",
        "INSERT INTO app.community_audit(id,action) VALUES(gen_random_uuid(),'spoof')",
        "UPDATE app.community_audit SET reason='spoof' WHERE false",
        "DELETE FROM app.community_audit WHERE false",
        "UPDATE app.community_versions SET source_kind='label' WHERE false",
        "UPDATE app.community_catalog_state SET revision=0 WHERE id=1",
        "CREATE TABLE app.e6_forbidden(id integer)",
    ],
)
def test_effective_runtime_table_column_and_audit_acl(transaction, role, statement):
    with pytest.raises(DBAPIError), transaction.begin_nested():
        transaction.exec_driver_sql("SET LOCAL ROLE " + role)
        transaction.exec_driver_sql(statement)


def test_public_and_role_execution_scope(transaction):
    api_only = [
        "lock_community_catalog(boolean)",
        "bump_community_catalog(boolean)",
        "create_community_version(uuid,integer,uuid,uuid,jsonb,jsonb)",
        "append_community_audit(jsonb)",
        "admit_community_operation(uuid,text)",
    ]
    for signature in api_only:
        for role in ["calorie_app_api", "calorie_app_worker", "calorie_app_deletion_operator"]:
            granted = transaction.scalar(
                text("SELECT has_function_privilege(:r,:f,'EXECUTE')"),
                {"r": role, "f": "app." + signature},
            )
            assert granted is (role == "calorie_app_api")
        assert not transaction.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_proc p,"
                "LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                "WHERE p.oid=CAST(:f AS regprocedure) AND a.grantee=0 AND "
                "a.privilege_type='EXECUTE')"
            ),
            {"f": "app." + signature},
        )
        assert transaction.scalar(
            text("SELECT proconfig FROM pg_proc WHERE oid=CAST(:f AS regprocedure)"),
            {"f": "app." + signature},
        ) == ["search_path=pg_catalog, pg_temp"]
    for role in ["calorie_app_api", "calorie_app_deletion_operator"]:
        with pytest.raises(DBAPIError), transaction.begin_nested():
            transaction.exec_driver_sql("SET LOCAL ROLE " + role)
            transaction.execute(text("SELECT app.prune_community_receipts(:o,1)"), {"o": uuid4()})


def test_create_seals_source_version_and_exact_metadata(transaction):
    transaction.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
    product, source = create(transaction)
    row = transaction.execute(
        text(
            "SELECT p.content_hash,s.content_hash,s.status,p.status "
            "FROM app.product_versions p JOIN app.product_sources s "
            "ON s.id=p.source_id WHERE p.product_id=:p"
        ),
        {"p": product},
    ).one()
    assert len(row[0]) == 64 and row[0] == row[1]
    assert row[2:] == ("unverified", "unverified")
    transaction.exec_driver_sql("RESET ROLE")
    for sql in [
        "UPDATE app.product_versions SET name='new' WHERE product_id=:p",
        "DELETE FROM app.product_versions WHERE product_id=:p",
        "UPDATE app.product_sources SET description='new' WHERE id=:s",
        "UPDATE app.community_versions SET recipe='new' WHERE product_id=:p",
    ]:
        with pytest.raises(DBAPIError), transaction.begin_nested():
            transaction.execute(text(sql), {"p": product, "s": source})


def test_community_function_cannot_adopt_shared_product(transaction):
    product = uuid4()
    transaction.execute(text("INSERT INTO app.products VALUES(:p)"), {"p": product})
    with pytest.raises(DBAPIError), transaction.begin_nested():
        transaction.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
        create(transaction, product)
    assert not transaction.scalar(
        text("SELECT EXISTS(SELECT 1 FROM app.community_products WHERE product_id=:p)"),
        {"p": product},
    )


def test_state_complete_exact_revision_and_guarded_compression(transaction):
    a, _ = create(transaction)
    b, _ = create(transaction)
    c, _ = create(transaction)
    d, _ = create(transaction)
    transaction.execute(
        text(
            "UPDATE app.community_products SET canonical_id=:b,state_revision=2 WHERE product_id=:a"
        ),
        {"a": a, "b": b},
    )
    with pytest.raises(DBAPIError), transaction.begin_nested():
        transaction.execute(
            text(
                "UPDATE app.community_products SET canonical_id=:c,state_revision=3 WHERE "
                "product_id=:a"
            ),
            {"a": a, "c": c},
        )
    transaction.execute(
        text(
            "UPDATE app.community_products SET canonical_id=:c,state_revision=2 WHERE product_id=:b"
        ),
        {"b": b, "c": c},
    )
    transaction.execute(
        text(
            "UPDATE app.community_products SET canonical_id=:c,state_revision=3 WHERE product_id=:a"
        ),
        {"a": a, "c": c},
    )
    for sql in [
        "UPDATE app.community_products SET canonical_id=:a,state_revision=2 WHERE product_id=:c",
        "UPDATE app.community_products SET current_revision=99,state_revision=2 WHERE "
        "product_id=:d",
        "UPDATE app.community_products SET visibility='hidden' WHERE product_id=:d",
    ]:
        with pytest.raises(DBAPIError), transaction.begin_nested():
            transaction.execute(text(sql), {"a": a, "c": c, "d": d})
    incomplete, _ = create(transaction, values=payload(energy=None))
    with pytest.raises(DBAPIError), transaction.begin_nested():
        transaction.execute(
            text(
                "UPDATE app.community_products SET verification='verified',state_revision=2 "
                "WHERE product_id=:p"
            ),
            {"p": incomplete},
        )


def test_long_normalized_name_index_hash_is_selector_only(transaction):
    original = "\ufdfa" * 2000
    expanded = "صلى الله عليه وسلم" * 2000
    snap, meta = payload(original)
    meta["normalized_names"] = [expanded]
    meta["search_text"] = expanded
    product, _ = create(transaction, values=(snap, meta))
    row = transaction.execute(
        text(
            "SELECT normalized_names,normalized_name_hashes FROM app.community_versions WHERE "
            "product_id=:p"
        ),
        {"p": product},
    ).one()
    assert row[0] == [expanded]
    assert row[1] == [hashlib.sha256(expanded.encode()).hexdigest()]


@pytest.mark.parametrize(
    "kind,limit", [("products", 20), ("reports", 50), ("votes", 200), ("receipts", 1000)]
)
def test_admission_persistent_exact_daily_caps(transaction, kind, limit):
    owner = account(transaction)
    transaction.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
    sql = text("SELECT app.admit_community_operation(:o,:k)")
    assert all(transaction.scalar(sql, {"o": owner, "k": kind}) for _ in range(limit))
    assert transaction.scalar(sql, {"o": owner, "k": kind}) is False
    assert (
        transaction.scalar(
            text("SELECT " + kind + " FROM app.community_quotas WHERE owner_id=:o"), {"o": owner}
        )
        == limit
    )


def test_retention_minimal_receipt_and_admission_survive(transaction):
    owner = account(transaction)
    epoch = transaction.scalar(text("SELECT sync_epoch FROM app.installation_state"))
    key = uuid4()
    transaction.execute(
        text(
            "INSERT INTO "
            "app.community_receipts(owner_id,operation_kind,operation_id,request_hash,generation,sync_epoch,status_code,response_payload,result_minimal,created_at)"
            " "
            "VALUES(:o,'publish',:k,:h,1,:e,201,'{\"decision\":\"new_product\"}'::jsonb,jsonb_build_object('executed',true),clock_timestamp()-interval"
            " '61 days')"
        ),
        {"o": owner, "k": key, "h": "a" * 64, "e": epoch},
    )
    transaction.exec_driver_sql("SET LOCAL ROLE calorie_app_worker")
    result = transaction.scalar(text("SELECT app.prune_community_receipts(:o,1)"), {"o": owner})
    assert result["community_receipts"] == 1
    assert (
        transaction.scalar(text("SELECT app.prune_community_receipts(:o,1)"), {"o": owner})[
            "community_receipts"
        ]
        == 0
    )
    transaction.exec_driver_sql("RESET ROLE")
    row = transaction.execute(
        text(
            "SELECT request_hash,result_minimal,response_payload FROM app.community_receipts "
            "WHERE owner_id=:o AND operation_id=:k"
        ),
        {"o": owner, "k": key},
    ).one()
    assert row == ("a" * 64, {"executed": True}, None)


def test_purge_removes_attribution_and_private_feedback_preserves_shared_versions(transaction):
    owner = account(transaction)
    other = account(transaction)
    product, source = create(transaction)
    transaction.execute(
        text("INSERT INTO app.community_authors VALUES(:p,:o)"), {"p": product, "o": owner}
    )
    transaction.execute(
        text(
            "INSERT INTO app.community_publication_bindings(owner_id,draft_id,draft_revision,"
            "metadata_hash,product_id,product_revision,result_minimal) "
            "VALUES(:o,:d,1,:h,:p,1,jsonb_build_object('revision',1))"
        ),
        {"o": owner, "d": uuid4(), "h": "a" * 64, "p": product},
    )
    transaction.execute(
        text(
            "INSERT INTO app.community_receipts(owner_id,operation_kind,operation_id,request_hash,"
            "generation,sync_epoch,status_code,response_payload,result_minimal) "
            "SELECT :o,'publish',:k,:h,1,sync_epoch,201,'{}','{}' FROM app.installation_state"
        ),
        {"o": owner, "k": uuid4(), "h": "a" * 64},
    )
    transaction.execute(
        text(
            "INSERT INTO app.community_quotas(owner_id,day,receipts,products) "
            "VALUES(:o,(clock_timestamp() AT TIME ZONE 'UTC')::date,1,1)"
        ),
        {"o": owner},
    )
    transaction.execute(
        text("INSERT INTO app.community_votes VALUES(:o,:p,1,1,true),(:b,:p,-1,1,true)"),
        {"p": product, "o": owner, "b": other},
    )
    transaction.execute(
        text(
            "INSERT INTO "
            "app.community_reports(id,owner_id,product_id,product_revision,canonical_id,reason,description)"
            " VALUES(:id,:o,:p,1,:p,'private reason','private description')"
        ),
        {"id": uuid4(), "o": owner, "p": product},
    )
    transaction.scalar(
        text("SELECT app.append_community_audit(CAST(:event AS jsonb))"),
        {
            "event": json.dumps(
                {
                    "actor_id": str(owner),
                    "operation_id": str(uuid4()),
                    "action": "publish",
                    "reason": "private reason",
                    "new_ref": {"product_id": str(product), "revision": 1},
                    "target_id": str(product),
                }
            )
        },
    )
    before = transaction.scalar(
        text("SELECT to_jsonb(v)::text FROM app.product_versions v WHERE product_id=:p"),
        {"p": product},
    )
    operation = uuid4()
    transaction.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
    transaction.scalar(
        text("SELECT app.begin_account_deletion(:o,:op,1)"), {"o": owner, "op": operation}
    )
    transaction.scalar(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
    transaction.scalar(text("SELECT app.purge_deleted_account(:op)"), {"op": operation})
    transaction.scalar(text("SELECT app.purge_deleted_account(:op)"), {"op": operation})
    transaction.exec_driver_sql("RESET ROLE")
    assert (
        transaction.scalar(
            text("SELECT to_jsonb(v)::text FROM app.product_versions v WHERE product_id=:p"),
            {"p": product},
        )
        == before
    )
    assert (
        transaction.scalar(
            text("SELECT count(*) FROM app.product_sources WHERE id=:s"), {"s": source}
        )
        == 1
    )
    assert (
        transaction.scalar(
            text("SELECT count(*) FROM app.community_votes WHERE product_id=:p"), {"p": product}
        )
        == 1
    )
    assert (
        transaction.scalar(
            text("SELECT count(*) FROM app.community_authors WHERE owner_id=:o"), {"o": owner}
        )
        == 0
    )
    assert (
        transaction.scalar(
            text("SELECT count(*) FROM app.community_reports WHERE owner_id=:o"), {"o": owner}
        )
        == 0
    )
    row = transaction.execute(
        text(
            "SELECT actor_id,operation_id,reason,new_ref FROM app.community_audit WHERE "
            "target_id=:p"
        ),
        {"p": product},
    ).one()
    assert row[:3] == (None, None, None)
    assert row[3] == {"product_id": str(product), "revision": 1}
    for table in ("community_receipts", "community_quotas", "community_publication_bindings"):
        assert (
            transaction.scalar(
                text("SELECT count(*) FROM app." + table + " WHERE owner_id=:o"), {"o": owner}
            )
            == 0
        )


def rowsets(connection):
    names = inspect(connection).get_table_names(schema="app")
    return {
        name: list(
            connection.scalars(
                text(
                    'SELECT to_jsonb(t)::text FROM app."' + name + '" t ORDER BY to_jsonb(t)::text'
                )
            )
        )
        for name in names
    }


def test_empty_downgrade_reupgrade_preserves_existing_graph(database):
    engine, migrate, _ = database
    with engine.connect() as connection:
        old_tables = [
            n
            for n in inspect(connection).get_table_names(schema="app")
            if not n.startswith(("community_", "ai_"))
            and n not in {"alembic_version", "product_search_metadata"}
        ]
        before = {
            n: list(
                connection.scalars(
                    text(
                        'SELECT to_jsonb(t)::text FROM app."' + n + '" t ORDER BY to_jsonb(t)::text'
                    )
                )
            )
            for n in old_tables
        }
    migrate("downgrade", "0012_e5_reads")
    migrate("upgrade", "head")
    migrate("check")
    with engine.connect() as connection:
        after = {
            n: list(
                connection.scalars(
                    text(
                        'SELECT to_jsonb(t)::text FROM app."' + n + '" t ORDER BY to_jsonb(t)::text'
                    )
                )
            )
            for n in old_tables
        }
        assert after == before
        assert (
            connection.scalar(text("SELECT extname FROM pg_extension WHERE extname='pg_trgm'"))
            == "pg_trgm"
        )


def test_downgrade_atomic_refusal_detects_shared_orphan_artifact(database):
    engine, migrate, _ = database
    source = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO "
                "app.product_sources(id,description,status,document_id,basis,missing_data,notes,content_hash)"
                " "
                "VALUES(:s,'synthetic','unverified','community:orphan','per_100_g','[]','[]',:h)"
            ),
            {"s": source, "h": "a" * 64},
        )
    try:
        with engine.connect() as connection:
            before = rowsets(connection)
            schema = sorted(inspect(connection).get_table_names(schema="app"))
        with pytest.raises(DBAPIError):
            migrate("downgrade", "0012_e5_reads")
        with engine.connect() as connection:
            assert rowsets(connection) == before
            assert sorted(inspect(connection).get_table_names(schema="app")) == schema
            assert (
                connection.scalar(text("SELECT version_num FROM app.alembic_version"))
                == "0015_e7_ai"
            )
    finally:
        # Privileged fixture cleanup removes only this synthetic orphan, retaining all old rows.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE app.product_sources DISABLE TRIGGER catalog_snapshot_guard"
            )
            connection.execute(text("DELETE FROM app.product_sources WHERE id=:s"), {"s": source})
            connection.exec_driver_sql(
                "ALTER TABLE app.product_sources ENABLE TRIGGER catalog_snapshot_guard"
            )


def test_admission_real_concurrent_writers_cannot_exceed_cap(database):
    engine, _, _ = database
    with engine.begin() as connection:
        owner = account(connection)
    barrier = Barrier(8)

    def writer(_):
        barrier.wait(timeout=10)
        admitted = 0
        for _ in range(30):
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
                admitted += bool(
                    connection.scalar(
                        text("SELECT app.admit_community_operation(:o,'votes')"), {"o": owner}
                    )
                )
        return admitted

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(writer, range(8))) == 200
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT votes FROM app.community_quotas WHERE owner_id=:o"), {"o": owner}
                )
                == 200
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM app.community_quotas WHERE owner_id=:o"), {"o": owner}
            )
            connection.execute(text("DELETE FROM app.user_accounts WHERE id=:o"), {"o": owner})


def test_new_exact_version_preserves_historical_source_and_nutrition(transaction):
    product, source = create(transaction)
    before = transaction.scalar(
        text(
            "SELECT to_jsonb(v)::text FROM app.product_versions v "
            "WHERE product_id=:p AND revision=1"
        ),
        {"p": product},
    )
    original_source = transaction.scalar(
        text("SELECT to_jsonb(s)::text FROM app.product_sources s WHERE id=:s"), {"s": source}
    )
    create(transaction, product, 2, values=payload(energy="220"))
    transaction.execute(
        text(
            "UPDATE app.community_products SET current_revision=2,state_revision=2 "
            "WHERE product_id=:p"
        ),
        {"p": product},
    )
    assert (
        transaction.scalar(
            text(
                "SELECT to_jsonb(v)::text FROM app.product_versions v "
                "WHERE product_id=:p AND revision=1"
            ),
            {"p": product},
        )
        == before
    )
    assert (
        transaction.scalar(
            text("SELECT to_jsonb(s)::text FROM app.product_sources s WHERE id=:s"), {"s": source}
        )
        == original_source
    )
    assert (
        transaction.scalar(
            text("SELECT count(*) FROM app.product_versions WHERE product_id=:p"), {"p": product}
        )
        == 2
    )
