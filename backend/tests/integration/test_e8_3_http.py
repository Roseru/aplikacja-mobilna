"""Real PostgreSQL/SCRAM lifecycle HTTP probes with synthetic signed JWTs."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from calorie_app.modules.nemesis.addressing import generate_share_code, share_code_digest
from calorie_app.modules.nemesis.rules import challenge_period
from calorie_app.modules.nemesis.schemas import NemesisMetadata, ShareCodeReceipt
from tests.support.e8_3_app import component_app
from tests.support.e8_3_jwt import ISSUER, SignedTokens
from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
TERMS = {
    "rule_version": "regularity_v1",
    "duration_days": 7,
    "time_zone": "Europe/Warsaw",
    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
}


@pytest.fixture
def runtime():
    pg = PrivatePostgres.from_environment()
    migrator = pg.engine("migrator")
    api = pg.engine("api")
    worker = pg.engine("worker")
    tokens = SignedTokens()
    with migrator.begin() as c:
        epoch = c.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
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
            {"epoch": epoch},
        )
        c.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
            "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp "
            "AS $$ SELECT TIMESTAMPTZ '2026-10-12 12:00:00Z' $$"
        )
    app = component_app(api, tokens.verifier, projection_initializer=lambda session, response: None)
    with TestClient(app) as client:
        yield pg, migrator, api, worker, tokens, client, epoch
    with migrator.begin() as c:
        c.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
            "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp "
            "AS $$ SELECT clock_timestamp() $$"
        )
        c.execute(text("UPDATE app.nemesis_control SET enabled=false"))
    for engine in (migrator, api, worker):
        engine.dispose()


def account(rt, zone="Europe/Warsaw"):
    _, migrator, _, _, _, _, _ = rt
    owner = uuid4()
    subject = str(uuid4())
    with migrator.begin() as c:
        c.execute(
            text("INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:issuer,:sub)"),
            {"id": owner, "issuer": ISSUER, "sub": subject},
        )
        c.execute(text("INSERT INTO app.sync_counters(owner_id) VALUES(:id)"), {"id": owner})
        c.execute(
            text(
                "INSERT INTO app.user_profiles(id,owner_id,revision,pseudonym,time_zone,"
                "activity_class) VALUES(:pid,:id,1,'Ĺ»oĹ‚nierz',:zone,'stationary')"
            ),
            {"pid": uuid4(), "id": owner, "zone": zone},
        )
    return owner, subject


def headers(rt, who, key=None, revision=None):
    _, _, _, _, tokens, _, epoch = rt
    result = {
        "Authorization": "Bearer " + tokens.token(who[1]),
        "X-Sync-Epoch": str(epoch),
        "Idempotency-Key": str(key or uuid4()),
    }
    if revision is not None:
        result["If-Match"] = '"' + str(revision) + '"'
    return result


def issue(rt, who, key=None):
    response = rt[5].post("/api/v1/me/nemesis/share-code", headers=headers(rt, who, key))
    assert response.status_code == 200, response.text
    ShareCodeReceipt.model_validate(response.json())
    return response.json()


def create(rt, sender, receiver, key=None, terms=None):
    code = issue(rt, receiver)["destination_code"]
    response = rt[5].post(
        "/api/v1/nemesis",
        headers=headers(rt, sender, key),
        json={"destination_code": code, "terms": terms or TERMS},
    )
    assert response.status_code in (200, 201), response.text
    NemesisMetadata.model_validate(response.json())
    return response.json(), code


def accept(rt, receiver, challenge, key=None, terms=None):
    return rt[5].post(
        "/api/v1/nemesis/" + challenge["id"] + "/accept",
        headers=headers(rt, receiver, key, challenge["revision"]),
        json={"terms": terms or TERMS},
    )


def clock(rt, value):
    assert value.tzinfo is not None
    # Test migrator only; no clock parameter exists in production request DTOs.
    canonical = value.astimezone(UTC).isoformat()
    with rt[1].begin() as c:
        c.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
            "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ "
            "SELECT TIMESTAMPTZ '" + canonical + "' $$"
        )


def test_http_lost_ack_rotation_and_revocation(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    key = uuid4()
    first = issue(rt, b, key)
    assert issue(rt, b, key) == first
    new = issue(rt, b)
    assert new["destination_code"] != first["destination_code"]
    assert (
        rt[5].post("/api/v1/me/nemesis/share-code", headers=headers(rt, b, key)).status_code == 409
    )
    response = rt[5].post(
        "/api/v1/nemesis",
        headers=headers(rt, a),
        json={"destination_code": first["destination_code"], "terms": TERMS},
    )
    assert response.status_code == 409
    revoke_key = uuid4()
    assert (
        rt[5]
        .delete("/api/v1/me/nemesis/share-code", headers=headers(rt, b, revoke_key))
        .status_code
        == 200
    )
    assert (
        rt[5]
        .delete("/api/v1/me/nemesis/share-code", headers=headers(rt, b, revoke_key))
        .status_code
        == 200
    )
    assert (
        rt[5]
        .post(
            "/api/v1/nemesis",
            headers=headers(rt, a),
            json={"destination_code": new["destination_code"], "terms": TERMS},
        )
        .status_code
        == 409
    )
    with rt[1].connect() as c:
        assert c.scalar(
            text("SELECT digest FROM app.nemesis_share_codes WHERE owner_id=:id"), {"id": b[0]}
        ) == share_code_digest(new["destination_code"])
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE inviter_id=:id"),
                {"id": a[0]},
            )
            == 0
        )


def test_twenty_invalid_admissions_commit_and_replay(runtime):
    rt = runtime
    a = account(rt)
    codes = []
    for _ in range(20):
        key = uuid4()
        body = {"destination_code": generate_share_code(), "terms": TERMS}
        response = rt[5].post("/api/v1/nemesis", headers=headers(rt, a, key), json=body)
        assert response.status_code == 409, response.text
        codes.append(response.json()["code"])
    key = uuid4()
    body = {"destination_code": generate_share_code(), "terms": TERMS}
    for _ in range(2):
        response = rt[5].post("/api/v1/nemesis", headers=headers(rt, a, key), json=body)
        assert response.status_code == 429 and response.headers["retry-after"]
    assert len(set(codes)) == 1
    with rt[1].connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=:id "
                    "AND kind='attempt'"
                ),
                {"id": a[0]},
            )
            == 21
        )
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE inviter_id=:id"),
                {"id": a[0]},
            )
            == 0
        )


def test_accept_exact_terms_epoch_revision_and_cancel_replay(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    other = account(rt)
    invite, code = create(rt, a, b)
    assert accept(rt, a, invite).status_code == 409
    changed = json.loads(json.dumps(TERMS))
    changed["scope"]["weight_change"] = True
    assert accept(rt, b, invite, terms=changed).status_code == 409
    assert accept(rt, b, invite | {"revision": 99}).status_code == 409
    key = uuid4()
    active = accept(rt, b, invite, key)
    assert active.status_code == 200, active.text
    metadata = active.json()
    NemesisMetadata.model_validate(metadata)
    assert metadata["status"] == "active" and metadata["result_status"] == "provisional"
    assert accept(rt, b, invite, key).json() == metadata
    assert (
        rt[5].get("/api/v1/nemesis/" + invite["id"], headers=headers(rt, other)).status_code == 404
    )
    for who in (a, b):
        stats = rt[5].get(
            "/api/v1/nemesis/" + invite["id"] + "/statistics", headers=headers(rt, who)
        )
        assert stats.status_code == 503
        assert "weight" not in stats.text and "goal" not in stats.text
    cancelkey = uuid4()
    response = rt[5].post(
        "/api/v1/nemesis/" + invite["id"] + "/cancel",
        headers=headers(rt, a, cancelkey, metadata["revision"]),
        json={"reason": "sharing_revoked"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    replay = accept(rt, b, invite, key)
    assert replay.status_code in {200, 409}
    assert '"status":"active"' not in replay.text
    assert accept(rt, b, response.json()).status_code == 409


def test_projection_initializer_failure_rolls_back_all_accept(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    invite, _ = create(rt, a, b)
    key = uuid4()

    def failure(session, response):
        raise RuntimeError("test-only initializer failure")

    rt[5].app.state.nemesis_projection_initializer = failure
    with pytest.raises(RuntimeError, match="test-only"):
        accept(rt, b, invite, key)
    with rt[1].connect() as c:
        assert (
            c.scalar(
                text("SELECT status FROM app.nemesis_challenges WHERE id=:id"),
                {"id": UUID(invite["id"])},
            )
            == "invited"
        )
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE challenge_id=:id"),
                {"id": UUID(invite["id"])},
            )
            == 0
        )
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM app.nemesis_receipts WHERE owner_id=:id "
                    "AND operation='accept' AND key=:key"
                ),
                {"id": b[0], "key": key},
            )
            == 0
        )
    rt[5].app.state.nemesis_projection_initializer = lambda s, r: None
    assert accept(rt, b, invite, key).status_code == 200


@pytest.mark.parametrize(
    "now", [datetime(2026, 3, 28, 12, tzinfo=UTC), datetime(2026, 10, 24, 12, tzinfo=UTC)]
)
def test_http_period_uses_calendar_and_utc_deadline(runtime, now):
    rt = runtime
    clock(rt, now)
    a = account(rt)
    b = account(rt)
    invite, _ = create(rt, a, b)
    response = accept(rt, b, invite)
    assert response.status_code == 200, response.text
    result = response.json()
    expected = challenge_period(now, 7, "Europe/Warsaw")
    assert datetime.fromisoformat(result["start_at"].replace("Z", "+00:00")) == expected.start_at
    assert datetime.fromisoformat(result["end_at"].replace("Z", "+00:00")) == expected.end_at
    assert datetime.fromisoformat(result["deadline"].replace("Z", "+00:00")) == expected.deadline
    assert (expected.end_at - expected.start_at).total_seconds() != 7 * 86400


def test_expiry_boundary_and_delayed_slot_release(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    invite, _ = create(rt, a, b)
    expires = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
    clock(rt, expires)
    assert accept(rt, b, invite).status_code == 409
    metadata = rt[5].get("/api/v1/nemesis/" + invite["id"], headers=headers(rt, a)).json()
    assert metadata["status"] == "cancelled" and metadata["cancel_reason"] == "expired"
    fresh, _ = create(rt, a, b)
    response = accept(rt, b, fresh)
    assert response.status_code == 200
    end = datetime.fromisoformat(response.json()["end_at"].replace("Z", "+00:00"))
    clock(rt, end)
    c = account(rt)
    new, _ = create(rt, c, b)
    assert accept(rt, b, new).status_code == 200
    with rt[1].connect() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM app.nemesis_challenges WHERE id=:id"),
                {"id": UUID(fresh["id"])},
            )
            == "finished"
        )


def test_two_connections_accept_shared_participant(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    c = account(rt)
    first, _ = create(rt, a, b)
    second, _ = create(rt, c, b)
    barrier = Barrier(2)

    def run(challenge):
        # Independent HTTP clients, SQL sessions and transactions; barrier admission.
        app = component_app(rt[2], rt[4].verifier, projection_initializer=lambda s, r: None)
        with TestClient(app) as client:
            barrier.wait(timeout=15)
            return client.post(
                "/api/v1/nemesis/" + challenge["id"] + "/accept",
                headers=headers(rt, b, revision=challenge["revision"]),
                json={"terms": TERMS},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(run, [first, second]))
    assert statuses == [200, 409]
    with rt[1].connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE owner_id=:id"), {"id": b[0]}
            )
            == 1
        )


def test_default_gate_raw_execute_and_safe_closed_operations(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    invite, _ = create(rt, a, b)
    with rt[1].begin() as c:
        c.execute(text("UPDATE app.nemesis_control SET enabled=false"))
    assert rt[5].post("/api/v1/me/nemesis/share-code", headers=headers(rt, a)).status_code == 503
    assert accept(rt, b, invite).status_code == 503
    with rt[2].begin() as c:
        raw = c.scalar(
            text("SELECT app.e8n_execute(:issuer,:sub,:epoch,'issue',:key,:hash,'{}')"),
            {"issuer": ISSUER, "sub": a[1], "epoch": rt[6], "key": uuid4(), "hash": "0" * 64},
        )
        assert raw["http_status"] == 503 and not raw["ok"]
    assert rt[5].get("/api/v1/nemesis/" + invite["id"], headers=headers(rt, a)).status_code == 200
    assert rt[5].delete("/api/v1/me/nemesis/share-code", headers=headers(rt, b)).status_code == 200
    response = rt[5].post(
        "/api/v1/nemesis/" + invite["id"] + "/cancel",
        headers=headers(rt, a, revision=invite["revision"]),
        json={"reason": "withdrawn"},
    )
    assert response.status_code == 200
