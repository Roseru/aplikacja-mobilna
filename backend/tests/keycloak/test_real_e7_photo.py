"""Actual Keycloak PKCE access tokens and minimal API LOGIN protect E7 photos."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_real_pkce import auth, tokens

from calorie_app.main import create_app

SPEC = importlib.util.spec_from_file_location(
    "real_e7_storage_fixtures", Path(__file__).parents[1] / "integration/test_e7_runtime.py"
)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
e7 = RUNTIME.e7


@pytest.fixture
def photo_api(e7, provider):
    issuer = provider[0]
    settings = e7["settings"].model_copy(
        update={
            "oidc_allow_local_http": True,
            "oidc_issuer": issuer,
            "oidc_jwks_url": issuer + "/protocol/openid-connect/certs",
        }
    )
    with TestClient(create_app(settings, engine=e7["api"])) as client:
        yield client


def boot(client, token):
    response = client.post(
        "/api/v1/me/bootstrap", headers=auth(token) | {"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 200
    return response.json()


def upload(client, token, account, key):
    return client.post(
        "/api/v1/ai/food-analyses",
        headers=auth(token)
        | {
            "Idempotency-Key": str(key),
            "X-Sync-Epoch": account["sync_epoch"],
        },
        files={
            "metadata": (None, json.dumps(RUNTIME.METADATA), "application/json"),
            "image": ("private.png", RUNTIME.image(), "image/png"),
        },
    )


def test_real_pkce_photo_accept_replay_cancel_and_id_token_denial(e7, provider, photo_api):
    issued = tokens(provider, "a")
    token = issued["access_token"]
    account = boot(photo_api, token)
    key = uuid4()
    accepted = upload(photo_api, token, account, key)
    assert accepted.status_code == 202, accepted.json()
    assert upload(photo_api, token, account, key).json() == accepted.json()
    denied = upload(photo_api, issued["id_token"], account, uuid4())
    assert denied.status_code == 401 and denied.headers["cache-control"] == "no-store"
    path = "/api/v1/ai/food-analyses/" + accepted.json()["analysis_id"]
    cancelled = photo_api.post(
        path + "/cancel",
        headers=auth(token)
        | {
            "Idempotency-Key": str(uuid4()),
            "X-Sync-Epoch": account["sync_epoch"],
        },
        json={"expected_revision": 1},
    )
    assert cancelled.status_code == 200, cancelled.json()
    assert RUNTIME.run(e7) == 0 and not list(e7["root"].iterdir())


@pytest.mark.parametrize("who", ["b", "moderator", "admin"])
def test_real_user_moderator_admin_cannot_read_confirm_or_cancel_foreign_photo(
    e7, provider, photo_api, who
):
    owner = tokens(provider, "a")["access_token"]
    account = boot(photo_api, owner)
    accepted = upload(photo_api, owner, account, uuid4())
    assert accepted.status_code == 202
    foreign = tokens(provider, who)["access_token"]
    other = boot(photo_api, foreign)
    path = "/api/v1/ai/food-analyses/" + accepted.json()["analysis_id"]
    found = photo_api.get(path, headers=auth(foreign))
    missing = photo_api.get("/api/v1/ai/food-analyses/" + str(uuid4()), headers=auth(foreign))
    assert found.status_code == missing.status_code == 404
    assert found.json()["code"] == missing.json()["code"] == "not_found"
    cancelled = photo_api.post(
        path + "/cancel",
        headers=auth(foreign)
        | {
            "Idempotency-Key": str(uuid4()),
            "X-Sync-Epoch": other["sync_epoch"],
        },
        json={"expected_revision": 1},
    )
    assert cancelled.status_code == 404
    assert cancelled.headers["cache-control"] == "no-store"
    confirmation = json.loads(
        (Path(__file__).parents[3] / "contracts/examples/e7/confirm.json").read_text(
            encoding="utf-8"
        )
    )
    confirmed = photo_api.post(
        path + "/confirm",
        headers=auth(foreign)
        | {
            "Idempotency-Key": str(uuid4()),
            "X-Sync-Epoch": other["sync_epoch"],
        },
        json=confirmation,
    )
    assert confirmed.status_code == 404 and confirmed.headers["cache-control"] == "no-store"
    assert RUNTIME.counts(e7)["ai_jobs"] == 1


@pytest.mark.parametrize("who", ["only_admin", "only_moderator"])
def test_real_privileged_role_without_user_cannot_reach_photo_parser(e7, provider, photo_api, who):
    token = tokens(provider, who)["access_token"]
    response = photo_api.post("/api/v1/ai/food-analyses", headers=auth(token), content=b"bad")
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert not list(e7["root"].iterdir())
