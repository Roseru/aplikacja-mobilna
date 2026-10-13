"""E9 uses the historical E resolver inside qualified E8 projections and frozen final results."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.modules.energy.service import energy_configuration
from calorie_app.modules.jobs.runner import Runner
from calorie_app.modules.profiles.schemas import ConsentInput
from calorie_app.modules.profiles.service import put_consents
from tests.integration.test_e7_runtime import role_engine
from tests.integration.test_e9_energy import body, notice, seed
from tests.support.e8_4_postgres import (
    activate,
    challenge,
    clock,
    complete_day,
    finalize,
    projection_rows,
    runtime,
    statistics,
)
from tests.support.e8_4_postgres import e8_4_services as e8_4_services

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_e9_changes_only_qualified_deficit_and_late_finalizer_freezes_same_result(
    tmp_path, late, automatic
):
    with runtime(now=datetime.now(UTC)) as rt:
        actor = rt["actors"]["a"]
        adapted = {
            "admin": rt["admin"],
            "api": rt["api"],
            "boots": [{"account_id": str(actor["owner"]), "sync_epoch": str(rt["epoch"])}],
        }
        original, goal, today = seed(adapted, existing_profile=True)
        activate(rt)
        accepted = challenge(rt, metrics=True)
        start = today + timedelta(days=1)
        complete_day(rt, "a", start, "2700")
        # E8 owns its test qualification clock; E9 continues to take its actual
        # application instant from clock_timestamp, so the new E is tomorrow.
        clock(rt, datetime.combine(start + timedelta(days=1), time(1), UTC))
        before = statistics(rt, accepted["id"]).json()
        assert before["self"]["mean_deficit"]["value"] == "-4.046242774566", before
        points = before["self"]["regularity"]
        source_before = projection_rows(rt, accepted["id"])
        current_body = body(adapted)
        api_headers = actor["headers"] | {"Idempotency-Key": str(uuid4())}
        worker, login = role_engine(
            (rt["admin"], None, rt["private"].admin_url), "calorie_app_ai_worker"
        )
        settings = Settings(
            database_url=rt["private"].api_url, environment="test", ai_photo_root=tmp_path
        )
        try:
            if automatic:
                with Session(rt["api"]) as s, s.begin():
                    c = put_consents(
                        s,
                        actor["owner"],
                        ConsentInput(ranking=False, automatic_energy_adjustment=True),
                        1,
                        uuid4(),
                    )
                affirmed = rt["client"].post(
                    "/api/v1/me/energy/affirm",
                    headers=api_headers,
                    json=current_body
                    | {
                        "id": str(original),
                        "consent_revision": c["revision"],
                        "notice": notice(automatic=True),
                    },
                )
                assert affirmed.status_code == 200, affirmed.text
                with Session(worker) as s, s.begin():
                    from calorie_app.modules.ai.repository import encoded

                    created = s.scalar(
                        text("SELECT app.e9_auto_enqueue(:owner,CAST(:p AS jsonb))"),
                        {
                            "owner": actor["owner"],
                            "p": encoded(energy_configuration(settings).profile),
                        },
                    )
                assert created is not None
                analysis_id = created["id"]
            else:
                created = rt["client"].post(
                    "/api/v1/me/energy/analyses",
                    headers=api_headers,
                    json=current_body | {"notice": notice()},
                )
                assert created.status_code == 200, created.text
                analysis_id = created.json()["id"]
            with rt["admin"].connect() as c:
                job = c.scalar(
                    text("SELECT id FROM app.ai_jobs WHERE energy_analysis_id=:id"),
                    {"id": analysis_id},
                )
            deadline = datetime.fromisoformat(accepted["deadline"].replace("Z", "+00:00"))

            def hook(boundary, claim):
                if automatic and late and boundary == "before_result_commit":
                    clock(rt, deadline + timedelta(microseconds=1))

            assert Runner(worker, lambda: Session(worker), settings, hook=hook).process(job)
            if not automatic:
                found = rt["client"].get(
                    "/api/v1/me/energy/analyses/" + str(analysis_id), headers=actor["headers"]
                )
                with rt["admin"].connect() as c:
                    technical = (
                        c.execute(
                            text(
                                "SELECT state,phase,generate_attempts,preflight_done,input_to"
                                "kens FROM app.ai_jobs"
                            )
                        )
                        .mappings()
                        .all()
                    )
                    attempts = (
                        c.execute(
                            text(
                                "SELECT kind,status,io_finished_at IS NOT NULL AS finished FR"
                                "OM app.ai_attempts"
                            )
                        )
                        .mappings()
                        .all()
                    )
                assert found.json()["state"] == "ready", (found.text, technical, attempts)
                if late:
                    clock(rt, deadline + timedelta(microseconds=1))
                applied = rt["client"].post(
                    "/api/v1/me/energy/analyses/accept",
                    headers=actor["headers"] | {"Idempotency-Key": str(uuid4())},
                    json=body(adapted)
                    | {"id": str(analysis_id), "revision": found.json()["revision"]},
                )
                assert applied.status_code == 200, applied.text
            after = statistics(rt, accepted["id"]).json()
            assert after["self"]["regularity"] == points | {"closed_days": 7 if late else 1}
            assert after["self"]["mean_deficit"]["value"] == ("-4.046242774566" if late else "0")
            with rt["admin"].connect() as c:
                assert (
                    c.scalar(
                        text("SELECT payload FROM app.goal_versions WHERE id=:id"), {"id": original}
                    )
                    == goal
                )
                assert (
                    c.scalar(
                        text("SELECT effective_from FROM app.energy_versions WHERE source=:source"),
                        {"source": "automatic" if automatic else "manual"},
                    )
                    == start
                )
            if late:
                assert projection_rows(rt, accepted["id"]) == source_before
                assert finalize(rt, accepted["id"])
                frozen = statistics(rt, accepted["id"]).json()
                assert frozen["status"] == "final"
                assert frozen["self"]["mean_deficit"]["value"] == "-4.046242774566"
                # A later finalizer observes the same durable projection set.
                assert finalize(rt, accepted["id"])
                assert statistics(rt, accepted["id"]).json()["self"] == frozen["self"]
        finally:
            worker.dispose()
            with rt["admin"].begin() as c:
                pg = c.connection.driver_connection
                c.exec_driver_sql(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
                )
                c.exec_driver_sql(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
                )


def test_expiry_is_rechecked_after_waiting_for_challenge_lock(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import sleep

    with runtime(now=datetime.now(UTC)) as rt:
        actor = rt["actors"]["a"]
        adapted = {
            "admin": rt["admin"],
            "api": rt["api"],
            "boots": [{"account_id": str(actor["owner"]), "sync_epoch": str(rt["epoch"])}],
        }
        seed(adapted, existing_profile=True)
        activate(rt)
        accepted = challenge(rt, metrics=True)
        created = rt["client"].post(
            "/api/v1/me/energy/analyses",
            headers=actor["headers"] | {"Idempotency-Key": str(uuid4())},
            json=body(adapted) | {"notice": notice()},
        )
        assert created.status_code == 200, created.text
        analysis = created.json()
        worker, login = role_engine(
            (rt["admin"], None, rt["private"].admin_url), "calorie_app_ai_worker"
        )
        settings = Settings(
            database_url=rt["private"].api_url, environment="test", ai_photo_root=tmp_path
        )
        try:
            with rt["admin"].connect() as c:
                job = c.scalar(
                    text("SELECT id FROM app.ai_jobs WHERE energy_analysis_id=:id"),
                    {"id": analysis["id"]},
                )
            Runner(worker, lambda: Session(worker), settings).process(job)
            ready = (
                rt["client"]
                .get("/api/v1/me/energy/analyses/" + analysis["id"], headers=actor["headers"])
                .json()
            )
            assert ready["state"] == "ready"
            locked = Event()
            release = Event()

            def holder():
                with rt["migrator"].begin() as c:
                    c.execute(
                        text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE"),
                        {"id": accepted["id"]},
                    )
                    locked.set()
                    assert release.wait(10)

            with ThreadPoolExecutor(2) as pool:
                hold = pool.submit(holder)
                assert locked.wait(5)
                with rt["admin"].begin() as c:
                    c.execute(
                        text(
                            "WITH t AS(SELECT clock_timestamp()+interval '2 seconds' e) "
                            "UPDATE app.energy_analyses SET created_at=t.e-interval '24 hours',"
                            "expires_at=t.e FROM t WHERE id=:id"
                        ),
                        {"id": analysis["id"]},
                    )
                accept = pool.submit(
                    rt["client"].post,
                    "/api/v1/me/energy/analyses/accept",
                    headers=actor["headers"] | {"Idempotency-Key": str(uuid4())},
                    json=body(adapted) | {"id": analysis["id"], "revision": ready["revision"]},
                )
                sleep(2.2)
                release.set()
                result = accept.result(timeout=10)
                hold.result(timeout=10)
            assert result.status_code == 410 and result.json()["code"] == "proposal_expired", (
                result.text
            )
            with rt["admin"].connect() as c:
                assert (
                    c.scalar(text("SELECT count(*) FROM app.energy_versions WHERE source='manual'"))
                    == 0
                )
        finally:
            worker.dispose()
            with rt["admin"].begin() as c:
                pg = c.connection.driver_connection
                c.exec_driver_sql(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
                )
                c.exec_driver_sql(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
                )
