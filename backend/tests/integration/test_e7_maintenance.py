"""Real PG/files/process maintenance and real dump/restore, never live Gemini."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_e7_processes import (
    FakeProvider,
    WorkerProcess,
    attempts,
    create_job,
    expire_lease,
    fence_proven_dead,
    permits,
    row,
    sql_value,
    workers,
)
from test_e7_quota import finish, reserve
from test_e7_runtime import METADATA, image
from test_e7_runtime import e7 as _runtime_e7

from calorie_app.modules.ai import cleanup
from calorie_app.modules.ai import repository as repo
from calorie_app.modules.ai.image_preparation import prepare_image
from calorie_app.modules.ai.service import create_analysis
from calorie_app.modules.ai.storage import PhotoStorage

pytestmark = pytest.mark.integration
e7 = _runtime_e7


def sweep(state, root=None, *, use_configured_root=True):
    return cleanup.sweep(
        state["worker"],
        lambda: Session(state["worker"]),
        state["root"] if use_configured_root else root,
    )


def key_for(state, analysis):
    return sql_value(state, "SELECT storage_key FROM app.ai_analyses WHERE id=:id", id=analysis)


def expire_photo(state, analysis):
    sql_value(
        state,
        "UPDATE app.ai_analyses SET accepted_at=accepted_at-interval '25 hours',"
        "photo_expires_at=photo_expires_at-interval '25 hours' WHERE id=:id RETURNING id",
        id=analysis,
    )


@pytest.mark.parametrize("claimed", [False, True])
def test_expired_photo_never_reaches_provider_from_queued_or_claimed_worker(e7, claimed):
    job, analysis = create_job(e7)
    with FakeProvider() as fake, workers(e7, fake) as spawn:
        worker = spawn(job, pause=[("after_claim", 1)] if claimed else [])
        if claimed:
            worker.start()
            worker.event("hook", boundary="after_claim", occurrence=1)
        expire_photo(e7, analysis)
        if claimed:
            worker.send()
        else:
            worker.start()
        worker.finish()
        assert row(e7, analysis)["state"] == "failed"
        assert row(e7, analysis)["error_code"] == "image_expired"
        assert attempts(e7, job) == [] and permits(e7) == 0
        assert fake.counts() == {"countTokens": 0, "generateContent": 0}
        assert list(e7["root"].iterdir()) == []


@pytest.mark.parametrize("failure", ["unlink", "ack"])
def test_durable_cleanup_intent_survives_unlink_failure_or_ack_rollback_and_retry(e7, failure):
    _, analysis = create_job(e7)
    key = key_for(e7, analysis)
    target = e7["root"] / (key + ".jpg")
    expire_photo(e7, analysis)
    original = repo.call

    def failed_ack(session, statement, **parameters):
        value = original(session, statement, **parameters)
        if "app.e7_cleanup_ack" in statement:
            raise OSError("synthetic crash after SQL ACK before commit")
        return value

    injection = (
        patch.object(PhotoStorage, "delete", side_effect=OSError("synthetic unlink failure"))
        if failure == "unlink"
        else patch.object(repo, "call", side_effect=failed_ack)
    )
    with injection:
        assert sweep(e7)["removed"] == 0
    assert (
        sql_value(e7, "SELECT count(*) FROM app.ai_cleanup_intents WHERE storage_key=:key", key=key)
        == 1
    )
    assert key_for(e7, analysis) == key and target.exists() == (failure == "unlink")
    assert sweep(e7)["removed"] == 1
    assert not target.exists() and key_for(e7, analysis) is None
    assert sql_value(e7, "SELECT count(*) FROM app.ai_cleanup_intents") == 0
    assert sweep(e7)["removed"] == 0


@pytest.mark.parametrize("suffix", [".jpg", ".staging"])
def test_orphan_grace_and_active_storage_advisory_lock_protect_owned_file(e7, suffix):
    key = uuid4().hex
    storage = PhotoStorage(e7["root"])
    storage.activate(key, prepare_image(image()).data)
    target = e7["root"] / (key + ".jpg")
    if suffix == ".staging":
        target = target.replace(e7["root"] / (key + suffix))
    assert sweep(e7)["removed"] == 0 and target.exists()  # fresh grace window
    old = time.time() - 301
    os.utime(target, (old, old))
    with e7["admin"].connect() as connection, Session(bind=connection) as session:
        name = "e7-storage:" + key
        assert repo.lock_session(session, name)
        session.commit()
        try:
            assert sweep(e7)["removed"] == 0 and target.exists()
            assert sql_value(e7, "SELECT count(*) FROM app.ai_cleanup_intents") == 0
        finally:
            assert repo.unlock_session(session, name)
            session.commit()
    assert sweep(e7)["removed"] == 1 and not target.exists()
    assert sweep(e7)["removed"] == 0


def test_purge_during_live_provider_io_preserves_permit_and_anonymizes_ledger(e7):
    job, analysis = create_job(e7)
    owner = UUID(e7["boots"][0]["account_id"])
    key = key_for(e7, analysis)
    principal = e7["principals"][0]
    with FakeProvider(hold_count=True) as fake, workers(e7, fake) as spawn:
        worker = spawn(job)
        worker.start()
        fake.accepted(1)
        assert permits(e7) == 1 and not worker.children[0][0].wait(0)
        operation = uuid4()
        with e7["admin"].begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
            connection.execute(
                text("SELECT app.begin_account_deletion(:owner,:operation,1)"),
                {"owner": owner, "operation": operation},
            )
            # Synthetic trusted identity confirmation; no external IdP is called.
            connection.execute(
                text("SELECT app.confirm_account_deletion(:operation)"), {"operation": operation}
            )
            connection.execute(
                text("SELECT app.purge_deleted_account(:operation)"), {"operation": operation}
            )
        assert permits(e7) == 1 and not worker.children[0][0].wait(0)
        assert sql_value(e7, "SELECT count(*) FROM app.user_accounts WHERE id=:id", id=owner) == 0
        assert sql_value(e7, "SELECT count(*) FROM app.ai_analyses WHERE id=:id", id=analysis) == 0
        with e7["admin"].connect() as connection:
            saved = dict(connection.execute(text("SELECT * FROM app.ai_attempts")).mappings().one())
        assert saved["job_id"] is None and saved["reserved_tokens"] == 10240
        encoded = json.dumps(saved, default=str)
        assert all(
            value not in encoded for value in (str(owner), principal.issuer, principal.subject, key)
        )
        with patch.object(
            PhotoStorage, "delete", side_effect=OSError("synthetic host unlink outage")
        ):
            assert sweep(e7)["removed"] == 0
        assert (
            sql_value(
                e7, "SELECT count(*) FROM app.ai_cleanup_intents WHERE storage_key=:key", key=key
            )
            == 1
        )
        fake.release(1)
        worker.finish()
        assert permits(e7) == 0 and fake.counts() == {"countTokens": 1, "generateContent": 0}
        assert sql_value(e7, "SELECT count(*) FROM app.ai_attempts") == 1
        assert sql_value(e7, "SELECT count(*) FROM app.ai_cleanup_intents") == 0
        assert list(e7["root"].iterdir()) == []


@pytest.mark.parametrize("root_mode", ["none", "unavailable"])
def test_quiet_sweep_prunes_full_receipt_but_preserves_minimal_replay_without_storage(
    e7, root_mode, tmp_path
):
    _, analysis = create_job(e7)
    owner = UUID(e7["boots"][0]["account_id"])
    with e7["admin"].connect() as connection:
        saved = dict(
            connection.execute(
                text("SELECT * FROM app.ai_receipts WHERE owner_id=:owner"), {"owner": owner}
            )
            .mappings()
            .one()
        )
    sql_value(
        e7,
        "UPDATE app.ai_receipts SET created_at=clock_timestamp()-interval "
        "'1464 hours' WHERE owner_id=:owner RETURNING operation_id",
        owner=owner,
    )
    root = None if root_mode == "none" else tmp_path / "unprovisioned-photo-root"
    assert sweep(e7, root, use_configured_root=False)["storage_available"] is False
    assert sql_value(
        e7,
        "SELECT response_payload IS NULL FROM app.ai_receipts WHERE owner_id=:owner",
        owner=owner,
    )
    assert (
        sql_value(
            e7, "SELECT result_minimal FROM app.ai_receipts WHERE owner_id=:owner", owner=owner
        )
        == saved["result_minimal"]
    )
    with (
        patch(
            "calorie_app.modules.ai.service.prepare_image",
            side_effect=AssertionError("replay cannot decode"),
        ),
        patch.object(PhotoStorage, "activate", side_effect=AssertionError("replay cannot write")),
    ):
        replay = create_analysis(
            e7["api"],
            e7["principals"][0],
            UUID(e7["boots"][0]["sync_epoch"]),
            saved["operation_id"],
            METADATA,
            image(),
            e7["settings"],
        )
    assert (
        replay.replayed and replay.status == 202 and replay.payload["analysis_id"] == str(analysis)
    )
    assert sql_value(e7, "SELECT count(*) FROM app.ai_jobs") == 1
    assert sql_value(e7, "SELECT count(*) FROM app.ai_receipts") == 1


def test_quiet_ledger_prune_removes_only_old_finished_attempts_without_active_permit(e7):
    _, finished = reserve(e7)
    assert finish(e7, finished)
    _, unfinished = reserve(e7, purpose="energy_adjustment")
    sql_value(
        e7,
        "UPDATE app.ai_attempts SET dispatched_at=clock_timestamp()-interval"
        " '337 hours' RETURNING id",
    )
    sweep(e7, None, use_configured_root=False)
    assert (
        sql_value(e7, "SELECT count(*) FROM app.ai_attempts WHERE id=:id", id=finished["attempt"])
        == 0
    )
    assert (
        sql_value(e7, "SELECT count(*) FROM app.ai_attempts WHERE id=:id", id=unfinished["attempt"])
        == 1
    )
    assert permits(e7) == 1


PG17_IMAGE = (
    "docker.io/library/postgres:17@sha256:"
    "2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)


def pg_command(name, arguments, *, interactive=False):
    directory = os.environ.get("E7_TEST_PG_BIN")
    path = (
        Path(directory) / (name + (".exe" if os.name == "nt" else ""))
        if directory
        else shutil.which(name)
    )
    if path and Path(path).is_file():
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, check=True, timeout=10
        )
        if " 17." in result.stdout:
            return [str(path), *arguments]
    docker = shutil.which("docker")
    if not docker:
        pytest.fail("Restore proof requires PG17 CLI or Docker with the pinned PostgreSQL17 image")
    return [
        docker,
        "run",
        "--rm",
        "--network",
        "host",
        "-e",
        "PGPASSWORD",
        *(["-i"] if interactive else []),
        PG17_IMAGE,
        name,
        *arguments,
    ]


def pg_args(url):
    assert url.database.endswith("_test")
    return [
        "--host",
        url.host,
        "--port",
        str(url.port),
        "--username",
        url.username,
        "--dbname",
        url.database,
    ]


@contextmanager
def restored_database(state, dump):
    name = "e7_restore_" + uuid4().hex[:12] + "_test"
    base = state["admin"].url
    control = create_engine(
        base.set(database="postgres"), hide_parameters=True, isolation_level="AUTOCOMMIT"
    )
    restored_admin = restored_worker = None
    try:
        with control.connect() as connection:
            pg = connection.connection.driver_connection
            connection.exec_driver_sql(
                sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator")
                .format(sql.Identifier(name))
                .as_string(pg)
            )
            connection.exec_driver_sql(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC")
                .format(sql.Identifier(name))
                .as_string(pg)
            )
            connection.exec_driver_sql(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}")
                .format(sql.Identifier(name), sql.Identifier(state["worker"].url.username))
                .as_string(pg)
            )
        target = base.set(database=name)
        environment = dict(os.environ, PGPASSWORD=base.password)
        with dump.open("rb") as archive:
            result = subprocess.run(
                pg_command("pg_restore", [*pg_args(target), "--exit-on-error"], interactive=True),
                stdin=archive,
                capture_output=True,
                env=environment,
                timeout=60,
            )
        assert result.returncode == 0, f"pg_restore exit code {result.returncode}"
        restored_admin = create_engine(target, hide_parameters=True)
        restored_worker = create_engine(
            state["worker"].url.set(database=name), hide_parameters=True
        )
        yield {**state, "admin": restored_admin, "worker": restored_worker}
    finally:
        for engine in (restored_worker, restored_admin):
            if engine is not None:
                engine.dispose()
        with control.connect() as connection:
            pg = connection.connection.driver_connection
            connection.exec_driver_sql(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)).as_string(pg)
            )
        control.dispose()


def test_real_dump_restore_new_epoch_never_replays_old_job_and_resume_requires_hold_and_fencing(
    e7, tmp_path
):
    job, analysis = create_job(e7)
    sql_value(e7, "UPDATE app.ai_pools SET rpm=1 WHERE provider='mock' RETURNING scope")
    with FakeProvider() as fake, workers(e7, fake) as spawn:
        original = spawn(job, pause=[("after_dispatch", 1)])
        original.start()
        original.event("hook", boundary="after_dispatch", occurrence=1)
        dump = tmp_path / "owned-older-snapshot.dump"
        environment = dict(os.environ, PGPASSWORD=e7["admin"].url.password)
        with dump.open("wb") as archive:
            result = subprocess.run(
                pg_command("pg_dump", [*pg_args(e7["admin"].url), "--format=custom"]),
                stdout=archive,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=60,
            )
        assert result.returncode == 0 and dump.stat().st_size > 0
        original.kill()
        assert original.children == [] and original.process.poll() is not None
        fence_proven_dead(e7, job)
        with restored_database(e7, dump) as restored:
            before = attempts(restored, job)
            assert (
                len(before) == 1 and before[0]["io_finished_at"] is None and permits(restored) == 1
            )
            epoch = uuid4()
            sql_value(
                restored,
                "UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1 RETURNING id",
                epoch=epoch,
            )
            assert (
                sql_value(restored, "SELECT dispatch_open FROM app.ai_controls WHERE id=1") is False
            )
            expire_lease(restored, job)
            # Same helper, but its real SCRAM connection targets the restored DB.
            replacement = WorkerProcess(restored, fake, job)
            try:
                replacement.start()
                assert replacement.finish()["handled"] is False
            finally:
                replacement.close()
            assert fake.counts() == {"countTokens": 0, "generateContent": 0}
            assert row(restored, analysis)["state"] == "failed" and permits(restored) == 1
            evidence = hashlib.sha256(
                b"all-own-pre-restore-processes-physically-fenced"
            ).hexdigest()
            for age in (0, 335):
                sql_value(
                    restored,
                    "UPDATE app.ai_controls SET closed_at=clock_timestamp()-"
                    "make_interval(hours=>:hours) WHERE id=1 RETURNING id",
                    hours=age,
                )
                with pytest.raises(DBAPIError) as refused:
                    sql_value(
                        restored,
                        "SELECT app.e7_reconcile(:epoch,:evidence,true)",
                        epoch=epoch,
                        evidence=evidence,
                    )
                assert refused.value.orig.sqlstate == "23514"
            sql_value(
                restored,
                "UPDATE app.ai_controls SET closed_at=clock_timestamp()-"
                "interval '336 hours' WHERE id=1 RETURNING id",
            )
            for supplied_epoch, supplied_evidence, fenced in (
                (uuid4(), evidence, True),
                (epoch, "bad", True),
                (epoch, evidence, False),
            ):
                with pytest.raises(DBAPIError) as refused:
                    sql_value(
                        restored,
                        "SELECT app.e7_reconcile(:epoch,:evidence,:fenced)",
                        epoch=supplied_epoch,
                        evidence=supplied_evidence,
                        fenced=fenced,
                    )
                assert refused.value.orig.sqlstate == "23514"
            sql_value(
                restored,
                "SELECT app.e7_reconcile(:epoch,:evidence,true)",
                epoch=epoch,
                evidence=evidence,
            )
            saved = attempts(restored, job)
            assert (
                len(saved) == 1
                and saved[0]["reserved_tokens"] == before[0]["reserved_tokens"] == 10240
            )
            assert (
                saved[0]["fenced_at"] is not None and saved[0]["fencing_evidence_hash"] == evidence
            )
            assert permits(restored) == 0 and sql_value(
                restored, "SELECT dispatch_open FROM app.ai_controls WHERE id=1"
            )
            denied, _ = reserve(restored)
            assert denied == {"error": "ai_rate_limited"}
            assert fake.counts() == {"countTokens": 0, "generateContent": 0}
