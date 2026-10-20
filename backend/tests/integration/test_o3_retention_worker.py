"""Real worker login, bounded scheduling, retention invariants and failure probes."""

import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.modules.identity.models import UserAccount
from calorie_app.modules.sync.models import SyncReceipt

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra/integration"))
from worker import LOCK_ID, Worker, healthy, read_json  # noqa: E402

from tests.support.deletion_regression import begin as begin_deletion

pytestmark = pytest.mark.integration


@pytest.fixture
def fixture(database, tmp_path):
    engine, _, url = database
    password = os.environ.get("TEST_WORKER_PASSWORD")
    assert password, "Actual worker login tests require TEST_WORKER_PASSWORD"
    worker_url = make_url(url).set(username="calorie_app_worker", password=password)
    settings = Settings(database_url=SecretStr(worker_url.render_as_string(hide_password=False)))
    # Fresh identity range preserves stable ordering without reusing a permanently fenced subject.
    identity_base = uuid4().int & ~0xFFFF
    a, b, c = [UUID(int=identity_base + i) for i in (301, 302, 303)]
    # The session-scoped database is shared with other integration fixtures.
    # Its conftest refuses anything except an explicit dedicated *_test database.
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")
    with Session(engine) as session, session.begin():
        session.add_all(
            UserAccount(id=x, issuer="https://retention.test", subject=str(x)) for x in (a, b, c)
        )
        session.flush()
        epoch = session.scalar(text("SELECT sync_epoch FROM app.installation_state"))
        for owner, count in ((a, 3), (b, 1), (c, 1)):
            for _ in range(count):
                session.add(
                    SyncReceipt(
                        owner_id=owner,
                        operation_id=uuid4(),
                        request_hash="b" * 64,
                        source_epoch=epoch,
                        entity_type="weight",
                        entity_id=uuid4(),
                        status="accepted",
                        revision=1,
                        response={"status": "accepted", "private": "must-not-be-logged"},
                    )
                )
        session.flush()
        session.execute(text("UPDATE app.sync_receipts SET created_at=now()-interval '61 days'"))
        session.add(
            SyncReceipt(
                owner_id=a,
                operation_id=uuid4(),
                request_hash="c" * 64,
                source_epoch=epoch,
                entity_type="weight",
                entity_id=uuid4(),
                status="accepted",
                revision=1,
                response={"fresh": True},
            )
        )
        begin_deletion(session.connection(), c, uuid4(), 1)
        # No HTTP activity: technical read copies alone must still be cleaned.
        for old in (True, False):
            sid = uuid4()
            session.execute(
                text(
                    "INSERT INTO app.read_sessions VALUES "
                    "(:sid,:a,1,:epoch,'meals',CURRENT_DATE,CURRENT_DATE,1,"
                    "now()-(:age * interval '1 minute'),"
                    "now()-(:age * interval '1 minute')+interval '60 minutes','{}',3,3)"
                ),
                {"sid": sid, "a": a, "epoch": epoch, "age": 120 if old else 0},
            )
            for position in (1, 2, 3):
                session.execute(
                    text("INSERT INTO app.read_session_items VALUES (:sid,:p,:a,'{}',1)"),
                    {"sid": sid, "p": position, "a": a},
                )
    worker = Worker(tmp_path, settings, batch=2, owners=2, seconds=10)
    yield engine, worker, (a, b, c), epoch
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")


def test_fair_continuation_restart_preserves_evidence_fresh_copies_and_epoch(fixture):
    engine, worker, (a, b, c), epoch = fixture
    worker.owners = 1
    first = worker.run()
    assert first["state"] == "pending" and first["owners"] == 1
    assert first["removed"]["receipts"] == 2 and first["removed"]["read_items"] == 2
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM app.sync_receipts")) == 6
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM app.sync_receipts WHERE owner_id=:b AND response IS NULL"
                ),
                {"b": b},
            )
            == 0
        )
    # A new process object resumes the private cursor, without replaying the hot first owner.
    replacement = Worker(
        worker.state,
        Settings(database_url=SecretStr(worker.engine.url.render_as_string(hide_password=False))),
        batch=2,
        owners=1,
        seconds=10,
    )
    following = replacement.run()
    assert following["owners"] == 1 and following["removed"]["receipts"] == 1
    result = None
    for _ in range(6):
        result = replacement.run()
        if result["state"] == "ok":
            break
    assert result["state"] == "ok" and healthy(result, 60)
    public = str(result) + (worker.state / "status.json").read_text()
    assert str(a) not in public and "must-not-be-logged" not in public
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM app.sync_receipts")) == 6
        assert (
            conn.scalar(text("SELECT count(*) FROM app.sync_receipts WHERE response IS NULL")) == 4
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.sync_receipts WHERE response->>'fresh'='true'")
            )
            == 1
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM app.sync_receipts "
                    "WHERE owner_id=:c AND response IS NOT NULL"
                ),
                {"c": c},
            )
            == 1
        )
        assert conn.scalar(text("SELECT count(*) FROM app.read_sessions")) == 1
        assert conn.scalar(text("SELECT count(*) FROM app.read_session_items")) == 3
        assert conn.scalar(text("SELECT sync_epoch FROM app.installation_state")) == epoch
        assert conn.scalar(text("SELECT count(*) FROM app.user_accounts")) == 3


def test_single_session_lock_and_bad_login_do_not_change_success_or_data(fixture):
    engine, worker, _, _ = fixture
    good = worker.run()
    status_before = (worker.state / "status.json").read_bytes()
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_ID})
        connection.commit()
        assert worker.run() == {"state": "busy"}
        assert (worker.state / "status.json").read_bytes() == status_before
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
        connection.commit()
    settings = Settings(
        database_url=SecretStr(
            worker.engine.url.set(password="wrong-secret-not-in-logs").render_as_string(
                hide_password=False
            )
        )
    )
    failed = Worker(worker.state, settings).run()
    assert failed["state"] == "failed" and failed["last_success"] == good["last_success"]
    assert not healthy(failed, 3600)
    assert "wrong-secret-not-in-logs" not in str(failed)


def test_lock_timeout_does_not_starve_other_owners_or_claim_success(fixture):
    engine, worker, (a, b, _), _ = fixture
    with engine.begin() as connection:
        connection.execute(
            text("SELECT id FROM app.user_accounts WHERE id=:a FOR UPDATE"), {"a": a}
        )
        result = worker.run()
    assert result["state"] == "failed" and result["errors"] == 1
    assert result["removed"]["receipts"] == 1 and not healthy(result, 3600)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.sync_receipts WHERE owner_id=:b AND response IS NULL"
                ),
                {"b": b},
            )
            == 1
        )
    assert read_json(worker.state / "progress.json")["cursor"] == str(UUID(int=0))


def test_transition_to_deleting_between_scan_and_lock_is_skipped(fixture):
    engine, worker, (a, _, _), _ = fixture
    changed = False

    def transition(conn, cursor, statement, parameters, context, many):
        nonlocal changed
        if "FOR UPDATE" in statement and not changed:
            changed = True
            with engine.begin() as other:
                begin_deletion(other, a, uuid4(), 1)

    event.listen(worker.engine, "before_cursor_execute", transition)
    result = worker.run()
    assert changed and result["skipped"] == 1 and result["errors"] == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.sync_receipts "
                    "WHERE owner_id=:a AND response IS NOT NULL"
                ),
                {"a": a},
            )
            == 4
        )


def test_lost_database_session_aborts_without_reconnecting_and_releasing_lock(fixture):
    engine, worker, _, _ = fixture
    terminated = False

    def disconnect(conn, cursor, statement, parameters, context, many):
        nonlocal terminated
        if "FOR UPDATE" in statement and not terminated:
            terminated = True
            with engine.begin() as other:
                other.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE usename='calorie_app_worker' AND datname=current_database()"
                    )
                )

    event.listen(worker.engine, "before_cursor_execute", disconnect)
    result = worker.run()
    assert terminated and result["state"] == "failed" and result["owners"] == 0
    assert result["removed"] == {} and not healthy(result, 3600)
    with engine.connect() as other:
        assert other.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
        other.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})


def test_worker_refuses_admin_role_and_shutdown_does_not_prune(fixture):
    from threading import Event

    engine, worker, _, _ = fixture
    bad = Worker(
        worker.state,
        Settings(database_url=SecretStr(engine.url.render_as_string(hide_password=False))),
    )
    assert bad.run()["state"] == "failed"
    stop = Event()
    stop.set()
    result = worker.run(stop)
    assert result["state"] == "stopped" and result["owners"] == 0
    assert result["last_success"] is None
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT count(*) FROM app.sync_receipts WHERE response IS NULL"))
            == 0
        )


def test_worker_schedules_e6_minimization_preserving_minimal_result_and_fresh_payload(fixture):
    engine, worker, (a, _, _), epoch = fixture
    operations = [uuid4(), uuid4()]
    with engine.begin() as connection:
        for operation, age in zip(operations, (61, 0), strict=True):
            connection.execute(
                text(
                    "INSERT INTO app.community_receipts "
                    "(owner_id,operation_kind,operation_id,request_hash,generation,sync_epoch,"
                    "status_code,response_payload,result_minimal,created_at) VALUES "
                    "(:owner,'vote',:operation,:hash,1,:epoch,200,"
                    '\'{"private":"must-not-be-logged"}\','
                    "'{\"result\":\"accepted\"}',now()-(:age * interval '1 day'))"
                ),
                {"owner": a, "operation": operation, "hash": "d" * 64, "epoch": epoch, "age": age},
            )
    result = worker.run()
    assert result["state"] in {"ok", "pending"} and result["errors"] == 0
    assert result["removed"]["community_receipts"] == 1
    with engine.connect() as connection:
        for operation, expired in zip(operations, (True, False), strict=True):
            row = connection.execute(
                text(
                    "SELECT request_hash,result_minimal,response_payload,sync_epoch "
                    "FROM app.community_receipts WHERE owner_id=:owner AND operation_id=:operation"
                ),
                {"owner": a, "operation": operation},
            ).one()
            assert row.request_hash == "d" * 64 and row.result_minimal == {"result": "accepted"}
            assert row.sync_epoch == epoch
            assert row.response_payload == (None if expired else {"private": "must-not-be-logged"})


def test_real_periodic_process_runs_again_without_http_and_logs_only_aggregates(fixture):
    import subprocess
    import time

    _, worker, owners, _ = fixture
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=worker.engine.url.render_as_string(hide_password=False),
        RETENTION_INTERVAL_SECONDS="5",
        RETENTION_RETRY_SECONDS="1",
        RETENTION_BATCH="2",
        RETENTION_MAX_OWNERS="2",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[3] / "infra/integration/worker.py"),
            "serve",
            "--state",
            str(worker.state),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        first = None
        while time.monotonic() < deadline:
            status = read_json(worker.state / "status.json")
            if healthy(status, 60):
                if first is None:
                    first = status["last_attempt"]
                elif status["last_attempt"] != first:
                    break
            assert process.poll() is None, "Periodic worker exited unexpectedly"
            time.sleep(0.1)
        else:
            pytest.fail("No second actual scheduled pass")
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    assert "last_success" in output
    assert all(str(owner) not in output for owner in owners)
    assert "must-not-be-logged" not in output
    assert environment["DATABASE_URL"] not in output
    if os.name != "nt":
        assert process.returncode == 0  # Real SIGTERM uses the graceful stop handler.
