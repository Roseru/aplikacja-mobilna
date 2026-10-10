"""Deletion protocol/ACL on PostgreSQL; provider-backed proof is a separate test."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.integrations.keycloak.admin import AdminFailure
from calorie_app.modules.diary.models import Weight
from calorie_app.modules.diary.service import (
    delete_entity,
    save_meal,
    save_product_draft,
    save_weight,
)
from calorie_app.modules.identity.deletion import begin, resume, status
from calorie_app.modules.identity.models import OnlineReceipt, UserAccount
from calorie_app.modules.identity.service import bootstrap, require_account
from calorie_app.modules.profiles.models import UserConsent
from calorie_app.modules.profiles.schemas import GoalPayload, ProfilePayload
from calorie_app.modules.profiles.service import create_goal, save_profile

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/examples/valid"


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def seed(engine, principal):
    with Session(engine) as session, session.begin():
        owner = UUID(bootstrap(session, principal, uuid4())["account_id"])
        save_profile(session, owner, uuid4(), ProfilePayload.model_validate(example("profile")))
        goal = uuid4()
        create_goal(session, owner, goal, GoalPayload.model_validate(example("goal")))
        correction = example("goal") | {
            "timeline_base_revision": 1,
            "reason": "history_correction",
            "correction_of": str(goal),
            "energy_kcal": "2700",
        }
        create_goal(session, owner, uuid4(), GoalPayload.model_validate(correction))
        payload = example("meal") | {"goal_id": str(goal)}
        save_meal(session, owner, uuid4(), payload)
        save_weight(session, owner, uuid4(), example("weight"))
        save_product_draft(session, owner, uuid4(), example("product-draft"))
    return owner


def graph(engine, owner):
    with engine.connect() as connection:
        return {
            table: list(
                connection.scalars(
                    text(
                        f"SELECT to_jsonb(t)::text FROM app.{table} t WHERE owner_id=:owner "
                        "ORDER BY to_jsonb(t)::text"
                    ),
                    {"owner": owner},
                )
            )
            for table in (
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
            )
        }


@pytest.fixture
def accounts(database):
    engine, _, _ = database
    a, b = (
        Principal("https://deletion.test/realms/ephemeral", str(uuid4()), frozenset({"user"}))
        for _ in range(2)
    )
    yield engine, a, seed(engine, a), b, seed(engine, b)
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")


def begin_operator(engine, owner, operation, generation=1):
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
        return begin(connection, owner, operation, generation)


def test_begin_idempotent_generation_context_and_subject_fence(accounts):
    engine, a, owner, _, b = accounts
    operation, before_b = uuid4(), graph(engine, b)
    first = begin_operator(engine, owner, operation)
    assert first["deleting_generation"] == 2 and first["identity_confirmed_at"] is None
    assert begin_operator(engine, owner, operation) == first
    for other_owner, other_op, generation in (
        (owner, operation, 2),
        (b, operation, 1),
        (owner, uuid4(), 1),
    ):
        with pytest.raises(DBAPIError):
            begin_operator(engine, other_owner, other_op, generation)
    for function in (lambda s: bootstrap(s, a, uuid4()), lambda s: require_account(s, a)):
        with Session(engine) as session, session.begin():
            with pytest.raises(DomainError) as error:
                function(session)
            assert error.value.code == "account_deleting"
    assert graph(engine, b) == before_b


def test_provider_failure_preserves_all_private_data_and_unconfirmed_purge_denied(accounts):
    engine, _, owner, _, _ = accounts
    operation, before = uuid4(), graph(engine, owner)
    begin_operator(engine, owner, operation)

    class Failed:
        def delete_and_confirm(self, issuer, subject):
            raise AdminFailure()

    with pytest.raises(AdminFailure):
        resume(engine, operation, Failed())
    assert graph(engine, owner) == before
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text("SELECT app.purge_deleted_account(:operation)"), {"operation": operation}
            )
        assert status(connection, operation)["identity_confirmed_at"] is None


@pytest.mark.parametrize(
    "crash_at", ["provider_confirmed", "confirmation_committed", "purge_committed"]
)
def test_resume_after_each_committed_or_external_stage_is_durable(accounts, crash_at):
    engine, a, owner, _, b = accounts
    operation, before_b, before_a = uuid4(), graph(engine, b), graph(engine, owner)
    begin_operator(engine, owner, operation)
    targets = []

    class Provider:
        def delete_and_confirm(self, issuer, subject):
            targets.append((issuer, subject))

    def crash(stage):
        if stage == crash_at:
            raise RuntimeError("injected crash")

    with pytest.raises(RuntimeError, match="injected crash"):
        resume(engine, operation, Provider(), barrier=crash)
    if crash_at != "purge_committed":
        assert graph(engine, owner) == before_a
    job = resume(engine, operation, Provider())
    assert job["purged_at"] is not None
    assert job["block_until"] - job["identity_confirmed_at"] >= timedelta(seconds=420)
    assert targets == [(a.issuer, a.subject)] * (2 if crash_at == "provider_confirmed" else 1)
    assert all(not rows for rows in graph(engine, owner).values())
    assert graph(engine, b) == before_b
    assert begin_operator(engine, owner, operation) == job
    assert resume(engine, operation, Provider()) == job
    with Session(engine) as session, session.begin():
        with pytest.raises(DomainError) as error:
            bootstrap(session, a, uuid4())
        assert error.value.code == "account_deleting"
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:issuer,:subject)"
                ),
                {"id": uuid4(), "issuer": a.issuer, "subject": a.subject},
            )
    # A new registration is a distinct Keycloak subject and account UUID.
    replacement = Principal(a.issuer, str(uuid4()), a.roles)
    with Session(engine) as session, session.begin():
        new_owner = UUID(bootstrap(session, replacement, uuid4())["account_id"])
    assert new_owner != owner


@pytest.mark.parametrize(
    "role", ["calorie_app_api", "calorie_app_worker", "calorie_app_deletion_operator"]
)
def test_effective_acl_and_raw_runtime_denials(accounts, role):
    engine, _, owner, _, _ = accounts
    with engine.begin() as connection:
        assert not connection.scalar(
            text("SELECT pg_has_role(:r,'calorie_app_migrator','MEMBER')"), {"r": role}
        )
        assert not connection.scalar(
            text("SELECT has_schema_privilege(:r,'app','CREATE')"), {"r": role}
        )
        for table in ("goal_versions", "user_accounts", "weights", "meals", "_deletion_context"):
            assert not connection.scalar(
                text("SELECT has_table_privilege(:r,:t,'DELETE')"), {"r": role, "t": "app." + table}
            )
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        for sql in (
            "DELETE FROM app.weights WHERE owner_id=:owner",
            "INSERT INTO app._deletion_context VALUES(txid_current(),:owner,:owner)",
            "TRUNCATE app.user_accounts CASCADE",
        ):
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text(sql), {"owner": owner})
        if role != "calorie_app_deletion_operator":
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(
                    text("SELECT app.begin_account_deletion(:owner,:op,1)"),
                    {"owner": owner, "op": uuid4()},
                )


def test_privileged_raw_delete_still_cannot_bypass_goal_guard(accounts):
    engine, _, owner, _, _ = accounts
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        with pytest.raises(DBAPIError) as error, connection.begin_nested():
            connection.execute(
                text("DELETE FROM app.goal_versions WHERE owner_id=:owner"), {"owner": owner}
            )
        assert error.value.orig.sqlstate == "23514"
        assert "goal versions are immutable" in str(error.value.orig)


def test_crash_after_actual_purge_sql_rolls_back_entire_graph_and_job(accounts):
    engine, _, owner, _, _ = accounts
    operation, before = uuid4(), graph(engine, owner)
    begin_operator(engine, owner, operation)

    class Provider:
        def delete_and_confirm(self, issuer, subject):
            pass

    executed = []

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT app.purge_deleted_account"):
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.user_accounts WHERE id=:owner"), {"owner": owner}
                )
                == 0
            )
            executed.append(True)
            raise RuntimeError("crash after purge SQL")

    event.listen(engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="crash after purge SQL"):
            resume(engine, operation, Provider())
    finally:
        event.remove(engine, "after_cursor_execute", fail)
    assert executed == [True]
    assert graph(engine, owner) == before
    with engine.begin() as connection:
        job = status(connection, operation)
        assert job["identity_confirmed_at"] is not None and job["purged_at"] is None
        assert connection.scalar(text("SELECT count(*) FROM app._deletion_context")) == 0
    assert resume(engine, operation, Provider())["purged_at"] is not None


def test_purge_includes_every_sync_table_and_preserves_other_owner(accounts):
    from calorie_app.modules.sync.models import (
        RecoveryMapping,
        SyncChange,
        SyncCounter,
        SyncReceipt,
        SyncReservation,
    )
    from calorie_app.modules.sync.snapshot_models import SyncSession, SyncSessionItem

    engine, _, owner, _, b = accounts
    models = (
        SyncCounter,
        SyncReceipt,
        SyncChange,
        SyncReservation,
        RecoveryMapping,
        SyncSession,
        SyncSessionItem,
    )
    for target in (owner, b):
        with Session(engine) as session, session.begin():
            epoch = session.scalar(text("SELECT sync_epoch FROM app.installation_state"))
            session.add(SyncCounter(owner_id=target, position=1))
            session.add(
                SyncReceipt(
                    owner_id=target,
                    operation_id=uuid4(),
                    request_hash="b" * 64,
                    source_epoch=epoch,
                    entity_type="weight",
                    entity_id=uuid4(),
                    status="accepted",
                    code=None,
                    revision=1,
                    recovery_epoch=None,
                    recovery_entity_id=None,
                    response={"synthetic": "accepted"},
                )
            )
            session.add(SyncChange(owner_id=target, position=1, entity={"synthetic": "private"}))
            session.add(
                SyncReservation(
                    owner_id=target,
                    entity_type="weight",
                    entity_id=uuid4(),
                    deleted_at=datetime.now(UTC),
                )
            )
            session.add(
                RecoveryMapping(
                    owner_id=target,
                    source_epoch=uuid4(),
                    source_entity_id=uuid4(),
                    entity_type="weight",
                    target_entity_id=uuid4(),
                    target_revision=1,
                )
            )
            now, sid = datetime.now(UTC), uuid4()
            session.add(
                SyncSession(
                    id=sid,
                    owner_id=target,
                    generation=1,
                    epoch=epoch,
                    mode="snapshot",
                    page_limit=1,
                    high_position=1,
                    base_position=0,
                    base_issued_at=None,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                    timeline_revision=1,
                    item_count=1,
                    byte_count=2,
                    final_offset=None,
                    final_response=None,
                )
            )
            session.flush()
            session.add(
                SyncSessionItem(
                    session_id=sid,
                    position=1,
                    owner_id=target,
                    kind="entities",
                    value={"synthetic": "private"},
                    byte_size=2,
                )
            )

    def rows(target):
        with engine.connect() as connection:
            return {
                model.__tablename__: list(
                    connection.scalars(
                        text(
                            f"SELECT to_jsonb(t)::text FROM app.{model.__tablename__} t "
                            "WHERE owner_id=:owner "
                            "ORDER BY to_jsonb(t)::text"
                        ),
                        {"owner": target},
                    )
                )
                for model in models
            }

    before_b = rows(b)
    assert all(before_b.values()) and all(rows(owner).values())
    operation = uuid4()
    begin_operator(engine, owner, operation)

    class Provider:
        def delete_and_confirm(self, issuer, subject):
            pass

    assert resume(engine, operation, Provider())["purged_at"] is not None
    assert all(not value for value in rows(owner).values())
    assert rows(b) == before_b


def test_deletion_functions_fixed_search_path_and_no_runtime_role_membership(database):
    engine, _, _ = database
    with engine.connect() as connection:
        records = connection.execute(
            text(
                "SELECT p.proname,p.prosecdef,p.proconfig FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND p.proname IN "
                "('begin_account_deletion','confirm_account_deletion',"
                "'purge_deleted_account','deletion_purge_authorized')"
            )
        )
        assert all(
            r.prosecdef and r.proconfig == ["search_path=pg_catalog, pg_temp"] for r in records
        )
        for role in ("calorie_app_api", "calorie_app_worker"):
            assert not connection.scalar(
                text("SELECT pg_has_role(:r,'calorie_app_deletion_operator','MEMBER')"), {"r": role}
            )


def test_deletion_metadata_matches_migrated_schema(database):
    from calorie_app.modules.identity.deletion_models import (
        AccountDeletionJob,
        DeletedSubject,
        DeletionContext,
    )

    engine, migrate, _ = database
    migrate("check")
    reflected = inspect(engine)
    for model in (AccountDeletionJob, DeletedSubject, DeletionContext):
        table = model.__tablename__
        constraints = [reflected.get_pk_constraint(table, schema="app")]
        constraints += reflected.get_foreign_keys(table, schema="app")
        constraints += reflected.get_unique_constraints(table, schema="app")
        constraints += reflected.get_check_constraints(table, schema="app")
        assert {c["name"] for c in constraints} == {c.name for c in model.__table__.constraints}
        assert reflected.get_indexes(table, schema="app") == [] or all(
            item.get("duplicates_constraint") for item in reflected.get_indexes(table, schema="app")
        )
    created = next(
        c
        for c in reflected.get_columns("account_deletion_jobs", schema="app")
        if c["name"] == "created_at"
    )
    assert created["default"] == "clock_timestamp()"


def test_original_0008_upgrade_preserves_private_graph_epoch_and_catalog_bytes(database, tmp_path):
    from calorie_app.modules.catalog.export import export_package, publish_package
    from calorie_app.modules.catalog.service import import_catalog

    engine, migrate, _ = database
    # Dedicated *_test fixture, run serially: rebuild the genuine old schema,
    # rather than a downgraded marker retaining the new E4 implementation.
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA app CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator")
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        # DROP SCHEMA also removes namespace-scoped default ACLs. Reproduce
        # the fixture/production bootstrap so later E1 role tests see the same
        # provisioning instead of inheriting this test's incomplete grants.
        connection.exec_driver_sql(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA app "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
            "TO calorie_app_api, calorie_app_worker"
        )
    migrate("upgrade", "0008_diary_delete")
    owner = uuid4()
    try:
        demo = json.loads((EXAMPLES.parents[2] / "backend/data/demo/seed.json").read_text())
        import_catalog(engine, demo)
        catalog = export_package(engine, UUID(demo["package_id"]), 1)
        publish_package(engine, UUID(demo["package_id"]), 1, tmp_path)
        artifact = next(tmp_path.rglob("*.json.gz"))
        published = artifact.read_bytes()
        with Session(engine) as session, session.begin():
            session.add(UserAccount(id=owner, issuer="https://upgrade.test", subject=str(owner)))
            session.flush()
            session.add(UserConsent(owner_id=owner))
            old_epoch = session.scalar(text("SELECT sync_epoch FROM app.installation_state"))
            for operation in ("bootstrap", "consents"):
                session.add(
                    OnlineReceipt(
                        owner_id=owner,
                        operation=operation,
                        key=uuid4(),
                        request_hash="a" * 64,
                        generation=1,
                        sync_epoch=old_epoch,
                        response={"old": "synthetic evidence"},
                        accepted_revision=1 if operation == "consents" else None,
                    )
                )
            save_profile(session, owner, uuid4(), ProfilePayload.model_validate(example("profile")))
            goal = uuid4()
            create_goal(session, owner, goal, GoalPayload.model_validate(example("goal")))
            save_meal(session, owner, uuid4(), example("meal") | {"goal_id": str(goal)})
            weight = uuid4()
            save_weight(session, owner, weight, example("weight"))
            delete_entity(session, Weight, owner, weight, base_revision=1)
            save_product_draft(session, owner, uuid4(), example("product-draft"))
        before = graph(engine, owner)
        with engine.connect() as connection:
            epoch = connection.scalar(text("SELECT sync_epoch FROM app.installation_state"))
        migrate("upgrade", "head")
        assert graph(engine, owner) == before
        assert export_package(engine, UUID(demo["package_id"]), 1) == catalog
        assert artifact.read_bytes() == published
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT sync_epoch FROM app.installation_state")) == epoch
        migrate("downgrade", "0008_diary_delete")
        assert graph(engine, owner) == before
        with engine.begin() as connection:
            for role in ("calorie_app_api", "calorie_app_worker"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege(:role,'app.weights','DELETE')"), {"role": role}
                )
        migrate("upgrade", "head")
        assert graph(engine, owner) == before
    finally:
        migrate("upgrade", "head")
        with engine.begin() as connection:
            connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")
            connection.exec_driver_sql(
                "TRUNCATE app.product_sources,app.products,app.rations,app.offline_channels CASCADE"
            )
