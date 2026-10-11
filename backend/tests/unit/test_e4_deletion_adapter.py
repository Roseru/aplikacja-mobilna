import asyncio
import json
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, OIDCVerifier
from calorie_app.integrations.keycloak.admin import AdminFailure, KeycloakAdmin, RealmAdminConfig

ISSUER = "https://id.test/realms/synthetic"


def configuration(**updates):
    return RealmAdminConfig(
        **(
            {
                "issuer": ISSUER,
                "admin_base_url": "https://id.test",
                "realm": "synthetic",
                "client_id": "delete-operator",
                "client_secret": SecretStr("synthetic-secret"),
            }
            | updates
        )
    )


@pytest.mark.parametrize("issuer", [ISSUER + "/", ISSUER + "?x=1", "https://evil/realms/synthetic"])
def test_exact_trust_mapping(issuer):
    with pytest.raises(ValueError):
        configuration(issuer=issuer)


@pytest.mark.parametrize("phase", ["token", "probe", "before", "delete", "after"])
@pytest.mark.parametrize("denied", [401, 403, 500, 302])
def test_no_untrusted_absence_or_transport_status_is_confirmation(phase, denied):
    subject, calls = str(uuid4()), []

    def handler(request):
        current = (
            "token"
            if request.url.path.endswith("/token")
            else "probe"
            if request.url.path.endswith("/users")
            else "delete"
            if request.method == "DELETE"
            else "before"
            if "before" not in calls
            else "after"
        )
        calls.append(current)
        if current == phase:
            return httpx.Response(denied)
        if current == "token":
            return httpx.Response(200, json={"access_token": "synthetic"})
        if current == "probe":
            return httpx.Response(200, json=[])
        if current == "before":
            return httpx.Response(200, json={"id": subject})
        return httpx.Response(204 if current == "delete" else 404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdminFailure):
            KeycloakAdmin([configuration()], client=client).delete_and_confirm(ISSUER, subject)


def test_retry_after_provider_delete_confirms_authorized_absence():
    subject, calls = str(uuid4()), []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic"})
        if request.url.path.endswith("/users"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = KeycloakAdmin([configuration()], client=client)
        adapter.delete_and_confirm(ISSUER, subject)
        with pytest.raises(AdminFailure, match="unconfigured"):
            adapter.delete_and_confirm(ISSUER + "/", subject)
    assert len(calls) == 4 and not any(method == "DELETE" for method, _ in calls)


def test_arbitrary_404_from_probe_is_not_absence_confirmation():
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic"})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdminFailure):
            KeycloakAdmin([configuration()], client=client).delete_and_confirm(ISSUER, str(uuid4()))


@pytest.mark.parametrize("offset,valid", [(0, True), (360, True), (419.999, True), (420, False)])
def test_future_iat_max_lifetime_and_skew_require_full_420_second_fence(offset, valid):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key())) | {"kid": "clock"}
    cut = 2000
    claims = {
        "iss": ISSUER,
        "aud": "calorie-api",
        "sub": str(uuid4()),
        "typ": "Bearer",
        "iat": cut + 60,
        "exp": cut + 360,
        "resource_access": {"calorie-api": {"roles": ["user"]}},
    }
    token = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "clock"})

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk]}))
        ) as client:
            verifier = OIDCVerifier(
                Settings(
                    database_url="postgresql+psycopg://unused@localhost/calorie_test",
                    oidc_issuer=ISSUER,
                    oidc_jwks_url="https://id.test/certs",
                ),
                client=client,
                wall_clock=lambda: cut + offset,
            )
            if valid:
                assert (await verifier.verify(token)).subject == claims["sub"]
            else:
                with pytest.raises(AuthFailure):
                    await verifier.verify(token)

    asyncio.run(scenario())
