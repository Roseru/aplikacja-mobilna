"""Controlled DB clock, real independent worker processes and stale-read races."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_e4_push import operation, send
from test_e4_push import synced as synced_fixture
from test_e7_runtime import role_engine
from test_e8_source_pg import complete_meal, matured, project

from calorie_app.modules.analytics.motivation import repository
from calorie_app.modules.analytics.motivation.service import read_motivation
from calorie_app.motivation_worker import cycle

pytestmark = pytest.mark.integration
synced = synced_fixture


@pytest.fixture(autouse=True)
def isolate_e8_accounts(database):
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    yield
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))


@contextmanager
def clock(engine, instant):
    def set_clock(value):
        # Only a disposable DB owner changes this private implementation. No
        # transport caller can set time, points, witnesses or qualification.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE OR REPLACE FUNCTION app.e8_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ "
                "SELECT " + value + " $$"
            )

    set_clock("TIMESTAMPTZ '" + instant + "'")
    try:
        yield
    finally:
        set_clock("clock_timestamp()")


@pytest.fixture
def worker(database):
    engine, _, _ = database
    runtime, login = role_engine(database, "calorie_app_motivation_worker")
    try:
        yield runtime
    finally:
        runtime.dispose()
        with engine.begin() as connection:
            pg = connection.connection.driver_connection
            connection.exec_driver_sql(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
            )
            connection.exec_driver_sql(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
            )


def test_midnight_no_new_sync_two_real_workers_and_restart(synced, worker):
    engine, _, _, owner, *_ = synced
    with clock(engine, "2024-01-01T12:00:00Z"):
        complete_meal(synced)
        matured(engine, owner)
        assert project(engine, owner)["total_points"] == 0
        with Session(engine) as session, session.begin():
            # Read clock is separately frozen for honest preworker pending state.
            from datetime import UTC, datetime
            from unittest.mock import patch

            with patch(
                "calorie_app.modules.analytics.motivation.service.database_now",
                return_value=datetime(2024, 1, 2, tzinfo=UTC),
            ):
                assert read_motivation(session, owner)["status"] == "pending_materialization"
    with clock(engine, "2024-01-02T00:00:00Z"):
        env = os.environ | {
            "DATABASE_URL": worker.url.render_as_string(hide_password=False),
            "PYTHONUTF8": "1",
        }
        args = [
            sys.executable,
            "-m",
            "calorie_app.motivation_worker",
            "--once",
            "--batch",
            "1",
            "--date-batch",
            "4",
        ]
        children = [
            subprocess.Popen(
                args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            for _ in range(2)
        ]
        try:
            outputs = [child.communicate(timeout=30) for child in children]
            assert all(child.returncode == 0 for child in children), outputs
            assert all(json.loads(output[0])["status"] == "ok" for output in outputs)
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
        assert project(engine, owner)["total_points"] == 1
        restart = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
        assert restart.returncode == 0, restart.stdout
        assert project(engine, owner)["total_points"] == 1
        with engine.connect() as c:
            assert (
                c.scalar(
                    text("SELECT count(*) FROM app.motivation_days WHERE owner_id=:owner"),
                    {"owner": owner},
                )
                == 1
            )


def test_worker_stale_candidate_rechecks_correction_after_owner_lock(synced, worker, monkeypatch):
    engine, _, _, owner, boot, *_ = synced
    with clock(engine, "2024-01-01T12:00:00Z"):
        op = complete_meal(synced)
        matured(engine, owner)
    selected, release = Event(), Event()
    original = repository.process_owner

    def barrier(session, who, batch):
        selected.set()
        assert release.wait(15)
        return original(session, who, batch)

    monkeypatch.setattr(repository, "process_owner", barrier)
    with clock(engine, "2024-01-02T00:00:00Z"), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cycle, worker, 100, 256)
        assert selected.wait(15)
        delete = operation(boot, "meal", entity_id=op["entity_id"], base=1, action="delete")
        assert send(synced, [delete])[0]["status"] == "accepted"
        release.set()
        assert future.result(timeout=30)["owners_handled"] >= 1
        assert project(engine, owner)["total_points"] == 0


def test_missing_bootstrap_projection_is_bounded_catchup_candidate(synced, worker):
    engine, _, _, owner, *_ = synced
    result = cycle(worker, 100, 256)
    assert result["owners_handled"] >= 1
    assert project(engine, owner)["backfill_state"] == "ready"
    assert project(engine, owner)["total_points"] == 0


def test_weight_only_multizone_matures_independently_no_fake_diary(synced):
    engine, _, _, owner, boot, *_ = synced
    with clock(engine, "2024-01-04T23:00:00Z"):
        for day in ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"):
            weight = {
                "local_date": day,
                "occurred_at": day + "T12:00:00Z",
                "time_zone": "UTC",
                "weight_kg": "75",
            }
            assert (
                send(synced, [operation(boot, "weight", payload=weight)])[0]["status"] == "accepted"
            )
        # Jan4 is already closed in Kiritimati while still open in UTC.
        early = {
            "local_date": "2024-01-04",
            "occurred_at": "2024-01-03T12:00:00Z",
            "time_zone": "Pacific/Kiritimati",
            "weight_kg": "76",
        }
        early_op = operation(boot, "weight", payload=early)
        assert send(synced, [early_op])[0]["status"] == "accepted"
        matured(engine, owner)
        with engine.connect() as c:
            assert (
                c.scalar(
                    text("SELECT count(*) FROM app.diary_days WHERE owner_id=:owner"),
                    {"owner": owner},
                )
                == 0
            )
            assert (
                c.scalar(
                    text(
                        "SELECT active FROM app.motivation_badges WHERE owner_id=:owner "
                        "AND badge_code='weight_days_4_14'"
                    ),
                    {"owner": owner},
                )
                is True
            )
        assert (
            send(
                synced,
                [
                    operation(
                        boot, "weight", entity_id=early_op["entity_id"], base=1, action="delete"
                    )
                ],
            )[0]["status"]
            == "accepted"
        )
        with engine.connect() as c:
            assert (
                c.scalar(
                    text(
                        "SELECT active FROM app.motivation_badges WHERE owner_id=:owner "
                        "AND badge_code='weight_days_4_14'"
                    ),
                    {"owner": owner},
                )
                is False
            )


def test_cli_rejects_api_and_migrator_roles(database):
    _, _, url = database
    result = subprocess.run(
        [sys.executable, "-m", "calorie_app.motivation_worker", "--once"],
        env=os.environ | {"DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "motivation_worker_role_or_schema_invalid"
