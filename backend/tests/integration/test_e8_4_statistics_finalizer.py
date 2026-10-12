"""Private metric wire and projection-only finalization on actual PostgreSQL."""

import json
import os
import subprocess
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, timedelta
from threading import Barrier, Event
from time import monotonic
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection
from tests.integration.test_e8_4_projections import day_fact, instant
from tests.support.e8_4_postgres import (
    activate,
    challenge,
    clock,
    complete_day,
    example,
    finalize,
    goal_payload,
    headers,
    operation,
    projection_rows,
    push,
    push_response,
    runtime,
    statistics,
    wait_for_blocker,
)
from tests.support.e8_4_postgres import e8_4_services as e8_4_services

pytestmark = pytest.mark.integration


@pytest.fixture
def live():
    with runtime() as rt:
        activate(rt)
        yield rt


def ready(rt, metadata, actor="a"):
    response = statistics(rt, metadata["id"], actor)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] in {"provisional", "final"}
    return result


def test_pending_has_no_fake_points_then_matures_without_client_or_general_worker(live):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    complete_day(rt, "a", day, "100")
    pending = statistics(rt, metadata["id"])
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"
    assert not {"self", "opponent", "outcome"}.intersection(pending.json())
    clock(rt, day_fact(rt, metadata["id"], day)["matures_at"])
    result = ready(rt, metadata)
    assert result["self"]["regularity"] == {
        "points": 1,
        "closed_days": 1,
        "complete_days": 1,
        "days_in_goal": 0,
    }
    assert result["opponent"]["regularity"]["points"] == 0
    assert result["outcome"] == "self_wins"
    assert ready(rt, metadata, "b")["outcome"] == "opponent_wins"
    for side in ("self", "opponent"):
        assert result[side]["weight_change"] == {"state": "hidden"}
        assert result[side]["mean_deficit"] == {"state": "hidden"}
    with rt["admin"].connect() as connection:
        assert (
            connection.scalar(
                text("SELECT total_points FROM app.motivation_accounts WHERE owner_id=:id"),
                {"id": rt["actors"]["a"]["owner"]},
            )
            == 0
        )


def test_daily_signed_deficit_mean_uses_historical_E_and_is_not_ratio_of_sums(live):
    rt = live
    metadata = challenge(rt, metrics=True)
    first = date.fromisoformat(metadata["start_date"])
    second = first + timedelta(days=1)
    for day, intake, maintenance, revision in (
        (first, "2001.6", "2502", 0),
        (second, "3001.5", "2001", 1),
    ):
        goal = operation(
            rt,
            "goal",
            payload=goal_payload(day, "5000", maintenance=maintenance, timeline_revision=revision),
        )
        assert push(rt, "a", goal)["status"] == "accepted"
        complete_day(rt, "a", day, intake)
    clock(rt, day_fact(rt, metadata["id"], second)["matures_at"])
    result = ready(rt, metadata)
    assert result["self"]["mean_deficit"] == {
        "state": "available",
        "value": "-15",
        "eligible_days": 2,
    }
    assert result["self"]["regularity"]["points"] == 2
    assert result["opponent"]["mean_deficit"] == {
        "state": "insufficient_data",
        "value": None,
        "eligible_days": 0,
    }
    assert result["self"]["weight_change"] == {
        "state": "insufficient_data",
        "value": None,
        "observed_days": 0,
    }
    # No source values, bindings or revision graphs may cross the partner wire.
    partner = statistics(rt, metadata["id"], "b")
    wire = partner.text
    for field in ("intake_kcal", "maintenance_kcal", "source_revisions"):
        assert field not in wire

    def scalars(value):
        if isinstance(value, dict):
            for member in value.values():
                yield from scalars(member)
        elif isinstance(value, list):
            for member in value:
                yield from scalars(member)
        else:
            yield str(value)

    # Digits occurring inside the shared random challenge UUID are public ID
    # text. Compare complete scalar values, including numeric JSON values.
    private_values = {"2502", "2001.6", "3001.5", "5000", str(rt["actors"]["a"]["owner"])}
    assert private_values.isdisjoint(scalars(partner.json()))


def test_zero_is_available_but_missing_E_and_empty_days_are_insufficient(live):
    rt = live
    metadata = challenge(rt, metrics=True)
    first = date.fromisoformat(metadata["start_date"])
    goal = operation(rt, "goal", payload=goal_payload(first, "2502", maintenance="2502"))
    assert push(rt, "a", goal)["status"] == "accepted"
    complete_day(rt, "a", first, "2502")
    complete_day(rt, "b", first, "100")
    clock(rt, instant(metadata["end_at"]))
    result = ready(rt, metadata)
    assert result["self"]["mean_deficit"] == {
        "state": "available",
        "value": "0",
        "eligible_days": 1,
    }
    assert result["self"]["regularity"] == {
        "points": 2,
        "closed_days": 7,
        "complete_days": 1,
        "days_in_goal": 1,
    }
    assert result["opponent"]["regularity"]["points"] == 1
    assert result["opponent"]["mean_deficit"] == {
        "state": "insufficient_data",
        "value": None,
        "eligible_days": 0,
    }


def test_weight_representative_uses_latest_instant_then_uuid_and_counts_dates(live):
    rt = live
    metadata = challenge(rt, metrics=True)
    first = date.fromisoformat(metadata["start_date"])
    second = first + timedelta(days=1)
    source = {}
    values = [
        ("10000000-0000-4000-8000-000000000001", first, "100", 1),
        ("10000000-0000-4000-8000-000000000002", first, "90", 1),
        ("10000000-0000-4000-8000-000000000003", second, "99", 1),
        ("10000000-0000-4000-8000-000000000000", first, "110", 1),
    ]
    for identifier, day, weight, hour in values:
        timestamp = day_fact(rt, metadata["id"], day)["starts_at"].astimezone(UTC) + timedelta(
            hours=hour
        )
        payload = example("weight") | {
            "occurred_at": timestamp.isoformat().replace("+00:00", "Z"),
            "local_date": day.isoformat(),
            "time_zone": "UTC",
            "weight_kg": weight,
        }
        op = operation(rt, "weight", entity=UUID(identifier), payload=payload)
        assert push(rt, "a", op)["status"] == "accepted"
        source[identifier] = op
    clock(rt, instant(metadata["end_at"]))
    metric = ready(rt, metadata)["self"]["weight_change"]
    assert metric["value"] == "10" and metric["observed_days"] == 2
    identifier = "10000000-0000-4000-8000-000000000000"
    timestamp = day_fact(rt, metadata["id"], first)["starts_at"].astimezone(UTC) + timedelta(
        hours=2
    )
    correction = operation(
        rt,
        "weight",
        entity=UUID(identifier),
        base=1,
        payload=source[identifier]["payload"]
        | {"weight_kg": "100", "occurred_at": timestamp.isoformat().replace("+00:00", "Z")},
    )
    assert push(rt, "a", correction)["status"] == "accepted"
    metric = ready(rt, metadata)["self"]["weight_change"]
    assert metric["value"] == "-1" and metric["observed_days"] == 2
    assert (
        push(rt, "a", operation(rt, "weight", entity=UUID(identifier), base=2, action="delete"))[
            "status"
        ]
        == "accepted"
    )
    metric = ready(rt, metadata)["self"]["weight_change"]
    assert metric["value"] == "10" and metric["observed_days"] == 2


def test_percentage_wire_has_no_arbitrary_six_digit_integer_limit(live):
    rt = live
    metadata = challenge(rt, metrics=True)
    first = date.fromisoformat(metadata["start_date"])
    for day, weight in ((first, "0.000001"), (first + timedelta(days=1), "1000")):
        timestamp = day_fact(rt, metadata["id"], day)["starts_at"].astimezone(UTC) + timedelta(
            hours=1
        )
        payload = example("weight") | {
            "occurred_at": timestamp.isoformat().replace("+00:00", "Z"),
            "local_date": day.isoformat(),
            "time_zone": "UTC",
            "weight_kg": weight,
        }
        assert push(rt, "a", operation(rt, "weight", payload=payload))["status"] == "accepted"
    clock(rt, instant(metadata["end_at"]))
    metric = ready(rt, metadata)["self"]["weight_change"]
    assert metric["value"] == "99999999900" and metric["observed_days"] == 2


def test_warsaw_weight_only_maturity_survives_profile_zone_change_and_moved_observation():
    with runtime(zone="Europe/Warsaw") as rt:
        activate(rt)
        metadata = challenge(rt, zone="Europe/Warsaw", metrics=True)
        first = date.fromisoformat(metadata["start_date"])
        second = first + timedelta(days=1)
        ids = [
            UUID("10000000-0000-4000-8000-000000000001"),
            UUID("10000000-0000-4000-8000-000000000002"),
        ]
        operations = []
        for index, (day, weight) in enumerate(((first, "100"), (second, "90"))):
            occurred = day_fact(rt, metadata["id"], day)["starts_at"] + timedelta(hours=1)
            payload = example("weight") | {
                "occurred_at": occurred.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "local_date": (day - timedelta(days=1)).isoformat(),
                "time_zone": "Pacific/Honolulu",
                "weight_kg": weight,
            }
            op = operation(rt, "weight", entity=ids[index], payload=payload)
            assert push(rt, "a", op)["status"] == "accepted"
            operations.append(op)
        # Sources have different dates/zones; the accepted boundary owns maturity.
        clock(rt, instant(metadata["end_at"]))
        old_boundaries = [
            (row["starts_at"], row["matures_at"]) for row in projection_rows(rt, metadata["id"])
        ]
        profile = operation(
            rt,
            "profile",
            entity=rt["actors"]["a"]["profile"],
            base=1,
            payload=example("profile") | {"time_zone": "America/New_York"},
        )
        assert push(rt, "a", profile)["status"] == "accepted"
        result = ready(rt, metadata)
        assert result["self"]["weight_change"] == {
            "state": "available",
            "value": "-10",
            "observed_days": 2,
            "first_date": first.isoformat(),
            "last_date": second.isoformat(),
        }
        assert result["self"]["regularity"]["points"] == 0
        assert [
            (row["starts_at"], row["matures_at"]) for row in projection_rows(rt, metadata["id"])
        ] == old_boundaries
        moved_at = instant(metadata["end_at"]) + timedelta(hours=1)
        moved = operation(
            rt,
            "weight",
            entity=ids[0],
            base=1,
            payload=operations[0]["payload"]
            | {
                "occurred_at": moved_at.isoformat().replace("+00:00", "Z"),
                "local_date": (
                    date.fromisoformat(metadata["end_date"]) - timedelta(days=1)
                ).isoformat(),
            },
        )
        assert push(rt, "a", moved)["status"] == "accepted"
        assert ready(rt, metadata)["self"]["weight_change"] == {
            "state": "insufficient_data",
            "value": None,
            "observed_days": 1,
        }
        deleted = operation(rt, "weight", entity=ids[1], base=1, action="delete")
        assert push(rt, "a", deleted)["status"] == "accepted"
        assert ready(rt, metadata)["self"]["weight_change"]["observed_days"] == 0


def test_finalizer_only_after_deadline_ignores_late_poison_and_is_retry_safe(live):
    rt = live
    metadata = challenge(rt, metrics=True)
    day = date.fromisoformat(metadata["start_date"])
    meal, _ = complete_day(rt, "a", day, "100")
    clock(rt, instant(metadata["deadline"]))
    finalize(rt, metadata["id"])
    assert ready(rt, metadata)["status"] == "provisional"
    before = projection_rows(rt, metadata["id"])
    clock(rt, instant(metadata["deadline"]) + timedelta(microseconds=1))
    poison = operation(rt, "meal", entity=UUID(meal["entity_id"]), base=1, action="delete")
    assert push(rt, "a", poison)["status"] == "accepted"
    assert projection_rows(rt, metadata["id"]) == before
    finalize(rt, metadata["id"])
    final = ready(rt, metadata)
    assert final["status"] == "final" and final["self"]["regularity"]["points"] == 1
    assert "finalized_at" in final
    finalize(rt, metadata["id"])
    assert ready(rt, metadata) == final


def test_accepted_instants_survive_resolver_drift_and_final_cannot_revert(live):
    rt = live
    metadata = challenge(rt)
    fields = ("accepted_at", "start_date", "end_date", "start_at", "end_at", "deadline")
    original = {name: metadata[name] for name in fields}
    with rt["migrator"].begin() as connection:
        connection.exec_driver_sql("""
        ALTER FUNCTION app.e8n_boundary(date,text) RENAME TO e8_4_original_boundary;
        CREATE FUNCTION app.e8n_boundary(d date,z text) RETURNS timestamptz
        LANGUAGE sql STABLE SET search_path=pg_catalog,pg_temp AS $$
          SELECT app.e8_4_original_boundary(d,z)+interval '1 hour'
        $$;
        REVOKE ALL ON FUNCTION app.e8n_boundary(date,text) FROM PUBLIC;
        """)
    clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
    finalize(rt, metadata["id"])
    assert ready(rt, metadata)["status"] == "final"
    current = rt["client"].get("/api/v1/nemesis/" + metadata["id"], headers=headers(rt)).json()
    assert {name: current[name] for name in fields} == original
    with pytest.raises(DBAPIError) as denied, rt["migrator"].begin() as connection:
        connection.execute(
            text(
                "UPDATE app.nemesis_challenges SET result_status='provisional',"
                "revision=revision+1 WHERE id=:id"
            ),
            {"id": metadata["id"]},
        )
    assert denied.value.orig.sqlstate == "23514"
    cancelled = rt["client"].post(
        "/api/v1/nemesis/" + metadata["id"] + "/cancel",
        headers=headers(rt, revision=current["revision"]),
        json={"reason": "sharing_revoked"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert {name: cancelled.json()[name] for name in fields} == original


def test_projection_only_finalizer_succeeds_with_physical_source_and_account_locks(live):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    complete_day(rt, "a", day, "100")
    clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
    tables = (
        "meals",
        "meal_items",
        "diary_days",
        "weights",
        "goal_versions",
        "goal_timelines",
        "user_profiles",
        "motivation_days",
        "motivation_accounts",
    )
    with rt["admin"].begin() as blocker:
        positions = list(
            blocker.execute(
                text("SELECT owner_id,position FROM app.sync_counters ORDER BY owner_id")
            )
        )
        blocker.exec_driver_sql(
            "LOCK TABLE " + ",".join("app." + name for name in tables) + " IN ACCESS EXCLUSIVE MODE"
        )
        blocker.execute(text("SELECT 1 FROM app.user_accounts ORDER BY id FOR UPDATE"))
        blocker.execute(text("SELECT 1 FROM app.sync_counters ORDER BY owner_id FOR UPDATE"))
        with rt["finalizer"].begin() as connection:
            connection.exec_driver_sql("SET LOCAL statement_timeout='3s'")
            connection.execute(text("SELECT app.e8n_finalize(:id)"), {"id": metadata["id"]})
        assert (
            list(
                blocker.execute(
                    text("SELECT owner_id,position FROM app.sync_counters ORDER BY owner_id")
                )
            )
            == positions
        )
    assert ready(rt, metadata)["status"] == "final"
    assert ready(rt, metadata)["self"]["regularity"]["points"] == 1


def test_two_finalizer_connections_and_rollback_then_restart_commit_once(live):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    complete_day(rt, "a", day, "100")
    clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
    with pytest.raises(RuntimeError), rt["finalizer"].begin() as connection:
        connection.execute(text("SELECT app.e8n_finalize(:id)"), {"id": metadata["id"]})
        raise RuntimeError("crash before COMMIT")
    assert ready(rt, metadata)["status"] == "provisional"
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=8)
        return finalize(rt, metadata["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run(), range(2)))
    result = ready(rt, metadata)
    assert result["status"] == "final"
    with rt["admin"].connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.nemesis_final_results WHERE challenge_id=:id"),
                {"id": metadata["id"]},
            )
            == 2
        )


@pytest.mark.parametrize("final", [False, True])
def test_cancel_after_provisional_or_final_revokes_read_and_304_cannot_restore_access(live, final):
    rt = live
    metadata = challenge(rt)
    clock(rt, instant(metadata["end_at"]))
    if final:
        clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
        finalize(rt, metadata["id"])
    assert statistics(rt, metadata["id"], "c").status_code == 404
    rt["actors"]["c"]["headers"] = {
        "Authorization": "Bearer "
        + rt["signed"].token(rt["actors"]["c"]["subject"], roles=("user", "admin", "moderator"))
    }
    assert statistics(rt, metadata["id"], "c").status_code == 404
    observed = ready(rt, metadata)
    current = rt["client"].get("/api/v1/nemesis/" + metadata["id"], headers=headers(rt)).json()
    cancelled = rt["client"].post(
        "/api/v1/nemesis/" + metadata["id"] + "/cancel",
        headers=headers(rt, revision=current["revision"]),
        json={"reason": "sharing_revoked"},
    )
    assert cancelled.status_code == 200, cancelled.text
    for actor in ("a", "b"):
        response = statistics(
            rt,
            metadata["id"],
            actor,
            extra_headers={"If-None-Match": '"' + str(observed["revision"]) + '"'},
        )
        assert response.status_code == 404 and response.json()["code"] == "nemesis_not_found"
    with rt["api"].begin() as connection:
        response = connection.scalar(
            text("SELECT app.e8n_statistics(:issuer,:sub,:epoch,:id)"),
            {
                "issuer": "https://nemesis-identity.example.test/realm",
                "sub": rt["actors"]["b"]["subject"],
                "epoch": rt["epoch"],
                "id": metadata["id"],
            },
        )
        assert response["http_status"] == 404


@pytest.mark.parametrize("commit", [True, False])
def test_finalizer_waits_for_earlier_qualified_source_commit_or_rollback(live, monkeypatch, commit):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    _, declaration = complete_day(rt, "a", day, "100")
    clock(rt, instant(metadata["deadline"]) - timedelta(microseconds=1))
    entered, release, captured = Event(), Event(), {}
    real_apply = NemesisSourceProjection.apply

    def hold(self, session, context):
        real_apply(self, session, context)
        captured["q"] = context.qualified_at
        captured["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert release.wait(12)
        if not commit:
            raise RuntimeError("synthetic source crash before COMMIT")

    monkeypatch.setattr(NemesisSourceProjection, "apply", hold)
    correction = operation(
        rt,
        "diary_day",
        entity=UUID(declaration["entity_id"]),
        base=declaration["base_revision"] + 1,
        payload=declaration["payload"] | {"declared_complete": False},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        source = pool.submit(push_response, rt, "a", [correction])
        assert entered.wait(8)
        clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
        finalizing = pool.submit(finalize, rt, metadata["id"])
        try:
            wait_for_blocker(rt, captured["pid"])
        finally:
            release.set()
        response = source.result(timeout=15)
        assert response.status_code == (200 if commit else 500)
        finalizing.result(timeout=15)
    final = ready(rt, metadata)
    assert final["status"] == "final"
    assert final["self"]["regularity"]["points"] == (0 if commit else 1)
    assert captured["q"] < instant(metadata["deadline"])


def test_statistics_correction_race_returns_one_revision_snapshot(live, monkeypatch):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    _, declaration = complete_day(rt, "a", day, "100")
    clock(rt, day_fact(rt, metadata["id"], day)["matures_at"])
    before = ready(rt, metadata)
    entered, release, state = Event(), Event(), {}
    real_apply = NemesisSourceProjection.apply

    def hold(self, session, context):
        real_apply(self, session, context)
        state["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert release.wait(12)

    monkeypatch.setattr(NemesisSourceProjection, "apply", hold)
    correction = operation(
        rt,
        "diary_day",
        entity=UUID(declaration["entity_id"]),
        base=declaration["base_revision"] + 1,
        payload=declaration["payload"] | {"declared_complete": False},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(push, rt, "a", correction)
        assert entered.wait(8)
        reading = pool.submit(ready, rt, metadata, "b")
        try:
            wait_for_blocker(rt, state["pid"])
        finally:
            release.set()
        assert writing.result(timeout=15)["status"] == "accepted"
        observed = reading.result(timeout=15)
    after = ready(rt, metadata, "b")
    assert observed == after
    assert observed["revision"] > before["revision"]
    assert observed["opponent"]["regularity"]["points"] == 0
    assert observed["opponent"]["regularity"]["complete_days"] == 0
    assert observed["outcome"] == "tie"


def test_missing_seed_is_unavailable_for_participants_but_404_for_other_account(live):
    rt = live
    metadata = challenge(rt)
    with rt["migrator"].begin() as connection:
        connection.execute(
            text(
                "DELETE FROM app.nemesis_day_projections WHERE challenge_id=:id "
                "AND participant_role='invitee' AND local_date=:day"
            ),
            {"id": metadata["id"], "day": metadata["start_date"]},
        )
    for actor in ("a", "b"):
        response = statistics(rt, metadata["id"], actor)
        assert (
            response.status_code == 503
            and response.json()["code"] == "nemesis_statistics_unavailable"
        )
    assert statistics(rt, metadata["id"], "c").status_code == 404


def test_unready_low_uuid_prefix_cannot_starve_real_due_finalization(live):
    rt = live
    metadata = challenge(rt)
    with rt["migrator"].begin() as connection:
        for index in range(1, 17):
            connection.execute(
                text("""
            INSERT INTO app.nemesis_challenges(id,inviter_id,invitee_id,inviter_generation,
             invitee_generation,sync_epoch,status,terms,created_at,expires_at,accepted_at,
             start_date,end_date,start_at,end_at,deadline_at,result_status)
            SELECT :id,inviter_id,invitee_id,inviter_generation,invitee_generation,sync_epoch,
             'finished',terms,created_at,expires_at,accepted_at,start_date,end_date,start_at,
             end_at,deadline_at,'provisional' FROM app.nemesis_challenges WHERE id=:source
            """),
                {"id": UUID(int=index), "source": metadata["id"]},
            )
    clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
    with rt["finalizer"].begin() as connection:
        result = connection.scalar(text("SELECT app.e8n_finalize_batch(1)"))
        assert result["processed"] == result["finalized"] == 1
    assert ready(rt, metadata)["status"] == "final"
    with rt["admin"].connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.nemesis_challenges WHERE result_status='provisional'"
                )
            )
            == 16
        )


def test_two_real_finalizer_processes_wait_then_commit_one_result(live, tmp_path, record_property):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    complete_day(rt, "a", day, "100")
    clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
    credential = tmp_path / "finalizer-private.json"
    credential.write_text(
        json.dumps({"url": rt["finalizer"].url.render_as_string(hide_password=False)}),
        encoding="utf-8",
    )
    credential.chmod(0o600)
    source = """
import json,sys
from pathlib import Path
from sqlalchemy import create_engine,text
engine=create_engine(json.loads(Path(sys.argv[1]).read_text())['url'],hide_parameters=True,
 connect_args={'application_name':'e8-4-finalizer-process'})
try:
 with engine.begin() as c:
  result=c.scalar(text('SELECT app.e8n_finalize(CAST(:id AS uuid))'),{'id':sys.argv[2]})
 print(json.dumps(result))
finally: engine.dispose()
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment["PYTHONPATH"] = (
        sysconfig.get_path("purelib") + os.pathsep + environment.get("PYTHONPATH", "")
    )
    processes = []
    try:
        with rt["admin"].begin() as blocker:
            blocker.execute(
                text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE"),
                {"id": metadata["id"]},
            )
            blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
            for _ in range(2):
                processes.append(
                    subprocess.Popen(
                        [
                            getattr(sys, "_base_executable", sys.executable),
                            "-c",
                            source,
                            str(credential),
                            metadata["id"],
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=environment,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                )
            deadline = monotonic() + 15
            while True:
                with rt["admin"].connect() as connection:
                    waiting = connection.scalar(
                        text(
                            "WITH RECURSIVE waits(pid) AS ("
                            "SELECT pid FROM pg_stat_activity "
                            "WHERE :parent=ANY(pg_blocking_pids(pid)) "
                            "UNION SELECT a.pid FROM pg_stat_activity a JOIN waits w "
                            "ON w.pid=ANY(pg_blocking_pids(a.pid))) "
                            "SELECT count(*) FROM pg_stat_activity a JOIN waits w USING(pid) "
                            "WHERE datname=current_database() "
                            "AND application_name='e8-4-finalizer-process'"
                        ),
                        {"parent": blocker_pid},
                    )
                if waiting == 2:
                    with rt["admin"].connect() as connection:
                        graph = [
                            dict(row)
                            for row in connection.execute(
                                text(
                                    "SELECT pid,pg_blocking_pids(pid) AS blockers,wait_event_type "
                                    "FROM pg_stat_activity WHERE datname=current_database() "
                                    "AND application_name='e8-4-finalizer-process' ORDER BY pid"
                                )
                            ).mappings()
                        ]
                    record_property(
                        "direct_waiters", sum(blocker_pid in row["blockers"] for row in graph)
                    )
                    record_property("transitive_waiters", waiting)
                    (tmp_path / "observed-blocking-graph.json").write_text(
                        json.dumps(graph), encoding="utf-8"
                    )
                    break
                assert monotonic() < deadline, (
                    "both owned finalizer processes did not reach actual lock wait"
                )
                Event().wait(0.01)
        results = []
        for process in processes:
            out, error = process.communicate(timeout=20)
            assert process.returncode == 0, error
            results.append(json.loads(out)["status"])
        assert sorted(results) == ["already_final", "finalized"]
        assert ready(rt, metadata)["self"]["regularity"]["points"] == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
