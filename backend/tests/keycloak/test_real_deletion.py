"""Only the disposable delete_a identity is removed from the ephemeral realm."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import jwt
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_real_pkce import api as api_fixture
from test_real_pkce import auth, decoded, tokens

from calorie_app.integrations.keycloak.admin import AdminFailure, KeycloakAdmin, RealmAdminConfig
from calorie_app.modules.catalog.export import export_package
from calorie_app.modules.catalog.service import import_catalog
from calorie_app.modules.identity.deletion import begin, resume, status

api = api_fixture


def admin_config(provider, client_id="calorie-deletion-operator"):
    secret_path = Path(os.environ["E3_KEYCLOAK_CREDENTIALS"]).with_name("admin-secrets.json")
    raw = json.loads(secret_path.read_text(encoding="utf-8"))
    return RealmAdminConfig(
        issuer=provider[0],
        admin_base_url=provider[0].removesuffix("/realms/calorie-dev"),
        realm="calorie-dev",
        client_id=client_id,
        client_secret=SecretStr(raw[client_id]),
        allow_local_http=True,
    )


def test_real_service_account_pkce_delete_confirmation_refresh_old_jwt_and_b_preserved(
    provider,
    api,
    database,
):
    engine, _, _ = database
    demo = json.loads(
        (Path(__file__).parents[2] / "data/demo/seed.json").read_text(encoding="utf-8")
    )
    import_catalog(engine, demo)
    catalog_before = export_package(engine, UUID(demo["package_id"]), 1)
    # A is its own disposable account, leaving the ordinary PKCE A/B fixtures.
    a, b = tokens(provider, "delete_a"), tokens(provider, "b")
    claims = decoded(a["access_token"])
    accounts = []
    for payload in (a, b):
        response = api.post(
            "/api/v1/me/bootstrap",
            headers={
                **auth(payload["access_token"]),
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert response.status_code == 200
        accounts.append(UUID(response.json()["account_id"]))
    b_before = api.get("/api/v1/me", headers=auth(b["access_token"])).json()
    operation = uuid4()
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
        begin(connection, accounts[0], operation, 1)
    denied_config = admin_config(provider, "calorie-deletion-denied")
    adapter = KeycloakAdmin([denied_config])
    try:
        try:
            resume(engine, operation, adapter)
        except AdminFailure:
            pass
        else:
            raise AssertionError("Underprivileged real service account unexpectedly confirmed")
    finally:
        adapter.close()
    with engine.begin() as connection:
        assert status(connection, operation)["identity_confirmed_at"] is None
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.online_receipts WHERE owner_id=:a"),
                {"a": accounts[0]},
            )
            > 0
        )
    config = admin_config(provider)
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        service = client.post(
            config.issuer + "/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config.client_id,
                "client_secret": config.client_secret.get_secret_value(),
            },
        )
        assert service.status_code == 200
        service_claims = jwt.decode(
            service.json()["access_token"], options={"verify_signature": False}
        )
        assert service_claims["resource_access"]["realm-management"]["roles"] == ["manage-users"]
        assert "realm-admin" not in service_claims["resource_access"]["realm-management"]["roles"]
        assert service_claims["iss"] == config.issuer
    adapter = KeycloakAdmin([config])
    try:
        committed = []

        def crash(stage):
            if stage == "provider_confirmed":
                committed.append(stage)
                raise RuntimeError("simulated provider response loss")

        try:
            resume(engine, operation, adapter, barrier=crash)
        except RuntimeError:
            pass
        assert committed == ["provider_confirmed"]
        result = resume(engine, operation, adapter)
        assert result["purged_at"] is not None
        assert result["subject"] == claims["sub"]
        assert (result["block_until"] - result["identity_confirmed_at"]).total_seconds() >= 420
        assert resume(engine, operation, adapter) == result
    finally:
        adapter.close()
    assert api.get("/api/v1/me", headers=auth(a["access_token"])).status_code == 403
    assert (
        api.post(
            "/api/v1/me/bootstrap",
            headers={
                **auth(a["access_token"]),
                "Idempotency-Key": str(uuid4()),
            },
        ).status_code
        == 403
    )
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        refreshed = client.post(
            provider[0] + "/protocol/openid-connect/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "calorie-pkce-harness",
                "refresh_token": a["refresh_token"].get_secret_value(),
            },
        )
        assert refreshed.status_code == 400
        assert refreshed.json()["error"] == "invalid_grant"
    try:
        tokens(provider, "delete_a")
    except AssertionError as error:
        assert str(error).startswith("Real user login failed")
    else:
        raise AssertionError("Deleted synthetic user can still log in")
    assert api.get("/api/v1/me", headers=auth(b["access_token"])).json() == b_before
    assert export_package(engine, UUID(demo["package_id"]), 1) == catalog_before
    with Session(engine) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM app.user_accounts WHERE id=:a"), {"a": accounts[0]}
            )
            == 0
        )
