"""Author acceptance: real archive restore and bounded all-history source rebuild."""

import hashlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from test_e4_push import SECRET, operation, request, send
from test_e4_push import synced as synced_fixture
from test_e5_statistics import example
from test_e7_maintenance import pg_command
from test_e8_consent_pg import put
from test_e8_ranking_pg import Verifier
from test_e8_source_pg import complete_meal, matured, project

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.router import execute_one

pytestmark = pytest.mark.integration
synced = synced_fixture
AUTH = {"Authorization": "Bearer a"}


@pytest.fixture(autouse=True)
def isolate_accounts(database):
    # Root executes this file serially against its explicitly injected test DB.
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    yield
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))


@contextmanager
def http_client(engine, principal):
    api = create_engine(
        engine.url, hide_parameters=True, connect_args={"options": "-c role=calorie_app_api"}
    )
    app = create_app(Settings(), engine=api)
    app.state.oidc_verifier = Verifier({"a": principal})
    try:
        with TestClient(app) as client:
            yield client
    finally:
        api.dispose()


def pg_arguments(url):
    assert url.database.endswith("_test")
    return [
        "--host",
        url.host,
        "--port",
        str(url.port or 5432),
        "--username",
        url.username,
        "--dbname",
        url.database,
    ]


def dump_database(engine, archive):
    # Credentials stay in the child environment, never argv or assertion output.
    with archive.open("wb") as output:
        result = subprocess.run(
            pg_command("pg_dump", [*pg_arguments(engine.url), "--format=custom"]),
            stdout=output,
            stderr=subprocess.PIPE,
            env=os.environ | {"PGPASSWORD": engine.url.password or ""},
            timeout=120,
        )
    assert result.returncode == 0, f"pg_dump exited {result.returncode}"
    assert archive.stat().st_size > 0


@contextmanager
def restore_archive(engine, archive):
    name = "e8_archive_" + uuid4().hex[:12] + "_test"
    target = engine.url.set(database=name)
    control = create_engine(
        engine.url.set(database="postgres"), hide_parameters=True, isolation_level="AUTOCOMMIT"
    )
    restored = None
    created = False
    try:
        with control.connect() as connection:
            pg = connection.connection.driver_connection
            connection.exec_driver_sql(
                sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator")
                .format(sql.Identifier(name))
                .as_string(pg)
            )
            created = True
        with archive.open("rb") as source:
            result = subprocess.run(
                pg_command(
                    "pg_restore", [*pg_arguments(target), "--exit-on-error"], interactive=True
                ),
                stdin=source,
                capture_output=True,
                env=os.environ | {"PGPASSWORD": target.password or ""},
                timeout=120,
            )
        assert result.returncode == 0, f"pg_restore exited {result.returncode}"
        restored = create_engine(target, hide_parameters=True)
        yield restored
    finally:
        if restored is not None:
            restored.dispose()
        if created:
            with control.connect() as connection:
                pg = connection.connection.driver_connection
                connection.exec_driver_sql(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)")
                    .format(sql.Identifier(name))
                    .as_string(pg)
                )
        control.dispose()


def process(engine, owner, batch):
    with Session(engine) as session, session.begin():
        return session.scalar(
            text("SELECT app.e8_process(:owner,:batch)"), {"owner": owner, "batch": batch}
        )


def test_real_older_archive_restore_requires_rebuild_and_fresh_consent(synced, tmp_path):
    engine, _, principal, owner, boot, checkpoint, _ = synced
    profile = operation(boot, "profile", payload=example("profile") | {"time_zone": "UTC"})
    assert send(synced, [profile])[0]["status"] == "accepted"
    old_source = complete_meal(synced)
    matured(engine, owner)
    assert project(engine, owner)["total_points"] == 1
    old_epoch = boot["sync_epoch"]
    legacy_key, affirmative_key = uuid4(), uuid4()
    with http_client(engine, principal) as client:
        assert put(client, key=legacy_key, revision=1).status_code == 200
        assert put(client, key=affirmative_key, revision=2, epoch=old_epoch).status_code == 200
        assert client.get("/api/v1/me/motivation", headers=AUTH).json()["ranking"]["effective"]
        assert len(client.get("/api/v1/ranking", headers=AUTH).json()["items"]) == 1
        legacy_hash = hashlib.sha256(
            canonical_json(
                {
                    "body": {"ranking": True, "automatic_energy_adjustment": False},
                    "if_match": 1,
                }
            )
        ).hexdigest()
        archive = tmp_path / "e8-owned-older-backup.dump"
        dump_database(engine, archive)
        # This committed opt-out occurs after backup and is absent from its restore.
        assert put(client, ranking=False, revision=3).status_code == 200
        assert not client.get("/api/v1/me/motivation", headers=AUTH).json()["ranking"]["effective"]
    with restore_archive(engine, archive) as restored:
        new_epoch = uuid4()
        with restored.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT ranking FROM app.user_consents WHERE owner_id=:o"), {"o": owner}
                )
                is True
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT request_hash FROM app.online_receipts "
                        "WHERE owner_id=:o AND key=:k AND operation='consents'"
                    ),
                    {"o": owner, "k": legacy_key},
                )
                == legacy_hash
            )
            connection.execute(
                text("UPDATE app.installation_state SET sync_epoch=:e WHERE id=1"), {"e": new_epoch}
            )
            assert (
                connection.scalar(text("SELECT dispatch_open FROM app.ai_controls WHERE id=1"))
                is False
            )
            assert (
                connection.scalar(text("SELECT sync_epoch FROM app.ai_controls WHERE id=1"))
                != new_epoch
            )
        with http_client(restored, principal) as client:
            pending = client.get("/api/v1/me/motivation", headers=AUTH)
            assert pending.status_code == 200, pending.text
            assert pending.json()["status"] == "pending_backfill"
            assert pending.json()["points"] is None
            assert pending.json()["ranking"]["pending_consent_refresh"]
            assert client.get("/api/v1/ranking", headers=AUTH).json()["items"] == []
            # Actual bounded rebuild does not affirm a restored true consent.
            batches = []
            for _ in range(10):
                result = process(restored, owner, 1)
                batches.append(result["processed"])
                if result["backfill_state"] == "ready":
                    break
            else:
                pytest.fail("single-date restored history did not finish bounded rebuild")
            assert max(batches) <= 1
            rebuilt = client.get("/api/v1/me/motivation", headers=AUTH).json()
            assert rebuilt["status"] == "final" and rebuilt["points"] == 1
            assert not rebuilt["ranking"]["effective"]
            assert client.get("/api/v1/ranking", headers=AUTH).json()["items"] == []
            for key, revision, epoch in ((legacy_key, 1, None), (affirmative_key, 2, old_epoch)):
                replay = put(client, key=key, revision=revision, epoch=epoch)
                assert replay.status_code == 409 and replay.json()["code"] == "sync_epoch_changed"
                assert replay.headers["cache-control"] == "no-store"
            factory = sessionmaker(restored, expire_on_commit=False)
            stale = request(boot, checkpoint, [old_source])
            with pytest.raises(SyncFailure) as refusal:
                execute_one(factory, owner, 1, stale, old_source, SECRET)
            assert refusal.value.code == "sync_epoch_changed"
            # Energy-only legacy mutation preserves requested true but cannot publish.
            assert put(client, revision=3, energy=True).status_code == 200
            assert not client.get("/api/v1/me/motivation", headers=AUTH).json()["ranking"][
                "effective"
            ]
            assert put(client, revision=4, energy=True, epoch=new_epoch).status_code == 200
            assert client.get("/api/v1/me/motivation", headers=AUTH).json()["ranking"]["effective"]
            assert len(client.get("/api/v1/ranking", headers=AUTH).json()["items"]) == 1
            assert put(client, ranking=False, energy=True, revision=5).status_code == 200
            assert client.get("/api/v1/ranking", headers=AUTH).json()["items"] == []
        with restored.connect() as connection:
            assert (
                connection.scalar(text("SELECT dispatch_open FROM app.ai_controls WHERE id=1"))
                is False
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT automatic_energy_adjustment FROM "
                        "app.user_consents WHERE owner_id=:o"
                    ),
                    {"o": owner},
                )
                is True
            )


def weight_digest(engine, owner):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT count(*),md5(string_agg(id::text||':'||revision::text"
                "||':'||local_date::text||':'||occurred_at::text||':'||weight_kg::text||':'||time_zone,"
                "'|' ORDER BY id)) FROM app.weights WHERE owner_id=:owner"
            ),
            {"owner": owner},
        ).one()


def test_large_sparse_history_resumes_and_serializes_accepted_write(synced, record_property):
    engine, _, principal, owner, boot, checkpoint, url = synced
    count, batch = 10000, 97
    started = monotonic()
    with engine.begin() as connection:
        # Only this old per-row zone/identity guard is bypassed for a known-valid
        # INSERT fixture. FK, account, E8 checks and revision constraints remain.
        connection.exec_driver_sql("ALTER TABLE app.weights DISABLE TRIGGER private_guard")
        connection.execute(
            text(
                "INSERT INTO app.weights(id,owner_id,revision,weight_kg,occurred_at,"
                "local_date,time_zone) SELECT md5(:owner_text||':'||i::text)::uuid,:owner,1,75,"
                "(DATE '1900-01-01'+i*2)::timestamp AT TIME ZONE 'UTC',DATE '1900-01-01'+i*2,'UTC'"
                " FROM generate_series(0,:last) i"
            ),
            {"owner": owner, "owner_text": str(owner), "last": count - 1},
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.weights WHERE owner_id=:owner "
                    "AND time_zone='UTC' AND revision=1 AND deleted_at IS NULL AND weight_kg=75 "
                    "AND (occurred_at AT TIME ZONE 'UTC')::date=local_date"
                ),
                {"owner": owner},
            )
            == count
        )
        connection.exec_driver_sql("ALTER TABLE app.weights ENABLE TRIGGER private_guard")
    initial = weight_digest(engine, owner)
    first = process(engine, owner, batch)
    assert first["processed"] == batch and first["backfill_state"] == "pending"
    durable = project(engine, owner)["backfill_after"]
    assert durable is not None
    # New connection/process lifetime resumes the persisted keyset checkpoint.
    engine.dispose()
    assert project(engine, owner)["backfill_after"] == durable
    accepted = operation(
        boot,
        "weight",
        payload={
            "local_date": "1880-01-01",
            "occurred_at": "1880-01-01T12:00:00Z",
            "time_zone": "UTC",
            "weight_kg": "76",
        },
    )
    writer_name = "e8-history-writer-" + uuid4().hex
    writer_engine = create_engine(
        url, hide_parameters=True, connect_args={"application_name": writer_name}
    )
    writer_factory = sessionmaker(writer_engine, expire_on_commit=False)
    writer_state = (writer_engine, writer_factory, principal, owner, boot, checkpoint, url)
    attempted = Event()

    def write():
        attempted.set()
        return send(writer_state, [accepted])[0]

    batches = [first["processed"]]
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with Session(engine) as locked, locked.begin():
                locked.execute(
                    text("SELECT id FROM app.user_accounts WHERE id=:owner FOR UPDATE"),
                    {"owner": owner},
                )
                future = pool.submit(write)
                assert attempted.wait(10)
                deadline = monotonic() + 15
                while True:
                    with engine.connect() as observer:
                        waiting = observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE application_name=:name AND wait_event_type='Lock'"
                            ),
                            {"name": writer_name},
                        )
                    if waiting:
                        break
                    assert monotonic() < deadline, (
                        "accepted writer never reached actual PG account wait"
                    )
                    attempted.wait(0.01)
                second = locked.scalar(
                    text("SELECT app.e8_process(:owner,:batch)"), {"owner": owner, "batch": batch}
                )
                batches.append(second["processed"])
            assert future.result(timeout=60)["status"] == "accepted"
    finally:
        writer_engine.dispose()
    committed_source = weight_digest(engine, owner)
    assert committed_source[0] == initial[0] + 1 and committed_source[1] != initial[1]
    for _ in range(count // batch + 10):
        result = process(engine, owner, batch)
        batches.append(result["processed"])
        if result["backfill_state"] == "ready":
            break
    else:
        pytest.fail("bounded sparse history backfill failed to resume to completion")
    assert max(batches) <= batch and sum(batches) == count
    assert weight_digest(engine, owner) == committed_source
    account = project(engine, owner)
    assert account["backfill_state"] == "ready" and account["total_points"] == 0
    assert account["active_badges"] == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.diary_days WHERE owner_id=:o"), {"o": owner}
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.motivation_days WHERE owner_id=:o"), {"o": owner}
            )
            == count + 1
        )
        assert (
            connection.scalar(
                text("SELECT sum(materialized_points) FROM app.motivation_days WHERE owner_id=:o"),
                {"o": owner},
            )
            == account["total_points"]
        )
        badge = connection.execute(
            text(
                "SELECT count(*),min(witness::text) FROM app.motivation_badges "
                "WHERE owner_id=:o AND active AND badge_code='weight_days_4_14'"
            ),
            {"o": owner},
        ).one()
        assert badge[0] == 1 and "1900-01-01" in badge[1]
        assert connection.scalar(
            text("SELECT source_position FROM app.motivation_accounts WHERE owner_id=:o"),
            {"o": owner},
        ) == connection.scalar(
            text("SELECT position FROM app.sync_counters WHERE owner_id=:o"), {"o": owner}
        )
    # Idle worker/restart remains idempotent and never rewrites accepted sources.
    assert process(engine, owner, batch)["processed"] == 0
    assert weight_digest(engine, owner) == committed_source
    for name, value in {
        "history_rows": count + 1,
        "maximum_batch": max(batches),
        "batch_calls": len(batches),
        "materialized_sum": account["total_points"],
        "history_seconds": round(monotonic() - started, 3),
    }.items():
        record_property(name, value)
