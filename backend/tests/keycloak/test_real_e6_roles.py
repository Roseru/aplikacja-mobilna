"""Actual PKCE-issued client roles protect E6 moderation and private resources."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_real_pkce import api as api_fixture
from test_real_pkce import auth, decoded, tokens

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog.community.models import CommunityReceipt
from calorie_app.modules.identity.models import UserAccount
from tests.support.deletion_regression import begin_deleting

api = api_fixture


@pytest.mark.parametrize(
    ("who", "allowed", "base_user"),
    [
        ("a", False, True),
        ("moderator", True, True),
        ("admin", True, True),
        ("only_moderator", False, False),
        ("only_admin", False, False),
        ("wrong_client", False, True),
    ],
)
def test_actual_keycloak_roles_require_user_and_exact_api_client(
    provider, api, who, allowed, base_user
):
    token = tokens(provider, who)["access_token"]
    claims = decoded(token)
    api_roles = claims["resource_access"]["calorie-api"]["roles"]
    assert ("user" in api_roles) is base_user
    if who == "wrong_client":
        assert "catalog_moderator" not in api_roles and "admin" not in api_roles
        assert (
            "catalog_moderator" in claims["resource_access"]["calorie-wrong-role-client"]["roles"]
        )
    boot = api.post(
        "/api/v1/me/bootstrap", headers={**auth(token), "Idempotency-Key": str(uuid4())}
    )
    assert boot.status_code == (200 if base_user else 403)
    queue = api.get("/api/v1/moderation/reports", headers=auth(token))
    assert queue.status_code == (200 if allowed else 403)
    assert queue.headers["Cache-Control"] == "no-store"
    if allowed:
        assert isinstance(queue.json()["items"], list)
    private = api.get("/api/v1/me", headers=auth(token))
    assert private.status_code == (200 if base_user else 403)


@pytest.mark.parametrize("who", ["moderator", "admin"])
def test_real_moderator_or_admin_cannot_read_other_users_private_weight(provider, api, who):
    a = tokens(provider, "a")["access_token"]
    boot = api.post(
        "/api/v1/me/bootstrap", headers={**auth(a), "Idempotency-Key": str(uuid4())}
    ).json()
    checkpoint = api.get("/api/v1/sync/pull", headers=auth(a)).json()["checkpoint"]
    weight_id = str(uuid4())
    body = {
        "protocol_version": 1,
        "sync_epoch": boot["sync_epoch"],
        "checkpoint": checkpoint,
        "operations": [
            {
                "operation_id": str(uuid4()),
                "entity_type": "weight",
                "entity_id": weight_id,
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
        ],
    }
    saved = api.post("/api/v1/sync/push", json=body, headers=auth(a))
    assert saved.status_code == 200 and saved.json()["results"][0]["status"] == "accepted"
    query = {"from": "2026-10-10", "to": "2026-10-10"}
    own = api.get("/api/v1/me/weights", params=query, headers=auth(a))
    assert own.status_code == 200
    assert weight_id in {item["entity_id"] for item in own.json()["items"]}
    elevated = tokens(provider, who)["access_token"]
    elevated_boot = api.post(
        "/api/v1/me/bootstrap", headers={**auth(elevated), "Idempotency-Key": str(uuid4())}
    )
    assert elevated_boot.status_code == 200
    response = api.get("/api/v1/me/weights", params=query, headers=auth(elevated))
    assert response.status_code == 200
    assert weight_id not in {item["entity_id"] for item in response.json()["items"]}
    assert response.headers["Cache-Control"] == "no-store"
    spoof = api.get(
        "/api/v1/me/weights",
        params={**query, "owner_id": boot["account_id"]},
        headers=auth(elevated),
    )
    assert spoof.status_code == 422


def test_real_e6_access_token_tampered_signature_is_rejected(provider, api):
    token = tokens(provider, "moderator")["access_token"]
    parts = token.get_secret_value().split(".")
    signature = parts[2]
    parts[2] = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = SecretStr(".".join(parts))
    result = api.get("/api/v1/moderation/reports", headers=auth(tampered))
    assert result.status_code == 401
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("field", ["issuer", "audience"])
def test_real_e6_roles_cannot_bypass_wrong_issuer_or_audience(provider, database, field):
    token = tokens(
        provider,
        "moderator",
        client_id="calorie-pkce-android-only" if field == "audience" else "calorie-pkce-harness",
    )["access_token"]
    issuer = provider[0]
    settings = Settings(
        database_url=database[2],
        environment="test",
        oidc_allow_local_http=True,
        oidc_issuer=issuer + "-wrong" if field == "issuer" else issuer,
        oidc_jwks_url=issuer + "/protocol/openid-connect/certs",
        catalog_page_token_secret="e2" * 32,
    )
    with TestClient(create_app(settings, engine=database[0])) as client:
        result = client.get("/api/v1/moderation/reports", headers=auth(token))
    assert result.status_code == 401
    assert result.headers["Cache-Control"] == "no-store"


def test_real_moderator_new_mutation_with_old_epoch_denied_before_version(provider, api):
    token = tokens(provider, "moderator")["access_token"]
    boot = api.post(
        "/api/v1/me/bootstrap", headers={**auth(token), "Idempotency-Key": str(uuid4())}
    )
    assert boot.status_code == 200
    result = api.patch(
        f"/api/v1/moderation/products/{uuid4()}",
        headers={**auth(token), "Idempotency-Key": str(uuid4()), "X-Sync-Epoch": str(uuid4())},
        json={"expected_state_revision": 1, "visibility": "hidden", "reason": "synthetic test"},
    )
    assert result.status_code == 409 and result.json()["code"] == "sync_epoch_changed"


def test_real_e6_replay_checks_current_generation_and_deleting_before_receipt(
    provider, api, database
):
    token = tokens(provider, "e6_context")["access_token"]
    bootstrap = api.post(
        "/api/v1/me/bootstrap", headers={**auth(token), "Idempotency-Key": str(uuid4())}
    )
    assert bootstrap.status_code == 200
    boot = bootstrap.json()
    account_id = UUID(boot["account_id"])
    path = f"/api/v1/moderation/products/{uuid4()}"
    headers = {**auth(token), "Idempotency-Key": str(uuid4()), "X-Sync-Epoch": boot["sync_epoch"]}
    body = {"expected_state_revision": 1, "visibility": "hidden", "reason": "synthetic test"}
    original = api.patch(path, headers=headers, json=body)
    assert original.status_code == 404
    with Session(database[0]) as session, session.begin():
        row = session.get(UserAccount, account_id)
        previous = row.generation
        # Inject a historical receipt from another generation. The current
        # account lifecycle must only change through the ledger producer.
        receipt = session.scalar(
            select(CommunityReceipt).where(
                CommunityReceipt.owner_id == account_id,
                CommunityReceipt.operation_id == UUID(headers["Idempotency-Key"]),
            )
        )
        assert receipt is not None
        receipt.generation = previous + 1
    replay = api.patch(path, headers=headers, json=body)
    assert replay.status_code == 409 and replay.json()["code"] == "account_generation_changed"
    with Session(database[0]) as session, session.begin():
        row = begin_deleting(session, account_id)
        assert row.generation == previous + 1
    deleting_replay = api.patch(path, headers=headers, json=body)
    assert (
        deleting_replay.status_code == 403 and deleting_replay.json()["code"] == "account_deleting"
    )
    queue = api.get("/api/v1/moderation/reports", headers=auth(token))
    assert queue.status_code == 403 and queue.json()["code"] == "account_deleting"
