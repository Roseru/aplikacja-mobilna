"""DELETE ACLs and account locks protect retained private history on PostgreSQL17."""

import copy
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from test_catalog_delivery import catalog_db, synthetic_official  # noqa: F401

from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.export import artifact_path, export_package, publish_package
from calorie_app.modules.catalog.service import import_catalog
from calorie_app.modules.diary.models import DiaryDay, Meal, ProductDraft, Weight
from calorie_app.modules.diary.repository import owned
from calorie_app.modules.diary.service import (
    delete_entity,
    meal_payload,
    remove_meal_item,
    save_diary_day,
    save_meal,
    save_product_draft,
    save_weight,
)
from calorie_app.modules.identity.models import UserAccount
from calorie_app.modules.identity.service import begin_deleting, bootstrap
from calorie_app.modules.profiles.schemas import ConsentInput, GoalPayload, ProfilePayload
from calorie_app.modules.profiles.service import create_goal, put_consents, save_profile

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/examples/valid"
ROLES = ("calorie_app_api", "calorie_app_worker")
PARENTS = {"diary_days": DiaryDay, "meals": Meal, "weights": Weight, "product_drafts": ProductDraft}


def example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def meal_with_items(count=2):
    payload = example("meal")
    original = payload["items"][0]
    payload["items"] = [
        copy.deepcopy(original) | {"item_id": str(uuid4()), "name": f"Synthetic item {index}"}
        for index in range(count)
    ]
    # A retained ration label exercises the snapshot as well as nutrition fields.
    payload["ration"] = {"ration_id": str(uuid4()), "revision": 1, "name": "Synthetic ration"}
    return payload


@pytest.fixture
def delete_owner(database):
    engine, _, _ = database
    owner = uuid4()
    with Session(engine) as session, session.begin():
        session.add(UserAccount(id=owner, issuer="https://delete.test", subject=str(owner)))
    try:
        yield engine, owner
    finally:
        # The database fixture first refuses anything except dedicated *_test DBs.
        # Immutable test history must be removed before E1/E2 downgrade regression.
        with engine.begin() as connection:
            connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")


def seed_parents(session, owner):
    ids = {table: uuid4() for table in PARENTS}
    save_diary_day(
        session, owner, ids["diary_days"], example("diary-day") | {"local_date": "2026-10-10"}
    )
    save_meal(session, owner, ids["meals"], meal_with_items())
    save_weight(session, owner, ids["weights"], example("weight"))
    save_product_draft(session, owner, ids["product_drafts"], example("product-draft"))
    return ids


def owner_snapshot(engine, owner):
    with engine.connect() as connection:
        return {
            table: list(
                connection.scalars(
                    text(
                        f"SELECT to_jsonb(t)::text FROM app.{table} t "
                        "WHERE owner_id=:owner ORDER BY to_jsonb(t)::text"
                    ),
                    {"owner": owner},
                )
            )
            for table in (*PARENTS, "meal_items")
        }


def assert_runtime_acl(connection, role):
    for table in (*PARENTS, "meal_items"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            actual = connection.scalar(
                text("SELECT has_table_privilege(:role,:table,:privilege)"),
                {"role": role, "table": f"app.{table}", "privilege": privilege},
            )
            assert actual is (privilege != "DELETE" or table == "meal_items"), (table, privilege)


def test_downgrade_emits_operator_warning_and_retains_security(database):
    engine, migrate, _ = database
    output = io.StringIO()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"), stdout=output)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            config.attributes["connection"] = connection
            command.downgrade(config, "0007_e3_diary")
        warning = output.getvalue()
        assert "WARNING:" in warning and "protection is retained on downgrade" in warning
        assert "privileges are not widened" in warning
        with engine.connect() as connection:
            for role in ROLES:
                assert_runtime_acl(connection, role)
            assert connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='diary_delete_account' "
                    "AND tgrelid='app.meal_items'::regclass)"
                )
            )
    finally:
        config.attributes.pop("connection", None)
        migrate("upgrade", "head")


@pytest.mark.parametrize("role", ROLES)
def test_effective_acl_and_real_runtime_insert_select_update(delete_owner, role):
    engine, owner = delete_owner
    with engine.begin() as connection:
        assert_runtime_acl(connection, role)
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with Session(bind=connection) as session:
            ids = seed_parents(session, owner)
            save_weight(session, owner, ids["weights"], example("weight"), base_revision=1)
            save_product_draft(
                session, owner, ids["product_drafts"], example("product-draft"), base_revision=1
            )
            save_diary_day(
                session,
                owner,
                ids["diary_days"],
                example("diary-day") | {"local_date": "2026-10-10"},
                base_revision=1,
            )
            row = save_meal(session, owner, ids["meals"], meal_with_items(3), base_revision=1)
            assert len(meal_payload(session, row)["items"]) == 3
            for table, model in PARENTS.items():
                assert owned(session, model, owner, ids[table]).revision == 2


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("table", PARENTS)
@pytest.mark.parametrize("tombstone", [False, True])
@pytest.mark.parametrize("deleting", [False, True])
def test_parent_delete_denied_and_rollback_preserves_history(
    delete_owner, role, table, tombstone, deleting
):
    engine, owner = delete_owner
    with Session(engine) as session, session.begin():
        ids = seed_parents(session, owner)
        if tombstone:
            delete_entity(session, PARENTS[table], owner, ids[table], base_revision=1)
        if deleting:
            begin_deleting(session, owner)
    before = owner_snapshot(engine, owner)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with pytest.raises(ProgrammingError) as error:
            connection.execute(text(f"DELETE FROM app.{table} WHERE id=:id"), {"id": ids[table]})
        assert error.value.orig.sqlstate == "42501", "Setup failures cannot prove ACL denial"
        transaction.rollback()
    assert owner_snapshot(engine, owner) == before
    if table == "weights" and tombstone:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
            with Session(bind=connection) as session:
                with pytest.raises(DomainError) as error:
                    save_weight(session, owner, ids[table], example("weight"), base_revision=0)
                assert error.value.code == ("account_deleting" if deleting else "version_conflict")
        with Session(engine) as session:
            weight = session.get(Weight, ids[table])
            assert (
                weight.id == ids[table] and weight.revision == 2 and weight.deleted_at is not None
            )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("deleting", [False, True])
def test_item_delete_rejects_deleting_account_or_retained_meal_snapshot(
    delete_owner, role, deleting
):
    engine, owner = delete_owner
    meal, payload = uuid4(), meal_with_items()
    with Session(engine) as session, session.begin():
        save_meal(session, owner, meal, payload)
        if deleting:
            begin_deleting(session, owner)
        else:
            delete_entity(session, Meal, owner, meal, base_revision=1)
    before = owner_snapshot(engine, owner)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with pytest.raises(IntegrityError) as error:
            connection.execute(
                text(
                    "DELETE FROM app.meal_items WHERE owner_id=:owner AND meal_id=:meal "
                    "AND item_id=:item"
                ),
                {"owner": owner, "meal": meal, "item": UUID(payload["items"][0]["item_id"])},
            )
        assert error.value.orig.sqlstate == "23514"
        assert ("active account" if deleting else "snapshot") in str(error.value.orig)
        transaction.rollback()
    assert owner_snapshot(engine, owner) == before


def wait_for_account_lock(engine, pending, pid, holder_pid):
    deadline = monotonic() + 5
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
        while monotonic() < deadline and not pending.done():
            blocked = observer.scalar(
                text(
                    "SELECT wait_event_type='Lock' AND :holder=ANY(pg_blocking_pids(pid)) "
                    "FROM pg_stat_activity WHERE pid=:pid"
                ),
                {"holder": holder_pid, "pid": pid},
            )
            if blocked:
                return
            Event().wait(0.01)
    pytest.fail("Contender did not demonstrably wait on the account transaction in PostgreSQL")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("deleting_first", [False, True])
def test_raw_item_delete_and_begin_deleting_serialize_both_orderings(
    delete_owner, role, deleting_first
):
    engine, owner = delete_owner
    meal, payload = uuid4(), meal_with_items()
    with Session(engine) as session, session.begin():
        save_meal(session, owner, meal, payload)
    before = owner_snapshot(engine, owner)
    ready, contender_pid = Event(), []
    deletion = text(
        "DELETE FROM app.meal_items WHERE owner_id=:owner AND meal_id=:meal AND item_id=:item"
    )
    parameters = {"owner": owner, "meal": meal, "item": UUID(payload["items"][0]["item_id"])}

    def contender():
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                connection.exec_driver_sql("SET LOCAL statement_timeout='10s'")
                contender_pid.append(connection.scalar(text("SELECT pg_backend_pid()")))
                ready.set()
                if deleting_first:
                    return connection.execute(deletion, parameters).rowcount
                with Session(bind=connection) as session:
                    return begin_deleting(session, owner).generation
        except IntegrityError as error:
            assert error.orig.sqlstate == "23514"
            assert "active account" in str(error.orig)
            return "account_deleting"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.begin() as first:
            first.exec_driver_sql(f"SET LOCAL ROLE {role}")
            first.exec_driver_sql("SET LOCAL statement_timeout='10s'")
            holder_pid = first.scalar(text("SELECT pg_backend_pid()"))
            if deleting_first:
                with Session(bind=first) as session:
                    begin_deleting(session, owner)
            else:
                assert first.execute(deletion, parameters).rowcount == 1
            pending = pool.submit(contender)
            assert ready.wait(timeout=5)
            wait_for_account_lock(engine, pending, contender_pid[0], holder_pid)
            assert not pending.done()
            if deleting_first:
                # The DELETE guard must run before diary_item_lock. While the
                # contender waits for our account, it must not own the parent
                # meal lock (otherwise account->meal service writes can deadlock).
                assert (
                    first.scalar(
                        text("SELECT id FROM app.meals WHERE id=:meal FOR UPDATE NOWAIT"),
                        {"meal": meal},
                    )
                    == meal
                )
        assert pending.result(timeout=10) == ("account_deleting" if deleting_first else 2)
    after = owner_snapshot(engine, owner)
    if deleting_first:
        assert after == before
    else:
        assert after["meals"] == before["meals"]
        assert len(after["meal_items"]) == 1
        assert json.loads(after["meal_items"][0])["item_id"] == payload["items"][1]["item_id"]
    with Session(engine) as session:
        account = session.get(UserAccount, owner)
        assert account.state == "deleting" and account.generation == 2


@pytest.mark.parametrize("role", ROLES)
def test_meal_replacement_rollback_after_actual_delete_and_last_item_tombstone(delete_owner, role):
    engine, owner = delete_owner
    meal, initial, replacement = uuid4(), meal_with_items(), meal_with_items(3)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with Session(bind=connection) as session:
            save_meal(session, owner, meal, initial)
    before = owner_snapshot(engine, owner)
    deleted = Event()

    def fail_after_delete(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("DELETE FROM APP.MEAL_ITEMS"):
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.meal_items WHERE meal_id=:meal"), {"meal": meal}
                )
                == 0
            )
            deleted.set()
            raise RuntimeError("injected_after_item_delete")

    event.listen(engine, "after_cursor_execute", fail_after_delete)
    try:
        with pytest.raises(RuntimeError, match="injected_after_item_delete"):
            with engine.begin() as connection:
                connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                with Session(bind=connection) as session:
                    save_meal(session, owner, meal, replacement, base_revision=1)
    finally:
        event.remove(engine, "after_cursor_execute", fail_after_delete)
    assert deleted.is_set(), "Failure must occur after successful DELETE, not during setup"
    assert owner_snapshot(engine, owner) == before
    with engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with Session(bind=connection) as session:
            row = save_meal(session, owner, meal, replacement, base_revision=1)
            assert row.revision == 2 and meal_payload(session, row) == replacement
    with engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with Session(bind=connection) as session:
            for index in range(2):
                remove_meal_item(
                    session,
                    owner,
                    meal,
                    UUID(replacement["items"][index]["item_id"]),
                    base_revision=2 + index,
                )
            row = session.get(Meal, meal)
            retained = meal_payload(session, row)
            remove_meal_item(
                session, owner, meal, UUID(replacement["items"][2]["item_id"]), base_revision=4
            )
            assert row.revision == 5 and row.deleted_at is not None
            assert meal_payload(session, row) == retained
    with Session(engine) as session:
        row = session.get(Meal, meal)
        assert row.revision == 5 and row.deleted_at is not None
        assert meal_payload(session, row) == retained


def database_snapshot(engine):
    with engine.connect() as connection:
        tables = list(
            connection.scalars(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='app' "
                    "AND tablename<>'alembic_version' ORDER BY tablename"
                )
            )
        )
        return {
            table: list(
                connection.exec_driver_sql(
                    f'SELECT to_jsonb(t)::text FROM app."{table}" t ORDER BY to_jsonb(t)::text'
                ).scalars()
            )
            for table in tables
        }


def test_upgrade_0007_preserves_entire_graph_published_bytes_and_secure_downgrade(
    request, tmp_path
):
    engine, migrate, _ = request.getfixturevalue("catalog_db")
    # Remove only fixtures in the already guarded disposable database. Recreate
    # 0007 from 0006 to exercise the original grants, rather than retained 0008 ACL.
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")
    migrate("downgrade", "0006_e3_identity")
    migrate("upgrade", "0007_e3_diary")
    try:
        value = synthetic_official(count=2)
        import_catalog(engine, value)
        manifest = publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
        artifact = export_package(engine, OFFICIAL_PACKAGE_ID, 1)
        path = artifact_path(tmp_path, f"official/{OFFICIAL_PACKAGE_ID}/base-pl.1.json.gz")
        compressed = path.read_bytes()
        assert hashlib.sha256(compressed).hexdigest() == manifest["sha256"]
        principal = Principal("https://upgrade-delete.test", str(uuid4()), frozenset({"user"}))
        with Session(engine) as session, session.begin():
            owner = UUID(bootstrap(session, principal, uuid4())["account_id"])
            put_consents(
                session,
                owner,
                ConsentInput(ranking=True, automatic_energy_adjustment=False),
                1,
                uuid4(),
            )
            save_profile(session, owner, uuid4(), ProfilePayload.model_validate(example("profile")))
            goal = uuid4()
            create_goal(session, owner, goal, GoalPayload.model_validate(example("goal")))
            ids = seed_parents(session, owner)
            historical = meal_with_items()
            historical["goal_id"] = str(goal)
            historical["items"][0]["product"] = {
                "product_id": value["products"][0]["product_id"],
                "revision": 1,
            }
            historical["items"][0]["nutrition_origin"] = "catalog_snapshot"
            save_meal(session, owner, ids["meals"], historical, base_revision=1)
            for table, model in PARENTS.items():
                delete_entity(
                    session, model, owner, ids[table], base_revision=2 if table == "meals" else 1
                )
            begin_deleting(session, owner)
        before = database_snapshot(engine)
        assert len(before["online_receipts"]) == 2
        assert before["installation_state"] and before["offline_packages"]
        migrate("upgrade", "head")
        assert {k: v for k, v in database_snapshot(engine).items() if k in before} == before
        assert export_package(engine, OFFICIAL_PACKAGE_ID, 1) == artifact
        assert path.read_bytes() == compressed
        with engine.connect() as connection:
            for role in ROLES:
                assert_runtime_acl(connection, role)
        migrate("downgrade", "0007_e3_diary")
        assert {k: v for k, v in database_snapshot(engine).items() if k in before} == before
        # Downgrade changes the marker but intentionally retains the security fix.
        with engine.connect() as connection:
            for role in ROLES:
                assert_runtime_acl(connection, role)
                with connection.begin_nested():
                    connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                    with pytest.raises(IntegrityError) as error, connection.begin_nested():
                        connection.execute(
                            text("DELETE FROM app.meal_items WHERE owner_id=:owner"),
                            {"owner": owner},
                        )
                    assert error.value.orig.sqlstate == "23514"
                    assert "active account" in str(error.value.orig)
        assert {k: v for k, v in database_snapshot(engine).items() if k in before} == before
        migrate("upgrade", "head")
        assert {k: v for k, v in database_snapshot(engine).items() if k in before} == before
        assert export_package(engine, OFFICIAL_PACKAGE_ID, 1) == artifact
        assert path.read_bytes() == compressed
    finally:
        migrate("upgrade", "head")
        with engine.begin() as connection:
            connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")
