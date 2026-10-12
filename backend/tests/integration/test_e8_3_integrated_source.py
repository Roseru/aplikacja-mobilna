"""Integrated production sync, source guard, JWT and real transaction races.

Uses create_app unchanged, real SCRAM API/operator logins and synthetic signed
JWT/JWKS. Test-only migration fixtures prepare accepted history and may enable
fake capability solely for a direct SQL accept race. They are not E8.4 proof.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.analytics.motivation import repository as motivation_repository
from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection
from calorie_app.modules.sync.schemas import validate_wire
from tests.support.e8_3_jwt import ISSUER, SignedTokens
from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/examples/valid"
TERMS = {
    "rule_version": "regularity_v1",
    "duration_days": 7,
    "time_zone": "UTC",
    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
}
SECRET = "d3" * 32


def example(name):
    return json.loads(EXAMPLES.joinpath(name + ".json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def integrated_db():
    import os

    private = PrivatePostgres.from_environment()
    admin, api, migrator = (
        private.engine("admin"),
        private.engine("api"),
        private.engine("migrator"),
    )
    raw = json.loads(
        Path(os.environ["E8_3_PARENT_DELETION_CREDENTIALS"]).read_text(encoding="utf-8")
    )
    operator = create_engine(raw["operator_url"], hide_parameters=True)
    with admin.connect() as c:
        assert c.scalar(text("SELECT version_num FROM app.alembic_version")) == (
            "0020_e8_nemesis_integration"
        )
        assert 170000 <= int(c.scalar(text("SHOW server_version_num"))) < 180000
    for engine, role in ((api, "calorie_app_api"), (operator, "e8_3_parent_deletion_login")):
        with engine.connect() as c:
            assert c.scalar(text("SELECT current_user=session_user"))
            assert c.scalar(text("SELECT session_user")) == role
    yield admin, api, migrator, operator
    for engine in (api, admin, migrator, operator):
        engine.dispose()


@pytest.fixture
def live(integrated_db):
    admin, api, migrator, operator = integrated_db
    with admin.begin() as c:
        c.execute(text("TRUNCATE app.user_accounts CASCADE"))
        c.execute(text("UPDATE app.nemesis_control SET enabled=false"))
        c.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp "
                "AS $$ SELECT clock_timestamp() $$"
            )
        )
        epoch, now = c.execute(
            text("SELECT sync_epoch,clock_timestamp() FROM app.installation_state WHERE id=1")
        ).one()
    signed = SignedTokens()
    settings = Settings(
        database_url=api.url.render_as_string(hide_password=False),
        environment="test",
        catalog_page_token_secret=SecretStr(SECRET),
        oidc_issuer=ISSUER,
        oidc_jwks_url=ISSUER + "/certs",
        _env_file=None,
    )
    app = create_app(settings, engine=api)
    app.state.oidc_verifier = signed.verifier
    assert "/api/v1/nemesis" in app.openapi()["paths"]
    actors = {}
    with TestClient(app) as client:
        rt = {
            "admin": admin,
            "api": api,
            "migrator": migrator,
            "operator": operator,
            "client": client,
            "signed": signed,
            "epoch": epoch,
            "now": now,
            "start": now.astimezone(UTC).date() + timedelta(days=1),
            "actors": actors,
        }
        for name in ("a", "b", "c"):
            subject = str(uuid4())
            token = signed.token(subject)
            headers = {"Authorization": "Bearer " + token}
            response = client.post(
                "/api/v1/me/bootstrap", headers=headers | {"Idempotency-Key": str(uuid4())}
            )
            assert response.status_code == 200, response.text
            owner = UUID(response.json()["account_id"])
            pull = client.get("/api/v1/sync/pull", headers=headers)
            assert pull.status_code == 200, pull.text
            who = {
                "owner": owner,
                "subject": subject,
                "headers": headers,
                "checkpoint": pull.json()["checkpoint"],
                "profile": uuid4(),
            }
            actors[name] = who
            payload = example("profile") | {"time_zone": "UTC"}
            result = push(
                rt, name, operation(rt, "profile", entity=who["profile"], payload=payload)
            )
            assert result["status"] == "accepted"
        yield rt
    with admin.begin() as c:
        c.execute(text("UPDATE app.nemesis_control SET enabled=false"))
        c.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp "
                "AS $$ SELECT clock_timestamp() $$"
            )
        )
        c.execute(text("TRUNCATE app.user_accounts CASCADE"))


def operation(rt, kind, *, entity=None, base=None, payload=None, action="upsert"):
    filename = "diary-day" if kind == "diary_day" else kind.replace("_", "-")
    return {
        "operation_id": str(uuid4()),
        "entity_type": kind,
        "entity_id": str(entity or uuid4()),
        "base_revision": base,
        "sync_epoch": str(rt["epoch"]),
        "action": action,
        "payload": (payload if payload is not None else example(filename))
        if action == "upsert"
        else None,
    }


def request_body(rt, name, operations):
    return {
        "protocol_version": 1,
        "sync_epoch": str(rt["epoch"]),
        "checkpoint": rt["actors"][name]["checkpoint"],
        "operations": operations,
    }


def push_response(rt, name, operations):
    response = rt["client"].post(
        "/api/v1/sync/push",
        headers=rt["actors"][name]["headers"],
        json=request_body(rt, name, operations),
    )
    assert response.headers["cache-control"] == "no-store"
    if response.status_code == 200:
        validate_wire(response.json(), "PushResponse")
    return response


def push(rt, name, op):
    response = push_response(rt, name, [op])
    assert response.status_code == 200, response.text
    return response.json()["results"][0]


def seed_challenge(rt, *, status="active", start=None):
    identifier, start = uuid4(), start or rt["start"]
    start_at = datetime.combine(start, time.min, UTC)
    accepted = rt["now"] if start == rt["start"] else start_at - timedelta(hours=12)
    created = accepted - timedelta(hours=1)
    with rt["migrator"].begin() as c:
        values = {
            "id": identifier,
            "a": rt["actors"]["a"]["owner"],
            "b": rt["actors"]["b"]["owner"],
            "epoch": rt["epoch"],
            "status": status,
            "terms": json.dumps(TERMS),
            "created": created,
            "expires": created + timedelta(hours=168),
        }
        if status == "invited":
            c.execute(
                text(
                    "INSERT INTO app.nemesis_challenges(id,inviter_id,invitee_id,"
                    "inviter_generation,invitee_generation,sync_epoch,status,terms,"
                    "created_at,expires_at) VALUES(:id,:a,:b,1,1,:epoch,:status,"
                    "CAST(:terms AS jsonb),:created,:expires)"
                ),
                values,
            )
        else:
            values |= {
                "accepted": accepted,
                "start": start,
                "end": start + timedelta(days=7),
                "start_at": start_at,
                "end_at": start_at + timedelta(days=7),
                "deadline": start_at + timedelta(days=37),
            }
            c.execute(
                text(
                    "INSERT INTO app.nemesis_challenges(id,inviter_id,invitee_id,"
                    "inviter_generation,invitee_generation,sync_epoch,status,terms,"
                    "created_at,expires_at,accepted_at,start_date,end_date,start_at,end_at,"
                    "deadline_at,result_status) VALUES(:id,:a,:b,1,1,:epoch,:status,"
                    "CAST(:terms AS jsonb),:created,:expires,:accepted,:start,:end,:start_at,"
                    ":end_at,:deadline,'provisional')"
                ),
                values,
            )
            if status == "active":
                for owner in sorted([values["a"], values["b"]]):
                    c.execute(
                        text("INSERT INTO app.nemesis_slots VALUES(:owner,:id)"),
                        {"owner": owner, "id": identifier},
                    )
    return identifier


def snapshot(rt, name="a"):
    owner = rt["actors"][name]["owner"]
    tables = (
        "user_profiles",
        "goal_timelines",
        "goal_versions",
        "diary_days",
        "meals",
        "meal_items",
        "weights",
        "sync_changes",
        "sync_receipts",
        "sync_reservations",
        "sync_counters",
        "motivation_accounts",
        "motivation_days",
        "motivation_badges",
    )
    with rt["admin"].connect() as c:
        return {
            table: list(
                c.scalars(
                    text(
                        f"SELECT to_jsonb(t)::text FROM app.{table} t "
                        "WHERE owner_id=:owner ORDER BY to_jsonb(t)::text"
                    ),
                    {"owner": owner},
                )
            )
            for table in tables
        }


def meal_payload(day, zone="UTC"):
    return example("meal") | {
        "local_date": day.isoformat(),
        "time_zone": zone,
        "occurred_at": datetime.combine(day, time(12), UTC).isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.parametrize("change", ["zone", "delete"])
def test_profile_axis_rejection_is_wire_valid_durable_and_has_no_source_effect(live, change):
    rt = live
    seed_challenge(rt)
    actor = rt["actors"]["a"]
    op = operation(
        rt,
        "profile",
        entity=actor["profile"],
        base=1,
        payload=example("profile") | {"time_zone": "Europe/Warsaw"},
        action="delete" if change == "delete" else "upsert",
    )
    before = snapshot(rt)
    refused = push(rt, "a", op)
    assert refused["status"] == "rejected" and refused["code"] == "invalid_payload"
    after = snapshot(rt)
    assert {k: v for k, v in after.items() if k != "sync_receipts"} == {
        k: v for k, v in before.items() if k != "sync_receipts"
    }
    assert len(after["sync_receipts"]) == len(before["sync_receipts"]) + 1
    assert push(rt, "a", op) == refused
    assert snapshot(rt) == after


def test_same_zone_profile_edit_is_allowed_but_product_and_replay_have_no_hooks(live, monkeypatch):
    rt = live
    seed_challenge(rt)
    calls, real_lock = [], NemesisSourceProjection.lock

    def tracked(self, session, context):
        calls.append(context.source_kind)
        return real_lock(self, session, context)

    monkeypatch.setattr(NemesisSourceProjection, "lock", tracked)
    op = operation(
        rt,
        "profile",
        entity=rt["actors"]["a"]["profile"],
        base=1,
        payload=example("profile") | {"time_zone": "UTC", "pseudonym": "Żołnierz"},
    )
    assert push(rt, "a", op)["status"] == "accepted"
    assert push(rt, "a", op)["status"] == "already_applied"
    draft = operation(rt, "product_draft")
    assert push(rt, "a", draft)["status"] == "accepted"
    stale = operation(rt, "profile", entity=rt["actors"]["a"]["profile"], base=1)
    assert push(rt, "a", stale)["status"] == "conflict"
    assert calls == ["profile"]


@pytest.mark.parametrize("kind", ["meal", "diary_day"])
def test_future_period_axis_mismatch_rolls_implicit_day_and_counter_back(live, kind):
    rt = live
    seed_challenge(rt)
    day = rt["start"] + timedelta(days=1)
    payload = (
        meal_payload(day, "Europe/Warsaw")
        if kind == "meal"
        else {
            "local_date": day.isoformat(),
            "time_zone": "Europe/Warsaw",
            "declared_complete": True,
        }
    )
    before = snapshot(rt)
    result = push(rt, "a", operation(rt, kind, payload=payload))
    assert result["status"] == "rejected" and result["code"] == "invalid_payload"
    after = snapshot(rt)
    assert {k: v for k, v in after.items() if k != "sync_receipts"} == {
        k: v for k, v in before.items() if k != "sync_receipts"
    }


def test_meal_move_carries_both_dates_and_authenticated_frozen_provenance(live, monkeypatch):
    rt = live
    seed_challenge(rt)
    day = rt["start"]
    original = operation(rt, "meal", payload=meal_payload(day))
    assert push(rt, "a", original)["status"] == "accepted"
    captured, real_apply = [], NemesisSourceProjection.apply

    def tracked(self, session, context):
        captured.append((self.provenance, context, self.plan))
        return real_apply(self, session, context)

    monkeypatch.setattr(NemesisSourceProjection, "apply", tracked)
    moved = operation(
        rt,
        "meal",
        entity=UUID(original["entity_id"]),
        base=1,
        payload=meal_payload(day + timedelta(days=1)),
    )
    assert push(rt, "a", moved)["status"] == "accepted"
    provenance, context, plan = captured[0]
    assert context.old_dates == (day,) and context.new_dates == (day + timedelta(days=1),)
    assert provenance.owner_id == context.owner_id == rt["actors"]["a"]["owner"]
    assert provenance.account_generation == 1 and provenance.sync_epoch == rt["epoch"]
    assert context.qualified_at is not None and plan.source.qualified_at is None
    assert "sync_epoch" not in context.__dataclass_fields__


def test_weight_outside_source_date_axis_still_discovers_accepted_zone_period(live, monkeypatch):
    rt = live
    challenge = seed_challenge(rt)
    captured, real_apply = [], NemesisSourceProjection.apply

    def tracked(self, session, context):
        captured.append(self.plan)
        return real_apply(self, session, context)

    monkeypatch.setattr(NemesisSourceProjection, "apply", tracked)
    instant = datetime.combine(rt["start"], time(5), UTC)
    payload = example("weight") | {
        "occurred_at": instant.isoformat().replace("+00:00", "Z"),
        "local_date": (rt["start"] - timedelta(days=1)).isoformat(),
        "time_zone": "Pacific/Honolulu",
    }
    assert push(rt, "a", operation(rt, "weight", payload=payload))["status"] == "accepted"
    assert [row.id for row in captured[0].challenges] == [challenge]


def test_goal_full_axis_locks_all_history_before_real_refresh(live, monkeypatch):
    rt = live
    ids = [
        seed_challenge(rt),
        seed_challenge(rt, status="finished", start=rt["start"] - timedelta(days=100)),
    ]
    real_refresh = motivation_repository.refresh
    checked = []

    def before_refresh(session, owner, dates=None, batch=256):
        assert dates is None
        for identifier in sorted(ids):
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError) as blocked, rt["admin"].begin() as other:
                other.execute(
                    text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": identifier},
                )
            assert blocked.value.orig.sqlstate == "55P03"
        checked.append(True)
        return real_refresh(session, owner, dates, batch)

    monkeypatch.setattr(motivation_repository, "refresh", before_refresh)
    assert push(rt, "a", operation(rt, "goal"))["status"] == "accepted"
    assert checked == [True]


@pytest.mark.parametrize("failure", ["unknown_sql", "application"])
def test_late_source_failure_rolls_real_source_h_counter_motivation_and_receipt_back(
    live,
    monkeypatch,
    failure,
):
    rt = live
    seed_challenge(rt)
    before, real_apply = snapshot(rt), NemesisSourceProjection.apply

    def fail(self, session, context):
        real_apply(self, session, context)
        if failure == "unknown_sql":
            session.execute(
                text(
                    "DO $$ BEGIN RAISE EXCEPTION 'synthetic unknown source check' "
                    "USING ERRCODE='23514'; END $$"
                )
            )
        raise RuntimeError("synthetic source adapter failure")

    monkeypatch.setattr(NemesisSourceProjection, "apply", fail)
    response = push_response(rt, "a", [operation(rt, "weight")])
    assert response.status_code == (503 if failure == "unknown_sql" else 500)
    assert "results" not in response.json()
    assert snapshot(rt) == before


def test_after_end_profile_zone_change_uses_real_guard_without_rewriting_period(live):
    rt = live
    challenge = seed_challenge(rt)
    with rt["migrator"].begin() as c:
        before = c.execute(
            text("SELECT start_at,end_at,deadline_at FROM app.nemesis_challenges WHERE id=:id"),
            {"id": challenge},
        ).one()
        instant = before.end_at.astimezone(UTC).isoformat()
        c.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ "
                "SELECT TIMESTAMPTZ '" + instant + "' $$"
            )
        )
    op = operation(
        rt,
        "profile",
        entity=rt["actors"]["a"]["profile"],
        base=1,
        payload=example("profile") | {"time_zone": "Europe/Warsaw"},
    )
    assert push(rt, "a", op)["status"] == "accepted"
    with rt["admin"].connect() as c:
        assert (
            c.execute(
                text("SELECT start_at,end_at,deadline_at FROM app.nemesis_challenges WHERE id=:id"),
                {"id": challenge},
            ).one()
            == before
        )


def wait_for_blocker(rt, blocker_pid):
    deadline = monotonic() + 8
    while monotonic() < deadline:
        with rt["admin"].connect() as c:
            found = c.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                    "WHERE datname=current_database() AND pid<>:blocker "
                    "AND :blocker=ANY(pg_blocking_pids(pid)))"
                ),
                {"blocker": blocker_pid},
            )
        if found:
            return
        Event().wait(0.01)  # Backoff only; observed PostgreSQL blocking is the oracle.
    raise AssertionError("competing transaction never entered the observed DB lock wait")


def hold_source(monkeypatch):
    entered, release, state = Event(), Event(), {}
    real_refresh = motivation_repository.refresh

    def refresh(session, owner, dates=None, batch=256):
        qualified = real_refresh(session, owner, dates, batch)
        state["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert release.wait(12), "source commit barrier was not released"
        return qualified

    monkeypatch.setattr(motivation_repository, "refresh", refresh)
    return entered, release, state


@pytest.mark.parametrize("competitor", ["cancel", "deletion"])
def test_source_commit_serializes_with_cancel_or_deletion(live, monkeypatch, competitor):
    rt = live
    challenge = seed_challenge(rt)
    entered, release, state = hold_source(monkeypatch)
    op = operation(rt, "weight")

    def other():
        if competitor == "cancel":
            actor = rt["actors"]["b"]
            return rt["client"].post(
                "/api/v1/nemesis/" + str(challenge) + "/cancel",
                headers=actor["headers"]
                | {
                    "X-Sync-Epoch": str(rt["epoch"]),
                    "Idempotency-Key": str(uuid4()),
                    "If-Match": '"1"',
                },
                json={"reason": "sharing_revoked"},
            )
        with rt["operator"].begin() as c:
            return c.scalar(
                text("SELECT app.begin_account_deletion(:owner,:op,1)"),
                {"owner": rt["actors"]["a"]["owner"], "op": uuid4()},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        source = pool.submit(push, rt, "a", op)
        assert entered.wait(8)
        competing = pool.submit(other)
        try:
            wait_for_blocker(rt, state["pid"])
        finally:
            release.set()
        assert source.result(timeout=15)["status"] == "accepted"
        result = competing.result(timeout=15)
        if competitor == "cancel":
            assert result.status_code == 200, result.text
    with rt["admin"].connect() as c:
        row = c.execute(
            text("SELECT status,cancel_reason FROM app.nemesis_challenges WHERE id=:id"),
            {"id": challenge},
        ).one()
        assert row == ("cancelled", "sharing_revoked" if competitor == "cancel" else "deleted")
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE challenge_id=:id"),
                {"id": challenge},
            )
            == 0
        )


def test_source_profile_commit_precedes_accept_axis_recheck(live, monkeypatch):
    rt = live
    challenge = seed_challenge(rt, status="invited")
    with rt["migrator"].begin() as c:
        c.execute(
            text(
                "INSERT INTO app.nemesis_releases VALUES('test-projector','test-finalizer') "
                "ON CONFLICT DO NOTHING"
            )
        )
        c.execute(
            text(
                "UPDATE app.nemesis_control SET enabled=true,sync_epoch=:epoch,"
                "projector_revision='test-projector',finalizer_revision='test-finalizer'"
            ),
            {"epoch": rt["epoch"]},
        )
    entered, release, state = hold_source(monkeypatch)
    op = operation(
        rt,
        "profile",
        entity=rt["actors"]["a"]["profile"],
        base=1,
        payload=example("profile") | {"time_zone": "Europe/Warsaw"},
    )

    def accept_sql():
        with rt["api"].begin() as c:
            return c.scalar(
                text(
                    "SELECT app.e8n_execute(:issuer,:subject,:epoch,'accept',"
                    ":key,:hash,CAST(:payload AS jsonb))"
                ),
                {
                    "issuer": ISSUER,
                    "subject": rt["actors"]["b"]["subject"],
                    "epoch": rt["epoch"],
                    "key": uuid4(),
                    "hash": "a" * 64,
                    "payload": json.dumps(
                        {"challenge_id": str(challenge), "revision": 1, "terms": TERMS}
                    ),
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        source = pool.submit(push, rt, "a", op)
        assert entered.wait(8)
        accepting = pool.submit(accept_sql)
        try:
            wait_for_blocker(rt, state["pid"])
        finally:
            release.set()
        assert source.result(timeout=15)["status"] == "accepted"
        refused = accepting.result(timeout=15)
        assert not refused["ok"] and refused["code"] == "nemesis_axis_unavailable"
    with rt["admin"].connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE challenge_id=:id"),
                {"id": challenge},
            )
            == 0
        )


def test_stale_epoch_at_guard_is_request_failure_and_never_durable_source_refusal(
    live, monkeypatch
):
    rt = live
    seed_challenge(rt)
    before, real_lock = snapshot(rt), NemesisSourceProjection.lock
    new_epoch = uuid4()

    def restore_between_context_and_guard(self, session, context):
        # External restore fence commits independently; caller cannot choose it.
        with rt["migrator"].begin() as other:
            other.execute(
                text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
                {"epoch": new_epoch},
            )
        return real_lock(self, session, context)

    monkeypatch.setattr(NemesisSourceProjection, "lock", restore_between_context_and_guard)
    op = operation(rt, "weight")
    response = push_response(rt, "a", [op])
    assert response.status_code == 503 and "results" not in response.json()
    assert snapshot(rt) == before
    replay = push_response(rt, "a", [op])
    assert replay.status_code == 409 and replay.json()["code"] == "sync_epoch_changed"
    assert snapshot(rt) == before


def test_deletion_committed_before_sync_blocks_old_receipt_replay_and_new_source(live):
    rt = live
    seed_challenge(rt)
    accepted = operation(rt, "weight")
    assert push(rt, "a", accepted)["status"] == "accepted"
    with rt["operator"].begin() as connection:
        connection.execute(
            text("SELECT app.begin_account_deletion(:owner,:operation,1)"),
            {"owner": rt["actors"]["a"]["owner"], "operation": uuid4()},
        )
    before = snapshot(rt)
    for op in (accepted, operation(rt, "weight")):
        response = push_response(rt, "a", [op])
        assert response.status_code == 403 and response.json()["code"] == "account_deleting"
        assert "results" not in response.json()
    assert snapshot(rt) == before
