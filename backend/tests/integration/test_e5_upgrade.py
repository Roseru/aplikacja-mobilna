"""Exact E4 relational graph preservation through E5 upgrade/downgrade/reupgrade."""

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.catalog.export import publish_package
from calorie_app.modules.catalog.service import import_catalog
from calorie_app.modules.diary.repository import day_for_date
from calorie_app.modules.identity.deletion import begin
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.profiles.schemas import ConsentInput
from calorie_app.modules.profiles.service import put_consents
from calorie_app.modules.sync.models import RecoveryMapping
from calorie_app.modules.sync.router import execute_one, preflight
from calorie_app.modules.sync.schemas import preflight_structure
from calorie_app.modules.sync.snapshots import pull

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
SECRET = SecretStr("e5" * 32)
E4_REVISION = "0011_e4_deletion"
NEW_TABLES = {"read_admissions", "read_sessions", "read_session_items"}


def _tables(connection):
    return list(
        connection.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='app' "
                "AND tablename <> 'alembic_version' ORDER BY tablename"
            )
        )
    )


def _rowsets(connection, tables):
    # PostgreSQL's canonical JSONB text preserves NUMERIC precision and all
    # nullable/audit fields. No Python float conversion or selected-column gaps.
    return {
        table: list(
            connection.scalars(
                text(
                    'SELECT to_jsonb(t)::text FROM app."'
                    + table.replace('"', '""')
                    + '" t ORDER BY to_jsonb(t)::text'
                )
            )
        )
        for table in tables
    }


def _example(kind):
    name = "diary-day" if kind == "diary_day" else kind.replace("_", "-")
    return json.loads((ROOT / f"contracts/examples/valid/{name}.json").read_text(encoding="utf-8"))


def _operation(boot, kind, *, entity=None, payload=None, base=None, action="upsert"):
    return {
        "operation_id": str(uuid4()),
        "entity_id": str(entity or uuid4()),
        "entity_type": kind,
        "action": action,
        "base_revision": base,
        "sync_epoch": boot["sync_epoch"],
        "payload": payload
        if payload is not None
        else _example(kind)
        if action == "upsert"
        else None,
    }


def _push(factory, principal, owner, boot, checkpoint, op):
    data = {
        "protocol_version": 1,
        "sync_epoch": boot["sync_epoch"],
        "checkpoint": checkpoint,
        "operations": [op],
    }
    preflight_structure(data)
    authorized_owner, generation = preflight(factory, principal, data, SECRET)
    assert authorized_owner == owner
    return execute_one(factory, owner, generation, data, op, SECRET)[0]


def _seed_e4(engine, artifact_root):
    who = Principal("https://e5-upgrade.test/realms/fixture", str(uuid4()), frozenset({"user"}))
    with Session(engine) as session, session.begin():
        boot = bootstrap(session, who, uuid4())
    owner = UUID(boot["account_id"])
    factory = sessionmaker(engine, expire_on_commit=False)
    checkpoint = pull(factory, owner, {}, SECRET)["checkpoint"]
    operations = []
    for kind in ("profile", "goal", "meal", "weight", "product_draft"):
        payload = _example(kind)
        if kind == "meal":
            payload["goal_id"] = operations[1]["entity_id"]
        op = _operation(boot, kind, payload=payload)
        result = _push(factory, who, owner, boot, checkpoint, op)
        assert result["status"] == "accepted", result
        operations.append(op)
    with Session(engine) as session:
        day_id = day_for_date(session, owner, datetime(2026, 10, 9).date()).id
    op = _operation(boot, "diary_day", entity=day_id, payload=_example("diary_day"), base=1)
    assert _push(factory, who, owner, boot, checkpoint, op)["status"] == "accepted"
    operations.append(op)
    tombstone = _operation(boot, "weight")
    assert _push(factory, who, owner, boot, checkpoint, tombstone)["status"] == "accepted"
    deleted = _operation(
        boot, "weight", entity=UUID(tombstone["entity_id"]), base=1, action="delete"
    )
    assert _push(factory, who, owner, boot, checkpoint, deleted)["status"] == "accepted"
    operations.extend((tombstone, deleted))
    with Session(engine) as session, session.begin():
        put_consents(
            session,
            owner,
            ConsentInput(ranking=True, automatic_energy_adjustment=False),
            1,
            uuid4(),
            1,
        )
        session.add(
            RecoveryMapping(
                owner_id=owner,
                source_epoch=uuid4(),
                source_entity_id=uuid4(),
                entity_type="weight",
                target_entity_id=UUID(operations[3]["entity_id"]),
            )
        )
    # Keep a non-final E4 snapshot with actual entities, mappings, receipts and
    # their immutable materialization, rather than fabricating a SyncSession row.
    frozen = pull(
        factory,
        owner,
        {"limit": 1, "recovery_operation_ids": [op["operation_id"] for op in operations]},
        SECRET,
    )
    assert frozen["snapshot_token"] and frozen["page_token"] and frozen["checkpoint"] is None
    package = json.loads((ROOT / "backend/data/demo/seed.json").read_text(encoding="utf-8"))
    imported = import_catalog(engine, package)
    publish_package(engine, imported.package_id, imported.release, artifact_root)
    with Session(engine) as session, session.begin():
        other = Principal(who.issuer, str(uuid4()), frozenset({"user"}))
        other_id = UUID(bootstrap(session, other, uuid4())["account_id"])
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE calorie_app_deletion_operator"))
        begin(connection, other_id, uuid4(), 1)


def _assert_new_acl(connection):
    signatures = {
        "admit_read_session(uuid)": "calorie_app_api",
        "discard_unpaged_read(uuid,uuid)": "calorie_app_api",
        "prune_read_sessions(uuid,integer)": "calorie_app_worker",
    }
    roles = ("calorie_app_api", "calorie_app_worker", "calorie_app_deletion_operator")
    for signature, authorized in signatures.items():
        for role in roles:
            allowed = connection.scalar(
                text("SELECT has_function_privilege(:role,:fn,'EXECUTE')"),
                {"role": role, "fn": "app." + signature},
            )
            assert allowed is (role == authorized), (signature, role)
        public = connection.scalar(
            text(
                "SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL "
                "aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                "WHERE p.oid=to_regprocedure(:fn) AND a.grantee=0 AND a.privilege_type='EXECUTE'"
            ),
            {"fn": "app." + signature},
        )
        assert public == 0, signature
        function = connection.execute(
            text(
                "SELECT prosecdef,pg_get_userbyid(proowner) AS owner,proconfig "
                "FROM pg_proc WHERE oid=to_regprocedure(:fn)"
            ),
            {"fn": "app." + signature},
        ).one()
        assert function.prosecdef is True
        assert function.owner == "calorie_app_migrator"
        assert len(function.proconfig) == 1
        assert function.proconfig[0].replace(" ", "") == "search_path=pg_catalog,pg_temp"
    for role in roles:
        for table in NEW_TABLES:
            for privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
            ):
                expected = (
                    role == "calorie_app_api"
                    and table != "read_admissions"
                    and privilege in {"SELECT", "INSERT"}
                )
                assert (
                    connection.scalar(
                        text("SELECT has_table_privilege(:role,:table,:privilege)"),
                        {"role": role, "table": "app." + table, "privilege": privilege},
                    )
                    is expected
                )
    for table in NEW_TABLES:
        columns = list(
            connection.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='app' AND table_name=:table ORDER BY ordinal_position"
                ),
                {"table": table},
            )
        )
        for role in roles:
            for column in columns:
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    expected = role == "calorie_app_api" and (
                        table != "read_admissions"
                        and privilege in {"SELECT", "INSERT"}
                        or table == "read_sessions"
                        and privilege == "UPDATE"
                        and column in {"item_count", "byte_count"}
                    )
                    actual = connection.scalar(
                        text("SELECT has_column_privilege(:role,:table,:column,:privilege)"),
                        {
                            "role": role,
                            "table": "app." + table,
                            "column": column,
                            "privilege": privilege,
                        },
                    )
                    assert actual is expected, (role, table, column, privilege)


def test_e4_entire_rowsets_survive_e5_upgrade_downgrade_reupgrade(database, tmp_path):
    engine, migrate, url = database
    runtime = create_engine(
        url, hide_parameters=True, connect_args={"options": "-c role=calorie_app_api"}
    )
    app = create_app(
        Settings(database_url=url, environment="test", catalog_page_token_secret=SECRET),
        engine=runtime,
    )
    try:
        migrate("downgrade", E4_REVISION)
        _seed_e4(engine, tmp_path / "catalog-demo")
        with engine.connect() as connection:
            tables = _tables(connection)
            before = _rowsets(connection, tables)
            assert NEW_TABLES.isdisjoint(tables)
        # Cover each requested aggregate/audit, including an actual E4 full
        # snapshot and published demo. Empty old technical tables are compared too.
        for table in (
            "installation_state",
            "user_accounts",
            "user_profiles",
            "user_consents",
            "goal_timelines",
            "goal_versions",
            "meals",
            "meal_items",
            "weights",
            "diary_days",
            "product_drafts",
            "online_receipts",
            "sync_receipts",
            "sync_changes",
            "sync_counters",
            "sync_reservations",
            "sync_recovery_mappings",
            "sync_sessions",
            "sync_session_items",
            "offline_channels",
            "offline_packages",
            "offline_package_products",
            "offline_package_rations",
            "offline_package_sources",
            "product_sources",
            "products",
            "product_versions",
            "rations",
            "ration_versions",
            "ration_components",
            "account_deletion_jobs",
            "deleted_subjects",
        ):
            assert before[table], table
        with TestClient(app) as client:
            assert client.get("/health/ready").status_code == 503
            migrate("upgrade", "head")
            assert client.get("/health/ready").status_code == 200
            with engine.connect() as connection:
                assert set(_tables(connection)) == set(tables) | NEW_TABLES
                assert _rowsets(connection, tables) == before
                _assert_new_acl(connection)
            migrate("downgrade", E4_REVISION)
            assert client.get("/health/ready").status_code == 503
            with engine.connect() as connection:
                assert _tables(connection) == tables
                assert _rowsets(connection, tables) == before
                for function in (
                    "admit_read_session(uuid)",
                    "discard_unpaged_read(uuid,uuid)",
                    "prune_read_sessions(uuid,integer)",
                ):
                    assert (
                        connection.scalar(
                            text("SELECT to_regprocedure(:name)"), {"name": "app." + function}
                        )
                        is None
                    )
            migrate("upgrade", "head")
            assert client.get("/health/ready").status_code == 200
            with engine.connect() as connection:
                assert _rowsets(connection, tables) == before
                _assert_new_acl(connection)
    finally:
        runtime.dispose()
        migrate("upgrade", "head")
        # The database fixture already refuses non-*_test and non-PG17 targets.
        # Clean only this disposable graph; retain its installation epoch.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE app.user_accounts,app.account_deletion_jobs,"
                    "app.deleted_subjects,app._deletion_context,app.offline_channels,app.product_sources,"
                    "app.products,app.rations CASCADE"
                )
            )
