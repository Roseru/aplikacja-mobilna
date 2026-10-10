"""The sync protocol is exercised using actual PKCE-issued A/B tokens."""

from uuid import uuid4

from test_real_pkce import api as api_fixture
from test_real_pkce import auth, tokens

api = api_fixture


def test_real_pkce_sync_replay_and_a_b_checkpoint_isolation(provider, api):
    accounts = []
    for who in ("a", "b"):
        token = tokens(provider, who)["access_token"]
        boot = api.post(
            "/api/v1/me/bootstrap", headers={**auth(token), "Idempotency-Key": str(uuid4())}
        )
        assert boot.status_code == 200
        snapshot = api.get("/api/v1/sync/pull", headers=auth(token))
        assert snapshot.status_code == 200
        accounts.append((token, boot.json(), snapshot.json()))
    token, boot, snapshot = accounts[0]
    operation = {
        "operation_id": str(uuid4()),
        "entity_type": "weight",
        "entity_id": str(uuid4()),
        "action": "upsert",
        "base_revision": None,
        "sync_epoch": boot["sync_epoch"],
        "payload": {
            "weight_kg": "80",
            "occurred_at": "2026-10-10T10:00:00Z",
            "local_date": "2026-10-10",
            "time_zone": "Europe/Warsaw",
        },
    }
    body = {
        "protocol_version": 1,
        "sync_epoch": boot["sync_epoch"],
        "checkpoint": snapshot["checkpoint"],
        "operations": [operation],
    }
    accepted = api.post("/api/v1/sync/push", json=body, headers=auth(token))
    assert accepted.status_code == 200, accepted.text
    replay = api.post("/api/v1/sync/push", json=body, headers=auth(token))
    assert replay.status_code == 200 and replay.json()["results"][0]["status"] == "already_applied"
    other = api.post("/api/v1/sync/push", json=body, headers=auth(accounts[1][0]))
    assert other.status_code == 422 and other.json()["code"] == "invalid_sync_token"
    assert not api.get("/api/v1/sync/pull", headers=auth(accounts[1][0])).json()["entities"]
