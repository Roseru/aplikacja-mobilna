"""PG17 acceptance of enforced deletion barriers and authenticated durable coverage."""

import copy
import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.identity import deletion
from calorie_app.modules.identity.ledger_contract import (
    LedgerInvalid,
    make_cutoff,
    validate_restore,
)
from calorie_app.modules.identity.ledger_transport import export_once
from calorie_app.modules.identity.service import begin_deleting
from tests.support.deletion_regression import harness
from tests.support.ledger_sink import ContractSink

pytestmark = pytest.mark.integration


@pytest.fixture
def ledger(database):
    engine, migrate, _ = database
    return engine, harness(engine), migrate


def account(engine):
    owner, subject = uuid4(), str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:issuer,:subject)"),
            {"id": owner, "issuer": "https://ledger.test/realms/owned", "subject": subject},
        )
    return owner


def begin(engine, owner):
    operation = uuid4()
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
        deletion.begin(connection, owner, operation, 1)
    return operation


def value(engine, sql, **params):
    with engine.connect() as connection:
        return connection.scalar(text(sql), params)


class Provider:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def delete_and_confirm(self, issuer, subject):
        self.calls.append((issuer, subject))
        if self.fail:
            raise TimeoutError("synthetic provider lost response")


@pytest.mark.parametrize(
    "point",
    [
        "provider_intent_committed",
        "provider_confirmed",
        "provider_result_committed",
        "confirmation_committed",
        "purge_intent_committed",
        "purge_committed",
    ],
)
def test_crash_restart_every_stage_retains_target_and_requires_external_ack(ledger, point):
    engine, h, _ = ledger
    owner, other = account(engine), account(engine)
    operation = begin(engine, owner)
    provider = Provider()

    def crash(stage):
        if stage == point:
            raise RuntimeError("synthetic crash")

    with pytest.raises(RuntimeError, match="synthetic crash"):
        deletion.resume(engine, operation, provider, delivery=h.deliver, barrier=crash)
    result = deletion.resume(engine, operation, provider, delivery=h.deliver)
    assert result["ledger_complete"] is True and result["deleting_generation"] == 2
    assert value(engine, "SELECT count(*) FROM app.user_accounts WHERE id=:id", id=owner) == 0
    assert value(engine, "SELECT count(*) FROM app.user_accounts WHERE id=:id", id=other) == 1
    assert len(set(provider.calls)) == 1
    assert value(engine, "SELECT count(*) FROM app._ledger_account_context") == 0


def test_no_ack_never_calls_provider_and_failure_is_not_completion(ledger):
    engine, h, _ = ledger
    operation = begin(engine, account(engine))
    provider = Provider(fail=True)
    with pytest.raises(DBAPIError, match="ACK required"):
        deletion.resume(engine, operation, provider)
    assert provider.calls == []
    with pytest.raises(TimeoutError):
        deletion.resume(engine, operation, provider, delivery=h.deliver)
    with engine.begin() as connection:
        state = deletion.status(connection, operation)
        assert state["provider_result"] == "uncertain"
        assert state["purged_at"] is None and state["identity_confirmed_at"] is None
        with pytest.raises(DBAPIError, match="uncertain"), connection.begin_nested():
            connection.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]


def test_final_local_purge_is_not_external_completion(ledger):
    engine, h, _ = ledger
    operation = begin(engine, account(engine))
    stop = False

    def boundary(stage):
        nonlocal stop
        if stage == "purge_committed":
            stop = True

    def delivery():
        if not stop:
            h.deliver()

    with pytest.raises(ValueError, match="external ACK pending"):
        deletion.resume(engine, operation, Provider(), delivery=delivery, barrier=boundary)
    with engine.begin() as connection:
        state = deletion.status(connection, operation)
        assert state["purged_at"] is not None and not state["ledger_complete"]
    h.deliver()
    assert deletion.resume(engine, operation, Provider())["ledger_complete"]


def test_delivery_lost_ack_restart_and_competing_exporters_are_idempotent(ledger, tmp_path):
    engine, h, _ = ledger
    operation = begin(engine, account(engine))

    class Lost:
        def deliver(self, envelope):
            h.sink.deliver(envelope)
            raise TimeoutError("lost ACK")

    before = value(engine, "SELECT ack_sequence FROM app.deletion_ledger_source")
    with pytest.raises(TimeoutError):
        export_once(h.exporter, Lost())
    assert value(engine, "SELECT ack_sequence FROM app.deletion_ledger_source") == before
    h.sink.close()
    h.sink = ContractSink(h.sink.path, h.trust)
    h.deliver()
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]
    # A second receiver must start from1 and cannot combine a foreign pin/prefix.
    other = ContractSink(tmp_path / "second.sqlite", h.trust)
    try:
        with engine.connect() as c:
            batch = c.scalar(text("SELECT app.ledger_batch(2,128)"))
        with pytest.raises(LedgerInvalid, match="gap"):
            other.deliver(batch)
    finally:
        other.close()


def test_transaction_rollback_and_waiting_commit_cannot_create_prefix_gap(ledger):
    engine, h, _ = ledger
    owner1, owner2 = account(engine), account(engine)
    prior = value(engine, "SELECT next_sequence FROM app.deletion_ledger_source")
    first = engine.connect()
    txn = first.begin()
    deletion.begin(first, owner1, uuid4(), 1)
    ready = Event()

    def second():
        ready.set()
        return begin(engine, owner2)

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(second)
        assert ready.wait(5)
        assert not future.done()
        txn.rollback()
        first.close()
        operation = future.result(10)
    assert value(engine, "SELECT next_sequence FROM app.deletion_ledger_source") == prior + 1
    assert (
        value(
            engine, "SELECT count(*) FROM app.account_deletion_jobs WHERE account_id=:id", id=owner1
        )
        == 0
    )
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]


def test_old_lease_cannot_confirm_new_provider_attempt(ledger):
    engine, h, _ = ledger
    operation = begin(engine, account(engine))
    h.deliver()
    with engine.begin() as c:
        old = c.scalar(text("SELECT app.ledger_prepare_provider(:op)"), {"op": operation})
    h.deliver()
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE app.deletion_ledger_operations SET "
                "provider_until=clock_timestamp()-interval '1 second' WHERE "
                "operation_id=:op"
            ),
            {"op": operation},
        )
        new = c.scalar(text("SELECT app.ledger_prepare_provider(:op)"), {"op": operation})
    assert old != new
    h.deliver()
    with engine.begin() as c:
        with pytest.raises(DBAPIError, match="stale"), c.begin_nested():
            c.execute(
                text("SELECT app.ledger_provider_result(:op,:token,'confirmed')"),
                {"op": operation, "token": old},
            )
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]


@pytest.mark.parametrize(
    "role",
    [
        "calorie_app_api",
        "calorie_app_worker",
        "calorie_app_deletion_operator",
        "calorie_app_deletion_exporter",
    ],
)
def test_raw_dml_internal_parents_fake_ack_and_lifecycle_are_denied(ledger, role):
    engine, _, _ = ledger
    owner = account(engine)
    with engine.begin() as c:
        c.exec_driver_sql(f"SET LOCAL ROLE {role}")
        for statement in (
            "UPDATE app.user_accounts SET state='deleting',generation=2 WHERE id=:id",
            "UPDATE app.user_accounts SET generation=2 WHERE id=:id",
            "INSERT INTO app.user_accounts(id,issuer,subject,state,generation) "
            "VALUES(gen_random_uuid(),'bad','bad','deleting',2)",
            "UPDATE app.deletion_ledger_source SET ack_sequence=next_sequence-1",
            "UPDATE app.deletion_ledger_events SET content='tampered'",
            "DELETE FROM app.deletion_ledger_events",
            "TRUNCATE app.deletion_ledger_receipts",
            "INSERT INTO app._ledger_account_context VALUES(txid_current(),:id,:id)",
            "SELECT app.begin_account_deletion_pre25(:id,:id,1)",
            "SELECT app.confirm_account_deletion_pre25(:id)",
            "SELECT app.purge_deleted_account_pre25(:id)",
            "SELECT app.purge_deleted_account_e8_19(:id)",
            "SELECT app._ledger_append(:id,'purge','confirmed')",
        ):
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(text(statement), {"id": owner})
        if role != "calorie_app_deletion_exporter":
            for statement in (
                "SELECT app.ledger_batch(1,1)",
                "SELECT app.ledger_ack(gen_random_uuid(),gen_random_uuid(),"
                "gen_random_uuid(),gen_random_uuid(),1,repeat('0',64),repeat('0',64))",
            ):
                with pytest.raises(DBAPIError), c.begin_nested():
                    c.execute(text(statement))
    with Session(engine) as session, session.begin():
        with pytest.raises(DomainError) as error:
            begin_deleting(session, owner)
        assert error.value.code == "deletion_operator_required"


def test_real_operator_login_blocks_legacy_resume_before_provider(ledger):
    from tests.integration.test_e4_operator_login import provision
    from tests.support.legacy_deletion import resume as legacy_resume

    engine, h, _ = ledger
    login, password = "ledger_operator_" + uuid4().hex[:12], secrets.token_urlsafe(32)
    url = engine.url
    provision(url, login, password)
    operator = create_engine(url.set(username=login, password=password), hide_parameters=True)
    try:
        operation = begin(engine, account(engine))
        p = Provider()
        with pytest.raises(DBAPIError):
            legacy_resume(operator, operation, p)
        assert p.calls == []
        assert value(operator, "SELECT current_user") == login
        assert deletion.resume(operator, operation, p, delivery=h.deliver)["ledger_complete"]
    finally:
        operator.dispose()
        with engine.begin() as c:
            c.exec_driver_sql(f'DROP OWNED BY "{login}"')
            c.exec_driver_sql(f'DROP ROLE "{login}"')


def test_source_mac_prefix_cutoff_tamper_and_epoch_fence(ledger):
    engine, h, _ = ledger
    h.deliver()
    batches = all_batches(engine)
    envelope = batches[0]
    ack = h.sink.deliver(batches[-1])
    from tests.support.ledger import contract_fence_pin

    pin = contract_fence_pin(h.trust)
    cutoff = make_cutoff(h.trust, ack, pin)
    # Exact cutoff supplied by the test observer; this is no production fencing proof.
    baseline = validate_restore(h.trust, batches, backup_point=ack, cutoff=cutoff, fence_pin=pin)
    assert baseline["reopen_authorized"] is False
    bad = copy.deepcopy(envelope)
    bad["body"] += " "
    with pytest.raises(LedgerInvalid, match="source"):
        validate_restore(h.trust, [bad], backup_point=ack, cutoff=cutoff, fence_pin=pin)
    bad_ack = ack | {"sequence": ack["sequence"] - 1}
    with pytest.raises(LedgerInvalid, match="ack"):
        validate_restore(h.trust, [envelope], backup_point=bad_ack, cutoff=cutoff, fence_pin=pin)
    with engine.begin() as c:
        epoch = c.scalar(text("SELECT sync_epoch FROM app.installation_state"))
        c.execute(text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": uuid4()})
    try:
        with pytest.raises(DBAPIError, match="restore fenced"):
            begin(engine, account(engine))
        with pytest.raises(DBAPIError, match="restore fenced"):
            h.deliver()
    finally:
        with engine.begin() as c:
            c.execute(text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": epoch})


def test_safe_downgrade_retains_evidence_and_reupgrade_keeps_barriers(ledger):
    engine, h, migrate = ledger
    operation = begin(engine, account(engine))
    h.deliver()
    before = value(engine, "SELECT count(*) FROM app.deletion_ledger_events")
    migrate("downgrade", "0024_e9_history_graph")
    assert value(engine, "SELECT count(*) FROM app.deletion_ledger_events") == before
    with pytest.raises(DBAPIError):
        with engine.begin() as c:
            c.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
            c.exec_driver_sql("SELECT * FROM app.account_deletion_jobs")
    migrate("upgrade", "head")
    assert value(engine, "SELECT count(*) FROM app.deletion_ledger_events") == before
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]


def all_batches(engine):
    result, start = [], 1
    while True:
        envelope = value(engine, "SELECT app.ledger_batch(:start,128)", start=start)
        events = json.loads(envelope["body"])["events"]
        if not events:
            return result
        result.append(envelope)
        start = events[-1]["sequence"] + 1


def test_real_exporter_login_only_delivers_authenticated_exact_prefix(ledger):
    import subprocess
    import sys

    engine, h, _ = ledger
    parsed = engine.url
    login, password = "ledger_exporter_" + uuid4().hex[:12], secrets.token_urlsafe(32)
    environment = os.environ | {
        "PGHOST": parsed.host,
        "PGPORT": str(parsed.port),
        "PGUSER": parsed.username,
        "PGDATABASE": parsed.database,
        "PGPASSWORD": parsed.password,
        "DELETION_EXPORTER_LOGIN": login,
        "DELETION_EXPORTER_PASSWORD": password,
    }
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "infra/local/provision_deletion_exporter.py")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert password not in result.stdout + result.stderr
    assert result.returncode == 0, "exporter provisioning failed (diagnostics withheld)"
    exporter = create_engine(parsed.set(username=login, password=password), hide_parameters=True)
    try:
        assert value(exporter, "SELECT current_user") == login
        operation = begin(engine, account(engine))
        export_once(exporter, h.sink)
        with exporter.begin() as c:
            with pytest.raises(DBAPIError, match="unauthenticated"), c.begin_nested():
                c.execute(
                    text("SELECT app.ledger_ack(:i,:s,:a,:r,1,repeat('0',64),repeat('0',64))"),
                    {
                        "i": UUID(h.trust.installation_id),
                        "s": UUID(h.trust.stream_id),
                        "a": UUID(h.trust.anchor_id),
                        "r": UUID(h.trust.receiver_id),
                    },
                )
            with pytest.raises(DBAPIError), c.begin_nested():
                c.exec_driver_sql("SELECT * FROM app.deletion_ledger_source")
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
        assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]
    finally:
        exporter.dispose()
        with engine.begin() as c:
            c.exec_driver_sql(f'DROP OWNED BY "{login}"')
            c.exec_driver_sql(f'DROP ROLE "{login}"')


def test_populated_previous_schema_preserves_jobs_and_legacy_unknown(historical_database, tmp_path):
    from calorie_app.integrations.keycloak import Principal
    from tests.integration.test_e4_deletion import graph, seed
    from tests.support.ledger import LedgerHarness

    engine, _, _ = historical_database
    principal = Principal("https://ledger.test/realms/owned", str(uuid4()), frozenset({"user"}))
    owner = seed(engine, principal)
    other = seed(engine, Principal(principal.issuer, str(uuid4()), principal.roles))
    before_a, before_b = graph(engine, owner), graph(engine, other)
    legacy_op = uuid4()
    with engine.begin() as c:
        c.execute(
            text("SELECT app.begin_account_deletion(:owner,:op,1)"),
            {"owner": owner, "op": legacy_op},
        )
    from alembic import command
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with engine.begin() as c:
        c.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        config.attributes["connection"] = c
        command.upgrade(config, "0025_deletion_ledger")
    assert graph(engine, owner) == before_a and graph(engine, other) == before_b
    h = LedgerHarness(engine, tmp_path)
    try:
        with engine.begin() as c:
            state = deletion.status(c, legacy_op)
            assert state["legacy_unknown"] and not state["ledger_complete"]
        assert (
            value(
                engine,
                (
                    "SELECT count(*) FROM app.deletion_ledger_events WHERE "
                    "stage='legacy' AND outcome='unknown'"
                ),
            )
            == 1
        )
        with pytest.raises(ValueError, match="Legacy"):
            deletion.resume(engine, legacy_op, Provider(), delivery=h.deliver)
        # A new operation still uses the complete current preserved graph.
        operation = begin(engine, other)
        assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]
        assert not any(graph(engine, other).values())
        assert graph(engine, owner) == before_a
    finally:
        h.close()


def test_real_pg_backup_before_deletion_restore_reconciles_from_restarted_sink(ledger, tmp_path):
    import subprocess

    from calorie_app.modules.identity.ledger_restore import reconcile_restore
    from tests.support.e8_3_archive import archive_environment, pg_command

    engine, h, _ = ledger
    owner, other = account(engine), account(engine)
    h.deliver()
    batches = all_batches(engine)
    backup_point = h.sink.deliver(batches[-1])
    environment = archive_environment(engine.url)
    dump_command = pg_command("pg_dump", ["--format=custom", "--no-owner"], environment)
    dump = subprocess.run(dump_command, env=environment, capture_output=True, timeout=60)
    assert dump.returncode == 0, "owned PG17 backup failed"
    operation = begin(engine, owner)
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]
    expected_batches = all_batches(engine)
    from tests.support.ledger import contract_fence_pin

    pin = contract_fence_pin(h.trust)
    cutoff_ack = h.sink.deliver(expected_batches[-1])
    cutoff = make_cutoff(h.trust, cutoff_ack, pin)
    # Persisted receiver data, independent of source and its restored snapshot.
    path = h.sink.path
    h.sink.close()
    h.sink = ContractSink(path, h.trust)
    name = "ledger_restore_" + uuid4().hex[:12] + "_test"
    admin = create_engine(
        engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    restored = None
    try:
        with admin.connect() as c:
            c.exec_driver_sql(f'CREATE DATABASE "{name}" OWNER calorie_app_migrator')
            c.exec_driver_sql(f'REVOKE ALL ON DATABASE "{name}" FROM PUBLIC')
        restore_env = environment | {"PGDATABASE": name}
        restored_dump = subprocess.run(
            pg_command(
                "pg_restore",
                ["--exit-on-error", "--dbname", name, "--no-owner"],
                restore_env,
                interactive=True,
            ),
            input=dump.stdout,
            env=restore_env,
            capture_output=True,
            timeout=60,
        )
        assert restored_dump.returncode == 0, "owned PG17 restore failed"
        restored = create_engine(engine.url.set(database=name), hide_parameters=True)
        assert (
            value(restored, "SELECT state FROM app.user_accounts WHERE id=:id", id=owner)
            == "active"
        )
        with restored.begin() as c:
            c.execute(
                text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": uuid4()}
            )
        with pytest.raises(DBAPIError, match="restore fenced"):
            begin(restored, account(restored))
        result = reconcile_restore(
            restored,
            h.trust,
            expected_batches,
            backup_point=backup_point,
            cutoff=cutoff,
            fence_pin=pin,
        )
        assert result["reopen_authorized"] is False and result["source_frozen"] is True
        assert (
            value(restored, "SELECT state FROM app.user_accounts WHERE id=:id", id=owner)
            == "deleting"
        )
        assert (
            value(restored, "SELECT generation FROM app.user_accounts WHERE id=:id", id=owner) == 2
        )
        assert (
            value(restored, "SELECT state FROM app.user_accounts WHERE id=:id", id=other)
            == "active"
        )
        assert value(restored, "SELECT count(*) FROM app.deletion_ledger_restore_receipts") == 1
        assert (
            value(
                restored,
                "SELECT count(*) FROM app.deleted_subjects WHERE operation_id=:op",
                op=operation,
            )
            == 1
        )
        assert value(restored, "SELECT enabled FROM app.deletion_ledger_source") is False
        # A wrong backup binding is rejected before any source/account update.
        with pytest.raises(LedgerInvalid, match="snapshot_prefix"):
            reconcile_restore(
                restored,
                h.trust,
                expected_batches,
                backup_point=cutoff_ack,
                cutoff=cutoff,
                fence_pin=pin,
            )
    finally:
        if restored:
            restored.dispose()
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH(FORCE)')
        admin.dispose()


def test_append_waiting_for_source_rechecks_a_concurrent_freeze(ledger):
    import time

    engine, _, _ = ledger
    owner = account(engine)
    freezer = engine.connect()
    tx = freezer.begin()
    freezer_pid = freezer.scalar(text("SELECT pg_backend_pid()"))
    freezer.exec_driver_sql("SELECT 1 FROM app.deletion_ledger_source WHERE id=1 FOR UPDATE")
    started, producer_pid = Event(), []

    def append():
        with engine.begin() as connection:
            producer_pid.append(connection.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            return deletion.begin(connection, owner, uuid4(), 1)

    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(append)
            assert started.wait(5)
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline and not future.done():
                blockers = value(engine, "SELECT pg_blocking_pids(:pid)", pid=producer_pid[0])
                if freezer_pid in blockers:
                    waiting = True
                    break
                time.sleep(0.01)
            assert waiting, "producer must pass initial readiness and wait on the source lock"
            freezer.exec_driver_sql(
                "UPDATE app.deletion_ledger_source SET enabled=false WHERE id=1"
            )
            tx.commit()
            with pytest.raises(DBAPIError, match="fenced"):
                future.result(10)
        assert (
            value(engine, "SELECT state FROM app.user_accounts WHERE id=:id", id=owner) == "active"
        )
        assert (
            value(
                engine,
                "SELECT count(*) FROM app.account_deletion_jobs WHERE account_id=:id",
                id=owner,
            )
            == 0
        )
    finally:
        if tx.is_active:
            tx.rollback()
        freezer.close()
        with engine.begin() as c:
            c.exec_driver_sql("UPDATE app.deletion_ledger_source SET enabled=true WHERE id=1")


def test_current_head_preserves_nemesis_activation_gate_and_rejects_bad_acl(ledger):
    engine, _, _ = ledger
    with engine.begin() as c:
        c.exec_driver_sql(
            "DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE "
            "rolname='calorie_app_nemesis_finalizer') THEN CREATE ROLE "
            "calorie_app_nemesis_finalizer NOLOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT; END IF; END $$"
        )
        c.exec_driver_sql(
            "GRANT EXECUTE ON FUNCTION app.e8n_finalize_batch(integer) TO "
            "calorie_app_nemesis_finalizer"
        )
        c.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is True
        epoch = c.scalar(text("SELECT sync_epoch FROM app.installation_state"))
        c.execute(text("SELECT app.e8n_activate(:epoch)"), {"epoch": epoch})
        assert c.scalar(text("SELECT app.e8n_gate()")) is True
        c.exec_driver_sql(
            "GRANT EXECUTE ON FUNCTION app.e8n_finalize_batch(integer) TO calorie_app_api"
        )
        assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is False
        with pytest.raises(DBAPIError), c.begin_nested():
            c.execute(text("SELECT app.e8n_activate(:epoch)"), {"epoch": epoch})
        c.exec_driver_sql(
            "REVOKE EXECUTE ON FUNCTION app.e8n_finalize_batch(integer) FROM calorie_app_api"
        )
        assert c.scalar(text("SELECT app.e8n_gate()")) is True
        c.exec_driver_sql("UPDATE app.nemesis_control SET enabled=false")


def test_two_real_concurrent_exporters_keep_one_durable_receiver_prefix(ledger):
    from threading import Barrier

    engine, h, _ = ledger
    operation = begin(engine, account(engine))
    ready = Barrier(2)

    class Concurrent:
        def deliver(self, envelope):
            sink = ContractSink(h.sink.path, h.trust)
            try:
                ready.wait(10)
                return sink.deliver(envelope)
            finally:
                sink.close()

    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(export_once, h.exporter, Concurrent(), max_batches=1) for _ in range(2)
        ]
        assert [future.result(15) for future in futures] == [1, 1]
    assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]


def test_begin_state_and_exact_outbox_event_commit_atomically(ledger):
    engine, _, _ = ledger
    owner = account(engine)
    previous = value(engine, "SELECT next_sequence FROM app.deletion_ledger_source")
    operation = begin(engine, owner)
    assert value(engine, "SELECT next_sequence FROM app.deletion_ledger_source") == previous + 1
    with engine.connect() as c:
        event = (
            c.execute(
                text("SELECT * FROM app.deletion_ledger_events WHERE sequence=:seq"),
                {"seq": previous},
            )
            .mappings()
            .one()
        )
        entry = json.loads(event["content"])
        assert entry["operation_id"] == str(operation)
        assert entry["account_id"] == str(owner)
        assert (entry["stage"], entry["outcome"]) == ("begin", "intent")
        assert (entry["expected_generation"], entry["deleting_generation"]) == (1, 2)
        assert (
            c.scalar(text("SELECT state FROM app.user_accounts WHERE id=:id"), {"id": owner})
            == "deleting"
        )


def test_current_head_keeps_existing_e7_worker_maintenance_permission(ledger):
    engine, _, _ = ledger
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_ai_worker")
        assert connection.scalar(text("SELECT app.e7_prune_ledger(1)")) == 0


@pytest.mark.parametrize(
    "profile,prefix,base",
    [
        ("motivation_worker", "MOTIVATION_WORKER", "calorie_app_motivation_worker"),
        ("nemesis_worker", "NEMESIS_WORKER", "calorie_app_nemesis_worker"),
        ("nemesis_finalizer", "NEMESIS_FINALIZER", "calorie_app_nemesis_finalizer"),
    ],
)
def test_current_head_real_e8_provisioners_keep_minimal_acl(ledger, profile, prefix, base):
    engine, _, _ = ledger
    assert_real_e8_provisioner_keeps_minimal_acl(engine, profile, prefix, base)


def assert_real_e8_provisioner_keeps_minimal_acl(engine, profile, prefix, base):
    import subprocess
    import sys

    parsed = engine.url
    login, password = "ledger_e8_" + uuid4().hex[:12], secrets.token_urlsafe(32)
    environment = os.environ | {
        "PGHOST": parsed.host,
        "PGPORT": str(parsed.port),
        "PGUSER": parsed.username,
        "PGDATABASE": parsed.database,
        "PGPASSWORD": parsed.password,
        prefix + "_LOGIN": login,
        prefix + "_PASSWORD": password,
    }
    root = Path(__file__).resolve().parents[3]

    def provision():
        result = subprocess.run(
            [sys.executable, str(root / "infra/local" / ("provision_" + profile + ".py"))],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert password not in result.stdout + result.stderr
        return result.returncode

    runtime = None
    try:
        assert provision() == 0, "head E8 provisioning failed; diagnostics withheld"
        runtime = create_engine(parsed.set(username=login, password=password), hide_parameters=True)
        assert value(runtime, "SELECT current_user") == login
        assert value(runtime, "SELECT pg_has_role(current_user,:base,'MEMBER')", base=base)
        with pytest.raises(DBAPIError), runtime.connect() as c:
            c.exec_driver_sql("SELECT * FROM app.deletion_ledger_source")
        with engine.begin() as c:
            c.exec_driver_sql(
                f'GRANT SELECT(installation_id) ON app.deletion_ledger_source TO "{login}"'
            )
        assert provision() != 0, "hostile ledger column grant must remain refused"
    finally:
        if runtime:
            runtime.dispose()
        with engine.begin() as c:
            if c.scalar(
                text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=:login)"), {"login": login}
            ):
                c.exec_driver_sql(f'DROP OWNED BY "{login}"')
                c.exec_driver_sql(f'DROP ROLE "{login}"')
