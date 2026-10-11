"""Regression probes contributed by the independent E4 reviewer."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.sync import service as sync_service
from calorie_app.modules.sync.router import execute_one, preflight
from calorie_app.modules.sync.schemas import preflight_structure
from calorie_app.modules.sync.snapshots import pull

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.sync_client import ClientError, SyncStore
from tools.sync_client.wire import AdaptationRequired


def api_client(setup):
    engine, _, contexts = setup
    a = contexts[0]
    app = create_app(
        Settings(database_url=str(engine.url), catalog_page_token_secret=SECRET), engine=engine
    )
    app.dependency_overrides[current_principal] = lambda: a[0]

    async def verify(token):
        return a[0]

    app.state.oidc_verifier.verify = verify
    return TestClient(app, raise_server_exceptions=False)


def body(ctx, ops):
    return dict(
        protocol_version=1, sync_epoch=ctx[2]["sync_epoch"], checkpoint=ctx[3], operations=ops
    )


def counts(setup, owner):
    with setup[0].connect() as c:
        return [
            c.scalar(text(f"SELECT count(*) FROM app.{table} WHERE owner_id=:o"), {"o": owner})
            for table in ("sync_receipts", "sync_changes", "weights")
        ]


ROOT = Path(__file__).resolve().parents[3]
SECRET = SecretStr("f5" * 32)


@pytest.fixture
def setup(database):
    engine, _, url = database
    factory = sessionmaker(engine, expire_on_commit=False)
    contexts = []
    for _ in range(2):
        who = Principal(
            "https://independent.example/realm", str(uuid4()), frozenset({"user", "admin"})
        )
        with Session(engine) as s, s.begin():
            boot = bootstrap(s, who, uuid4())
        owner = UUID(boot["account_id"])
        cp = pull(factory, owner, {}, SECRET)["checkpoint"]
        contexts.append((who, owner, boot, cp))
    return engine, factory, contexts


def operation(ctx, kind="weight", **kwargs):
    filename = {"diary_day": "diary-day", "product_draft": "product-draft"}.get(kind, kind)
    payload = json.loads((ROOT / f"contracts/examples/valid/{filename}.json").read_text())
    if kind == "goal":
        payload["timeline_base_revision"] = 0
    op = dict(
        operation_id=str(uuid4()),
        entity_type=kind,
        entity_id=str(uuid4()),
        action="upsert",
        base_revision=None,
        sync_epoch=ctx[2]["sync_epoch"],
        payload=payload,
    )
    op.update(kwargs)
    return op


def send(setup, ctx, ops):
    _, factory, _ = setup
    data = dict(
        protocol_version=1, sync_epoch=ctx[2]["sync_epoch"], checkpoint=ctx[3], operations=ops
    )
    preflight_structure(data)
    owner, generation = preflight(factory, ctx[0], data, SECRET)
    return [execute_one(factory, owner, generation, data, op, SECRET)[0] for op in ops]


def recover(ctx, source, epoch, kind="weight"):
    op = operation(ctx, kind)
    op["recovery"] = dict(
        source_epoch=str(epoch),
        source_entity_id=source,
        source_revision=None,
        source_operation_id=None,
        decision="recreate_missing",
    )
    return op


def test_cross_owner_recovery_same_type_denied(setup):
    a, b = setup[2]
    src = operation(b)
    send(setup, b, [src])
    result = send(setup, a, [recover(a, src["entity_id"], uuid4())])[0]
    assert result["code"] == "recovery_source_invalid"
    assert result["current"] is None


def test_cross_owner_recovery_wrong_type_denied(setup):
    a, b = setup[2]
    src = operation(b, "profile")
    send(setup, b, [src])
    result = send(setup, a, [recover(a, src["entity_id"], uuid4())])[0]
    assert result["status"] == "rejected", result
    assert result["code"] == "recovery_source_invalid"


def test_recovery_mapping_concurrent_and_deleted_target(setup):
    a = setup[2][0]
    source = str(uuid4())
    epoch = uuid4()
    ops = [recover(a, source, epoch) for i in range(2)]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda op: send(setup, a, [op])[0], ops))
    assert sorted(r["status"] for r in results) == ["accepted", "already_applied"]
    target = results[0]["recovery_mapping"]["target_entity_id"]
    remove = operation(a, entity_id=target, action="delete", base_revision=1, payload=None)
    assert send(setup, a, [remove])[0]["status"] == "accepted"
    another = send(setup, a, [recover(a, source, epoch)])[0]
    assert another["code"] == "recovery_target_conflict"
    assert another["recovery_mapping"]["target_entity_id"] == target
    assert another["recovery_mapping"]["target_revision"] == 2


def test_final_snapshot_replay_does_not_renew_checkpoint(setup):
    engine, factory, contexts = setup
    a = contexts[0]
    for _ in range(3):
        send(setup, a, [operation(a)])
    first = pull(factory, a[1], {"limit": 2}, SECRET)
    assert first["checkpoint"] is None
    query = dict(
        limit=2,
        sync_epoch=a[2]["sync_epoch"],
        snapshot_token=first["snapshot_token"],
        page_token=first["page_token"],
    )
    final = pull(factory, a[1], query, SECRET)
    again = pull(factory, a[1], query, SECRET)
    assert final == again
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE app.sync_sessions SET created_at=created_at-interval '1 hour', "
                "expires_at=expires_at-interval '1 hour' WHERE owner_id=:o"
            ),
            {"o": a[1]},
        )
    with pytest.raises(Exception, match="snapshot_expired"):
        pull(factory, a[1], query, SECRET)


def test_http_pull_extreme_numeric_limit_returns_422(setup):
    engine, _, contexts = setup
    a = contexts[0]
    app = create_app(
        Settings(database_url=str(engine.url), catalog_page_token_secret=SECRET), engine=engine
    )
    app.dependency_overrides[current_principal] = lambda: a[0]
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/sync/pull", params={"limit": "9" * 5000})
    assert response.status_code == 422, (response.status_code, response.text)


def test_late_real_database_error_prefix_receipt_and_safe_retry(setup, monkeypatch):
    a = setup[2][0]
    ops = [operation(a), operation(a)]
    original = sync_service.mutate

    def fail_second(session, owner, op, counter):
        if op["operation_id"] == ops[1]["operation_id"]:
            session.execute(text("SELECT 1/0"))
        return original(session, owner, op, counter)

    monkeypatch.setattr(sync_service, "mutate", fail_second)
    with api_client(setup) as client:
        result = client.post(
            "/api/v1/sync/push",
            json=body(a, ops),
            headers={"Authorization": "Bearer own-synthetic"},
        )
        assert result.status_code == 503, result.text
        assert set(result.json()) == {"code", "message", "details", "request_id"}
        assert counts(setup, a[1]) == [1, 1, 1]
        monkeypatch.setattr(sync_service, "mutate", original)
        retry = client.post(
            "/api/v1/sync/push",
            json=body(a, ops),
            headers={"Authorization": "Bearer own-synthetic"},
        )
        assert retry.status_code == 200, retry.text
        assert [r["status"] for r in retry.json()["results"]] == ["already_applied", "accepted"]
        assert counts(setup, a[1]) == [2, 2, 2]


@pytest.mark.parametrize("boundary", ["request", "payload"])
def test_actual_byte_boundary_and_plus_one_preflight_zero_dml(setup, boundary):
    a = setup[2][0]
    with api_client(setup) as client:
        for extra, expected in ((0, 200), (1, 413)):
            op = operation(a)
            raw = json.dumps(body(a, [op]), separators=(",", ":"))
            if boundary == "request":
                raw += " " * (1048576 - len(raw.encode()) + extra)
                assert len(raw.encode()) == 1048576 + extra
            else:
                original_payload = json.dumps(op["payload"], separators=(",", ":"))
                padding = " " * (262144 - len(original_payload.encode()) + extra)
                raw = raw.replace('"payload":', '"payload":' + padding, 1)
            before = counts(setup, a[1])
            response = client.post(
                "/api/v1/sync/push",
                content=raw.encode(),
                headers={
                    "Authorization": "Bearer own-synthetic",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == expected, response.text
            after = counts(setup, a[1])
            assert after == ([n + 1 for n in before] if expected == 200 else before)


def test_durable_precision_immutable_wire_and_a_b_a_late_reply(setup, tmp_path):
    engine, factory, contexts = setup
    a, b = contexts
    path = tmp_path / "own-device.sqlite"
    store = SyncStore(path)
    try:
        scope = store.register(issuer=a[0].issuer, subject=a[0].subject)
        other = store.register(issuer=b[0].issuer, subject=b[0].subject)
        store.select(scope)
        store.bootstrap(scope, a[2], lease_generation=1)
        captured = store.capture()
        pull_id = store.start_pull(captured, full=True)
        req = store.prepare_pull(captured, pull_id)
        page = pull(factory, a[1], req, SECRET)
        store.apply_pull(captured, pull_id, req, page)
        for value in ("1.234567000001", "0.000000000001"):
            payload = operation(a)["payload"] | {"weight_kg": value}
            src = store.import_source(scope, "weight", str(uuid4()), "create", json.dumps(payload))
            with pytest.raises(AdaptationRequired, match="precision_review"):
                store.materialize(captured, src)
        payload = operation(a)["payload"] | {"weight_kg": "80.000000000000"}
        src = store.import_source(scope, "weight", str(uuid4()), "create", json.dumps(payload))
        wire = store.materialize(captured, src)
        assert wire["payload"]["weight_kg"] == "80"
        first_request = store.prepare_push(captured)
        store.close()
        store = SyncStore(path)
        assert store.prepare_push(captured) == first_request
        assert store.db.execute("SELECT count(*) FROM originals").fetchone()[0] == 3
        store.select(other)
        store.select(scope)
        with pytest.raises(ClientError, match="stale_context"):
            store.prepare_push(captured)
        with pytest.raises(ClientError, match="stale_context"):
            store.apply_pull(captured, pull_id, req, page)
        assert store.db.execute("SELECT state FROM wire_ops").fetchone()[0] == "sent"
    finally:
        store.close()
