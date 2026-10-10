"""Two actual SQLite devices over loopback HTTP to PostgreSQL; synthetic auth only.

Real OIDC/PKCE and deletion provider evidence lives in tests/keycloak. This suite
does not replace it, and never substitutes SQLite for the backend database.
"""

import json
import socket
import sys
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import Request
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.identity.dependencies import current_principal

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.sync_client import ClientError, SyncHTTP, SyncStore  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def live_api(database, monkeypatch):
    engine, _, url = database
    app_engine = create_engine(
        url, hide_parameters=True, connect_args={"options": "-c role=calorie_app_api"}
    )
    settings = Settings(
        database_url=url, environment="test", catalog_page_token_secret=SecretStr("e4" * 32)
    )
    app = create_app(settings, engine=app_engine)
    who = Principal("https://reference.example.test/realm", str(uuid4()), frozenset({"user"}))
    other = Principal(who.issuer, str(uuid4()), frozenset({"user"}))

    def principal(request: Request):
        return who if request.headers.get("Authorization") == "Bearer synthetic-a" else other

    async def verify(token):
        return who if token == "synthetic-a" else other

    monkeypatch.setattr(app.state.oidc_verifier, "verify", verify)
    app.dependency_overrides[current_principal] = principal
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
    )
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = monotonic() + 10
    while not server.started:
        assert thread.is_alive() and monotonic() < deadline, "uvicorn did not start"
        Event().wait(0.02)
    yield f"http://127.0.0.1:{port}", who, engine
    server.should_exit = True
    thread.join(timeout=10)
    listener.close()
    app_engine.dispose()
    assert not thread.is_alive(), "own uvicorn thread must stop"


def device(path, api, who, *, token="synthetic-a"):
    store = SyncStore(path)
    scope = store.register(issuer=who.issuer, subject=who.subject)
    store.select(scope)
    with httpx.Client() as http:
        response = http.post(
            api + "/api/v1/me/bootstrap",
            headers={"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid4())},
        )
    assert response.status_code == 200, response.text
    lease = store.db.execute("SELECT generation FROM active WHERE id=1").fetchone()[0]
    store.bootstrap(scope, response.json(), lease_generation=lease)
    context = store.capture()
    http = SyncHTTP(api, token_supplier=lambda _: token)
    http.pull(store, context, full=True)
    return store, context, http


def add_weight(store, context, *, entity=None, action="create", kg="80"):
    payload = json.loads((ROOT / "contracts/examples/valid/weight.json").read_text())
    payload["weight_kg"] = kg
    entity = entity or str(uuid4())
    draft = store.import_source(context.scope, "weight", entity, action, json.dumps(payload))
    return store.materialize(context, draft)


@pytest.mark.parametrize("boundary", ["request", "payload"])
def test_real_http_chunked_boundaries_have_zero_dml_on_preflight_rejection(
    live_api, tmp_path, boundary
):
    api, who, engine = live_api
    store, context, transport = device(tmp_path / "chunked.sqlite", api, who)
    try:
        add_weight(store, context)
        body = store.prepare_push(context)
        with httpx.Client(timeout=10) as http:
            for extra in (0, 1):
                body["operations"][0]["operation_id"] = str(uuid4())
                body["operations"][0]["entity_id"] = str(uuid4())
                raw = json.dumps(body, separators=(",", ":")).encode()
                if boundary == "request":
                    raw += b" " * (1048576 - len(raw) + extra)
                else:
                    size = len(
                        json.dumps(body["operations"][0]["payload"], separators=(",", ":")).encode()
                    )
                    raw = raw.replace(
                        b'"payload":', b'"payload":' + b" " * (262144 - size + extra), 1
                    )
                with engine.connect() as connection:
                    before = connection.scalar(text("SELECT count(*) FROM app.sync_receipts"))
                chunks = (raw[offset : offset + 8192] for offset in range(0, len(raw), 8192))
                response = http.post(
                    api + "/api/v1/sync/push",
                    content=chunks,
                    headers={
                        "Authorization": "Bearer synthetic-a",
                        "Content-Type": "application/json",
                    },
                )
                assert response.request.headers["Transfer-Encoding"] == "chunked"
                assert "Content-Length" not in response.request.headers
                assert response.status_code == (200 if extra == 0 else 413), response.text
                with engine.connect() as connection:
                    after = connection.scalar(text("SELECT count(*) FROM app.sync_receipts"))
                assert after == before + (1 if extra == 0 else 0)
    finally:
        transport.close()
        store.close()


def test_two_devices_http_lost_ack_restart_conflict_and_originals(live_api, tmp_path):
    api, who, engine = live_api
    a, ac, ah = device(tmp_path / "a.sqlite", api, who)
    b, bc, bh = device(tmp_path / "b.sqlite", api, who)
    try:
        operation = add_weight(a, ac)

        def lost(_):
            raise ConnectionError("simulate process loss after committed HTTP result")

        with pytest.raises(ConnectionError):
            ah.push(a, ac, after_response=lost)
        a.close()
        a = SyncStore(tmp_path / "a.sqlite")
        replay = ah.push(a, ac)
        assert replay["results"][0]["status"] == "already_applied"
        assert a.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == 1
        ah.pull(a, ac)
        bh.pull(b, bc)
        first = add_weight(a, ac, entity=operation["entity_id"], action="update", kg="81")
        second = add_weight(b, bc, entity=operation["entity_id"], action="update", kg="82")
        assert first["base_revision"] == second["base_revision"] == 1
        assert ah.push(a, ac)["results"][0]["status"] == "accepted"
        conflict = bh.push(b, bc)["results"][0]
        assert (
            conflict["status"] == "conflict" and conflict["current"]["payload"]["weight_kg"] == "81"
        )
        assert b.db.execute("SELECT count(*) FROM conflicts").fetchone()[0] == 1
        assert b.db.execute("SELECT count(*) FROM originals").fetchone()[0] == 1
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.weights WHERE id=:id"),
                    {"id": operation["entity_id"]},
                )
                == 1
            )
    finally:
        a.close()
        b.close()
        ah.close()
        bh.close()


def test_http_snapshot_resume_between_pages_and_atomic_shadow(live_api, tmp_path):
    api, who, _ = live_api
    a, ac, ah = device(tmp_path / "a.sqlite", api, who)
    b, bc, bh = device(tmp_path / "b.sqlite", api, who)
    try:
        for _ in range(3):
            add_weight(a, ac)
        ah.push(a, ac)
        session = b.start_pull(bc, full=True, limit=1)
        assert not bh.pull_page(b, bc, session)
        assert b.db.execute("SELECT count(*) FROM shadow").fetchone()[0] == 0
        b.close()
        b = SyncStore(tmp_path / "b.sqlite")
        while not bh.pull_page(b, bc, session):
            assert b.db.execute("SELECT count(*) FROM shadow").fetchone()[0] == 0
        assert b.db.execute("SELECT count(*) FROM shadow").fetchone()[0] >= 3
        assert b.db.execute("SELECT checkpoint FROM bindings").fetchone()[0]
    finally:
        a.close()
        b.close()
        ah.close()
        bh.close()


def test_http_old_epoch_keeps_outbox_and_requires_new_decision(live_api, tmp_path):
    api, who, engine = live_api
    a, old, http = device(tmp_path / "a.sqlite", api, who)
    try:
        op = add_weight(a, old)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
                {"epoch": uuid4()},
            )
        with pytest.raises(ClientError, match="sync_epoch_changed"):
            http.push(a, old)
        assert a.db.execute("SELECT state FROM wire_ops").fetchone()[0] == "sent"
        assert json.loads(a.db.execute("SELECT wire_json FROM wire_ops").fetchone()[0]) == op
        with httpx.Client() as raw:
            response = raw.post(
                api + "/api/v1/me/bootstrap",
                headers={"Authorization": "Bearer synthetic-a", "Idempotency-Key": str(uuid4())},
            )
        assert response.status_code == 200
        a.bootstrap(old.scope, response.json(), lease_generation=old.lease_generation)
        current = a.capture()
        http.pull(a, current, full=True, recovery_ids=[op["operation_id"]])
        with pytest.raises(ClientError, match="recovery_required"):
            http.push(a, current)
        assert a.db.execute("SELECT count(*) FROM originals").fetchone()[0] == 1
    finally:
        a.close()
        http.close()
