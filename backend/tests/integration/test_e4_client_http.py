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
from sqlalchemy.orm import sessionmaker

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
    engine._e4_reference_app = app
    engine._e4_reference_runtime = app_engine
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


def test_two_sqlite_devices_real_database_restore_and_concurrent_http_recovery(live_api, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    api, who, source = live_api
    a, old_a, ah = device(tmp_path / "restore-a.sqlite", api, who)
    b, old_b, bh = device(tmp_path / "restore-b.sqlite", api, who)
    app = source._e4_reference_app
    suffix = uuid4().hex[:12]
    backup_name, restore_name = f"e4_http_backup_{suffix}_test", f"e4_http_restore_{suffix}_test"
    admin = create_engine(source.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    restored = runtime = None
    try:
        # Quiesce owned pools before making a physical PG copy. No API request
        # occurs until its replacement DB has a new committed epoch.
        source.dispose()
        source._e4_reference_runtime.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{backup_name}" TEMPLATE "{source.url.database}"'
            )
        original = add_weight(a, old_a)
        assert ah.push(a, old_a)["results"][0]["status"] == "accepted"
        bh.pull(b, old_b)
        counterpart = add_weight(b, old_b, entity=original["entity_id"])
        old_b_request = b.prepare_push(old_b)
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{restore_name}" TEMPLATE "{backup_name}"')
        restored = create_engine(source.url.set(database=restore_name))
        new_epoch = uuid4()
        with restored.begin() as connection:
            connection.execute(
                text("UPDATE app.installation_state SET sync_epoch=:e WHERE id=1"), {"e": new_epoch}
            )
        runtime = create_engine(
            source.url.set(database=restore_name),
            connect_args={"options": "-c role=calorie_app_api"},
        )
        app.state.engine = runtime
        app.state.session_factory = sessionmaker(runtime, expire_on_commit=False)
        with pytest.raises(ClientError, match="sync_epoch_changed"):
            bh.push(b, old_b)
        assert (
            json.loads(
                b.db.execute(
                    "SELECT wire_json FROM wire_ops WHERE operation_id=?",
                    (counterpart["operation_id"],),
                ).fetchone()[0]
            )
            == old_b_request["operations"][0]
        )
        currents, proposals = [], []
        for store, old, transport, operation in (
            (a, old_a, ah, original),
            (b, old_b, bh, counterpart),
        ):
            with httpx.Client() as http:
                response = http.post(
                    api + "/api/v1/me/bootstrap",
                    headers={
                        "Authorization": "Bearer synthetic-a",
                        "Idempotency-Key": str(uuid4()),
                    },
                )
            assert response.status_code == 200
            store.bootstrap(old.scope, response.json(), lease_generation=old.lease_generation)
            current = store.capture()
            transport.pull(store, current, full=True, recovery_ids=[operation["operation_id"]])
            assert store.db.execute("SELECT count(*) FROM originals").fetchone()[0] == 1
            recovery = {
                "source_epoch": old.sync_epoch,
                "source_entity_id": original["entity_id"],
                "source_revision": 1,
                "source_operation_id": operation["operation_id"],
                "decision": "recreate_missing",
            }
            proposal = store.materialize(
                current,
                operation["operation_id"],
                recovery=recovery,
                target_id=str(uuid4()),
                confirmed=True,
            )
            currents.append(current)
            proposals.append(proposal)
        a.close()
        b.close()

        def push_recovery(index):
            with SyncStore(
                tmp_path / ("restore-a.sqlite" if index == 0 else "restore-b.sqlite")
            ) as store:
                transport = SyncHTTP(api, token_supplier=lambda _: "synthetic-a")
                try:
                    return transport.push(store, currents[index], recovery_only=True)
                finally:
                    transport.close()

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(push_recovery, (0, 1)))
        replies = [result["results"][0] for result in results]
        assert sorted(result["status"] for result in replies) == ["accepted", "already_applied"]
        targets = {result["recovery_mapping"]["target_entity_id"] for result in replies}
        assert len(targets) == 1 and original["entity_id"] not in targets
        assert [result["entity_id"] for result in replies] == [p["entity_id"] for p in proposals]
        with restored.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.weights WHERE owner_id=:o"),
                    {"o": old_a.account_id},
                )
                == 1
            )
        a, b = SyncStore(tmp_path / "restore-a.sqlite"), SyncStore(tmp_path / "restore-b.sqlite")
        for store, proposal in zip((a, b), proposals, strict=True):
            saved = json.loads(
                store.db.execute(
                    "SELECT wire_json FROM wire_ops WHERE operation_id=?",
                    (proposal["operation_id"],),
                ).fetchone()[0]
            )
            assert saved == proposal
            assert store.db.execute("SELECT count(*) FROM originals").fetchone()[0] == 1
    finally:
        a.close()
        b.close()
        ah.close()
        bh.close()
        if runtime:
            runtime.dispose()
        if restored:
            restored.dispose()
        app.state.engine = source._e4_reference_runtime
        app.state.session_factory = sessionmaker(
            source._e4_reference_runtime, expire_on_commit=False
        )
        with admin.connect() as connection:
            for name in (restore_name, backup_name):
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()
