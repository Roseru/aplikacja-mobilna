"""Real atomic lifecycle seeds and source transaction/qualification evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from calorie_app.modules.analytics.motivation import repository as motivation_repository
from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection
from tests.integration.test_e8_4_migration import snapshot
from tests.integration.test_e8_goal_history import seed_goal_axis
from tests.support.e8_3_jwt import ISSUER
from tests.support.e8_4_postgres import (
    accept,
    activate,
    challenge,
    clock,
    complete_day,
    fresh_database,
    goal_payload,
    invite,
    meal_payload,
    operation,
    projection_rows,
    push,
    push_response,
    runtime,
)
from tests.support.e8_4_postgres import e8_4_services as e8_4_services

pytestmark = pytest.mark.integration


@pytest.fixture
def live():
    with runtime() as rt:
        activate(rt)
        yield rt


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def day_fact(rt, identifier, day, role="inviter"):
    return next(
        row
        for row in projection_rows(rt, identifier)
        if row["participant_role"] == role and row["local_date"] == day
    )


@pytest.mark.parametrize("days", [7, 30, 90])
@pytest.mark.parametrize(
    "now", [datetime(2026, 3, 28, 12, tzinfo=UTC), datetime(2026, 10, 24, 12, tzinfo=UTC)]
)
def test_real_seed_all_dates_both_roles_preserves_calendar_boundaries(days, now):
    with runtime(now=now, zone="Europe/Warsaw") as rt:
        activate(rt)
        metadata = challenge(rt, days=days, zone="Europe/Warsaw")
        rows = projection_rows(rt, metadata["id"])
        start = date.fromisoformat(metadata["start_date"])
        assert len(rows) == days * 2
        assert {row["participant_role"] for row in rows} == {"inviter", "invitee"}
        zone = ZoneInfo("Europe/Warsaw")
        for role in ("inviter", "invitee"):
            actual = [row for row in rows if row["participant_role"] == role]
            assert [row["local_date"] for row in actual] == [
                start + timedelta(days=i) for i in range(days)
            ]
            for row in actual:
                expected_start = datetime.combine(
                    row["local_date"], datetime.min.time(), zone
                ).astimezone(UTC)
                expected_end = datetime.combine(
                    row["local_date"] + timedelta(days=1), datetime.min.time(), zone
                ).astimezone(UTC)
                assert (row["starts_at"], row["matures_at"]) == (expected_start, expected_end)
        durations = {
            (row["matures_at"].astimezone(UTC) - row["starts_at"].astimezone(UTC)).total_seconds()
            / 3600
            for row in rows
        }
        assert 23 in durations if now.month == 3 else 25 in durations
        assert instant(metadata["deadline"]) == instant(metadata["end_at"]) + timedelta(hours=720)


def test_skipped_accepted_civil_date_is_rejected_without_any_seed():
    with runtime(now=datetime(2011, 12, 28, 12, tzinfo=UTC), zone="Pacific/Apia") as rt:
        activate(rt)
        invitation, terms = invite(rt, zone="Pacific/Apia")
        response = accept(rt, invitation, terms)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "period_calendar_date_unavailable"
        assert projection_rows(rt, invitation["id"]) == []


def test_future_source_seed_is_real_and_accept_replay_does_not_seed_twice(live):
    rt = live
    start = rt["now"].date() + timedelta(days=1)
    complete_day(rt, "a", start, "100")
    complete_day(rt, "b", start, "200")
    invitation, terms = invite(rt, metrics=True)
    key = uuid4()
    accepted = accept(rt, invitation, terms, key=key)
    assert accepted.status_code == 200, accepted.text
    rows = projection_rows(rt, invitation["id"])
    for role, energy in (("inviter", 100), ("invitee", 200)):
        fact = day_fact(rt, invitation["id"], start, role)
        assert fact["candidate_points"] == 1 and fact["effective_complete"]
        assert fact["intake_kcal"] == energy
        assert fact["matures_at"] > fact["qualified_at"]
    replay = accept(rt, invitation, terms, key=key)
    assert replay.status_code == 200 and replay.json() == accepted.json()
    assert projection_rows(rt, invitation["id"]) == rows
    with rt["admin"].connect() as connection:
        receipt = connection.scalar(
            text("SELECT response FROM app.nemesis_receipts WHERE operation='accept' AND key=:key"),
            {"key": key},
        )
        assert "self" not in receipt and "opponent" not in receipt and "aggregates" not in receipt


def test_second_participant_seed_failure_rolls_both_sides_slots_and_receipt_back(live):
    rt = live
    start = rt["now"].date() + timedelta(days=1)
    complete_day(rt, "a", start, "100")
    complete_day(rt, "b", start, "200")
    invitation, terms = invite(rt)
    with rt["migrator"].begin() as connection:
        connection.exec_driver_sql("""
        CREATE FUNCTION app.e8_4_test_fail_second_seed() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic second participant seed failure'; END $$;
        CREATE TRIGGER e8_4_second_seed BEFORE UPDATE OF candidate_points
          ON app.nemesis_day_projections FOR EACH ROW
          WHEN(NEW.participant_role='invitee' AND NEW.candidate_points=1)
          EXECUTE FUNCTION app.e8_4_test_fail_second_seed();
        """)
    before = snapshot(rt["admin"])
    key = uuid4()
    try:
        response = accept(rt, invitation, terms, key=key)
        assert response.status_code == 503, response.text
        assert snapshot(rt["admin"]) == before
        assert projection_rows(rt, invitation["id"]) == []
    finally:
        with rt["migrator"].begin() as connection:
            connection.exec_driver_sql(
                "DROP TRIGGER e8_4_second_seed ON app.nemesis_day_projections"
            )
            connection.exec_driver_sql("DROP FUNCTION app.e8_4_test_fail_second_seed()")
    assert accept(rt, invitation, terms, key=key).status_code == 200


def test_raw_api_accept_runs_production_initializer_for_all_dates(live):
    rt = live
    invitation, terms = invite(rt, days=30)
    with rt["api"].begin() as connection:
        result = connection.scalar(
            text(
                "SELECT app.e8n_execute(:issuer,:subject,:epoch,'accept',"
                ":key,:hash,CAST(:payload AS jsonb))"
            ),
            {
                "issuer": ISSUER,
                "subject": rt["actors"]["b"]["subject"],
                "epoch": rt["epoch"],
                "key": uuid4(),
                "hash": "4" * 64,
                "payload": json.dumps(
                    {
                        "challenge_id": invitation["id"],
                        "revision": invitation["revision"],
                        "terms": terms,
                    }
                ),
            },
        )
        assert result["ok"], result
    assert len(projection_rows(rt, invitation["id"])) == 60


@pytest.mark.parametrize(
    "energy,expected", [("1800", 2), ("2200", 2), ("1799.999999", 1), ("2200.000001", 1)]
)
def test_projection_uses_same_inclusive_historical_goal_band(live, energy, expected):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    assert (
        push(rt, "a", operation(rt, "goal", payload=goal_payload(start, "2000")))["status"]
        == "accepted"
    )
    complete_day(rt, "a", start, energy)
    fact = day_fact(rt, metadata["id"], start)
    assert fact["candidate_points"] == expected and fact["in_goal"] is (expected == 2)


@pytest.mark.parametrize("offset,expected", [(-1, 1), (0, 1), (1, 0)])
def test_one_actual_db_q_before_on_after_deadline_controls_projection(
    live, monkeypatch, offset, expected
):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    qualification = instant(metadata["deadline"]) + timedelta(microseconds=offset)
    clock(rt, qualification)
    captured, real_apply = [], NemesisSourceProjection.apply

    def checked(self, session, context):
        real_apply(self, session, context)
        captured.append(context.qualified_at)

    monkeypatch.setattr(NemesisSourceProjection, "apply", checked)
    complete_day(rt, "a", start, "100")
    assert captured == [qualification, qualification]
    fact = day_fact(rt, metadata["id"], start)
    assert fact["candidate_points"] == expected
    if expected:
        assert fact["qualified_at"] == qualification
    else:
        assert fact["qualified_at"] == instant(metadata["accepted_at"])
    with rt["admin"].connect() as connection:
        assert (
            connection.scalar(
                text("SELECT total_points FROM app.motivation_accounts WHERE owner_id=:owner"),
                {"owner": rt["actors"]["a"]["owner"]},
            )
            == 1
        )


@pytest.mark.parametrize("failure", ["application", "unknown_sql"])
def test_apply_failure_rolls_source_projection_change_counter_and_receipt_back(
    live, monkeypatch, failure
):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    before, real_apply = snapshot(rt["admin"]), NemesisSourceProjection.apply

    def failed(self, session, context):
        real_apply(self, session, context)
        if failure == "unknown_sql":
            session.execute(
                text(
                    "DO $$ BEGIN RAISE EXCEPTION 'unknown projection failure' "
                    "USING ERRCODE='23514'; END $$"
                )
            )
        raise RuntimeError("synthetic apply failure")

    monkeypatch.setattr(NemesisSourceProjection, "apply", failed)
    response = push_response(rt, "a", [operation(rt, "meal", payload=meal_payload(start, "100"))])
    assert response.status_code == (500 if failure == "application" else 503), response.text
    assert snapshot(rt["admin"]) == before


def test_projection_source_replay_does_not_call_orchestrator_or_hook_twice(live, monkeypatch):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    calls, real_apply = [], NemesisSourceProjection.apply

    def observed(self, session, context):
        real_apply(self, session, context)
        calls.append(context.qualified_at)

    monkeypatch.setattr(NemesisSourceProjection, "apply", observed)
    op = operation(rt, "meal", payload=meal_payload(start, "100"))
    assert push(rt, "a", op)["status"] == "accepted"
    before = projection_rows(rt, metadata["id"])
    assert push(rt, "a", op)["status"] == "already_applied"
    assert len(calls) == 1
    assert projection_rows(rt, metadata["id"]) == before


def test_qualification_before_deadline_commits_after_deadline_without_losing_candidate(
    live, monkeypatch
):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    meal, declaration = complete_day(rt, "a", start, "100")
    before_deadline = instant(metadata["deadline"]) - timedelta(microseconds=1)
    clock(rt, before_deadline)
    entered, release, captured = Event(), Event(), []
    real_apply = NemesisSourceProjection.apply

    def held(self, session, context):
        real_apply(self, session, context)
        captured.append(context.qualified_at)
        entered.set()
        assert release.wait(12)

    monkeypatch.setattr(NemesisSourceProjection, "apply", held)
    correction = operation(
        rt,
        "diary_day",
        entity=UUID(declaration["entity_id"]),
        base=declaration["base_revision"] + 1,
        payload=declaration["payload"] | {"declared_complete": False},
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(push, rt, "a", correction)
        assert entered.wait(8)
        try:
            clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
        finally:
            release.set()
        assert pending.result(timeout=15)["status"] == "accepted"
    fact = day_fact(rt, metadata["id"], start)
    assert fact["candidate_points"] == 0 and not fact["effective_complete"]
    assert fact["qualified_at"] == before_deadline and captured == [before_deadline]


@pytest.mark.parametrize("sqlstate", ["40001", "40P01"])
def test_source_transaction_retry_requalifies_after_deadline_and_never_reuses_old_q(
    live, monkeypatch, sqlstate
):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    _, declaration = complete_day(rt, "a", start, "100")
    before = instant(metadata["deadline"]) - timedelta(microseconds=1)
    after = instant(metadata["deadline"]) + timedelta(microseconds=1)
    clock(rt, before)
    captured, real_apply = [], NemesisSourceProjection.apply

    def first_fails(self, session, context):
        real_apply(self, session, context)
        captured.append((context.qualified_at, session.scalar(text("SELECT txid_current()"))))
        if len(captured) == 1:
            clock(rt, after)
            session.execute(
                text(
                    "DO $$ BEGIN RAISE EXCEPTION 'synthetic restartable failure' "
                    f"USING ERRCODE='{sqlstate}'; END $$"
                )
            )

    monkeypatch.setattr(NemesisSourceProjection, "apply", first_fails)
    correction = operation(
        rt,
        "diary_day",
        entity=UUID(declaration["entity_id"]),
        base=declaration["base_revision"] + 1,
        payload=declaration["payload"] | {"declared_complete": False},
    )
    assert push(rt, "a", correction)["status"] == "accepted"
    assert [q for q, _ in captured] == [before, after]
    assert captured[0][1] != captured[1][1]
    fact = day_fact(rt, metadata["id"], start)
    assert fact["candidate_points"] == 1 and fact["effective_complete"]
    with rt["admin"].connect() as connection:
        assert (
            connection.scalar(
                text("SELECT declared_complete FROM app.diary_days WHERE id=:id"),
                {"id": declaration["entity_id"]},
            )
            is False
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.sync_receipts WHERE operation_id=:operation"),
                {"operation": correction["operation_id"]},
            )
            == 1
        )


def test_complete_goal_axis_over10000_versions_is_used_by_actual_sync_orchestrator(live):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    seed_goal_axis(rt["migrator"], rt["actors"]["a"]["owner"], 10001)
    complete_day(rt, "a", start, "100")
    assert day_fact(rt, metadata["id"], start)["candidate_points"] == 2
    op = operation(rt, "goal", payload=goal_payload(start, "200", timeline_revision=10001))
    assert push(rt, "a", op)["status"] == "accepted"
    assert day_fact(rt, metadata["id"], start)["candidate_points"] == 1
    with rt["admin"].connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.goal_versions WHERE owner_id=:owner"),
                {"owner": rt["actors"]["a"]["owner"]},
            )
            == 10002
        )


@pytest.mark.parametrize(
    "forgery", ["qualified_at", "smaller_lockset", "wrong_position", "committed_source"]
)
def test_raw_source_orchestrator_refuses_caller_clock_and_inexact_discovery(
    live, monkeypatch, forgery
):
    rt = live
    metadata = challenge(rt)
    start = date.fromisoformat(metadata["start_date"])
    captured, real_apply = [], NemesisSourceProjection.apply

    def capture(self, session, context):
        real_apply(self, session, context)
        captured.append((context, self.plan))

    monkeypatch.setattr(NemesisSourceProjection, "apply", capture)
    assert (
        push(rt, "a", operation(rt, "meal", payload=meal_payload(start, "100")))["status"]
        == "accepted"
    )
    context, plan = captured[0]
    source = asdict(context)
    source.pop("qualified_at")
    source = json.loads(json.dumps(source, default=str))
    ids = [row.id for row in plan.challenges]
    if forgery == "qualified_at":
        source["qualified_at"] = rt["now"].isoformat()
    elif forgery == "smaller_lockset":
        ids = []
    elif forgery == "wrong_position":
        source["source_position"] -= 1
    before = snapshot(rt["admin"])
    with pytest.raises(DBAPIError) as rejected, rt["api"].begin() as connection:
        connection.execute(
            text(
                "SELECT app.e8n_source_refresh(:owner,1,:epoch,"
                "CAST(:source AS jsonb),CAST(:ids AS uuid[]))"
            ),
            {
                "owner": context.owner_id,
                "epoch": rt["epoch"],
                "source": json.dumps(source),
                "ids": ids,
            },
        )
    assert rejected.value.orig.sqlstate == "23514"
    assert snapshot(rt["admin"]) == before


def test_old_and_new_challenges_use_one_q_against_their_own_deadlines(live, monkeypatch):
    rt = live
    first = challenge(rt)
    start = date.fromisoformat(first["start_date"])
    complete_day(rt, "a", start, "100")
    clock(rt, instant(first["end_at"]))
    second = challenge(rt, receiver="c")
    old = projection_rows(rt, first["id"])
    qualification = instant(first["deadline"]) + timedelta(microseconds=1)
    assert qualification < instant(second["deadline"])
    clock(rt, qualification)
    captured, real_apply = [], NemesisSourceProjection.apply

    def capture(self, session, context):
        real_apply(self, session, context)
        captured.append((context.qualified_at, [row.id for row in self.plan.challenges]))

    monkeypatch.setattr(NemesisSourceProjection, "apply", capture)
    assert push(rt, "a", operation(rt, "weight"))["status"] == "accepted"
    assert captured == [(qualification, sorted([UUID(first["id"]), UUID(second["id"])]))]
    assert projection_rows(rt, first["id"]) == old
    assert all(
        row["qualified_at"] == qualification
        for row in projection_rows(rt, second["id"])
        if row["participant_role"] == "inviter"
    )


def test_actual_visible_source_xmin_survives_savepoint_release_but_not_commit_or_rollback():
    with fresh_database("0021_e8_nemesis_results") as private:
        engine = private.engine()
        try:
            with engine.connect() as connection:
                connection.execute(text("CREATE TEMP TABLE e8_4_xmin_probe(v integer)"))
                connection.commit()
                connection.execute(text("INSERT INTO e8_4_xmin_probe VALUES(1)"))
                assert connection.scalar(
                    text(
                        "SELECT app.e8n_source_in_transaction(xmin) FROM e8_4_xmin_probe WHERE v=1"
                    )
                )
                with connection.begin_nested():
                    released_xmin = connection.scalar(
                        text("INSERT INTO e8_4_xmin_probe VALUES(2) RETURNING xmin::text")
                    )
                    assert connection.scalar(
                        text(
                            "SELECT app.e8n_source_in_transaction(xmin) "
                            "FROM e8_4_xmin_probe WHERE v=2"
                        )
                    )
                assert connection.scalar(
                    text("SELECT app.e8n_source_in_transaction(CAST(:xmin AS xid))"),
                    {"xmin": released_xmin},
                )
                with pytest.raises(RuntimeError), connection.begin_nested():
                    rolled_back_xmin = connection.scalar(
                        text("INSERT INTO e8_4_xmin_probe VALUES(3) RETURNING xmin::text")
                    )
                    raise RuntimeError("synthetic savepoint rollback")
                assert not connection.scalar(
                    text("SELECT app.e8n_source_in_transaction(CAST(:xmin AS xid))"),
                    {"xmin": rolled_back_xmin},
                )
                connection.commit()
                assert not connection.scalar(
                    text("SELECT app.e8n_source_in_transaction(CAST(:xmin AS xid))"),
                    {"xmin": released_xmin},
                )
        finally:
            engine.dispose()


def test_db_orchestrator_calls_general_refresh_exactly_once_per_real_source(live, monkeypatch):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    with rt["migrator"].begin() as connection:
        connection.exec_driver_sql("""
        CREATE TABLE app.e8_4_refresh_calls(n integer NOT NULL);
        INSERT INTO app.e8_4_refresh_calls VALUES(0);
        REVOKE ALL ON app.e8_4_refresh_calls FROM PUBLIC,calorie_app_api,calorie_app_worker;
        ALTER FUNCTION app.e8_refresh(uuid,date[],integer) RENAME TO e8_4_original_refresh;
        CREATE FUNCTION app.e8_refresh(
          p_owner uuid,p_dates date[] DEFAULT NULL,p_batch integer DEFAULT 256)
        RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,pg_temp AS $$ DECLARE q timestamptz;
        BEGIN
          UPDATE app.e8_4_refresh_calls SET n=n+1;
          q:=app.e8_4_original_refresh(p_owner,p_dates,p_batch);
          RETURN q;
        END $$;
        REVOKE ALL ON FUNCTION app.e8_refresh(uuid,date[],integer) FROM PUBLIC;
        """)

    def forbidden_plain(*args, **kwargs):
        raise AssertionError("plain Python refresh must not run alongside the DB orchestrator")

    monkeypatch.setattr(motivation_repository, "refresh", forbidden_plain)
    source, _ = complete_day(rt, "a", day, "100")
    with rt["admin"].connect() as connection:
        assert connection.scalar(text("SELECT n FROM app.e8_4_refresh_calls")) == 2
    assert push(rt, "a", source)["status"] == "already_applied"
    with rt["admin"].connect() as connection:
        assert connection.scalar(text("SELECT n FROM app.e8_4_refresh_calls")) == 2


def test_broken_required_projector_never_acknowledges_source_or_creates_receipt(live):
    rt = live
    metadata = challenge(rt)
    day = date.fromisoformat(metadata["start_date"])
    with rt["migrator"].begin() as connection:
        connection.execute(
            text("DELETE FROM app.nemesis_projection_seeds WHERE challenge_id=:id"),
            {"id": metadata["id"]},
        )
    before = snapshot(rt["admin"])
    response = push_response(rt, "a", [operation(rt, "meal", payload=meal_payload(day, "100"))])
    assert response.status_code == 503 and "results" not in response.json()
    assert snapshot(rt["admin"]) == before
