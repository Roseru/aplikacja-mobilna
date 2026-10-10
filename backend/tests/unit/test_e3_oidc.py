import asyncio
import gzip
import json
from dataclasses import FrozenInstanceError

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, OIDCVerifier


@pytest.fixture(scope="module")
def material():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="first", alg="RS256", use="sig")
    return private, jwk


def settings(**changes):
    return Settings(
        database_url="postgresql+psycopg://unused@localhost/calorie_test",
        oidc_issuer="https://identity.example/realms/test",
        oidc_jwks_url="https://keys.example/certs",
        **changes,
    )


def signed(private, *, kid="first", headers=None, **changes):
    claims = {
        "iss": "https://identity.example/realms/test",
        "aud": ["calorie-api", "other"],
        "sub": "subject-a",
        "typ": "Bearer",
        "iat": 1000,
        "exp": 1300,
        "resource_access": {"calorie-api": {"roles": ["user"]}},
    }
    claims.update(changes)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid, **(headers or {})})


def run(coroutine):
    return asyncio.run(coroutine)


def verifier(material, *, clock=None, handler=None, **changes):
    clock = clock or [0]
    handler = handler or (lambda request: httpx.Response(200, json={"keys": [material[1]]}))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OIDCVerifier(
        settings(**changes), client=client, wall_clock=lambda: 1100, monotonic=lambda: clock[0]
    )


def test_valid_immutable_principal_and_only_api_roles(material):
    principal = run(verifier(material).verify(signed(material[0])))
    assert principal.issuer == "https://identity.example/realms/test"
    assert principal.subject == "subject-a"
    assert principal.roles == frozenset({"user"})
    with pytest.raises(FrozenInstanceError):
        principal.subject = "other"
    token = signed(
        material[0],
        resource_access={"calorie-android": {"roles": ["user", "admin"]}},
        realm_access={"roles": ["user"]},
    )
    assert not run(verifier(material).verify(token)).roles


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://other/realms/test"},
        {"aud": "calorie-android"},
        {"aud": True},
        {"sub": ""},
        {"sub": "   "},
        {"sub": None},
        {"exp": None},
        {"iat": None},
        {"exp": True},
        {"iat": "1000"},
        {"exp": float("inf")},
        {"iat": float("nan")},
        {"nbf": False},
        {"nbf": "1000"},
        {"nbf": 1160.001},
        {"iat": 1160.001, "exp": 1400},
        {"iat": 1000, "exp": 1000},
        {"iat": 1000, "exp": 1300.001},
        {"iat": 740, "exp": 1040},
        {"typ": "ID"},
        {"typ": None},
        {"resource_access": []},
        {"resource_access": {"calorie-api": {"roles": "user"}}},
    ],
)
def test_rejects_bad_claims_without_sensitive_error(material, changes):
    token = signed(material[0], **changes)
    with pytest.raises(AuthFailure) as error:
        run(verifier(material).verify(token))
    assert (error.value.status, error.value.code) == (401, "unauthorized")
    assert token not in str(error.value)


def test_missing_required_times_and_bad_signature(material):
    for name in ("iat", "exp"):
        claims = jwt.decode(signed(material[0]), options={"verify_signature": False})
        del claims[name]
        token = jwt.encode(claims, material[0], algorithm="RS256", headers={"kid": "first"})
        with pytest.raises(AuthFailure) as error:
            run(verifier(material).verify(token))
        assert error.value.status == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthFailure):
        run(verifier(material).verify(signed(other)))


def test_skew_boundary_optional_nbf(material):
    for changes in (
        {"iat": 1160, "exp": 1400, "nbf": 1160},
        {"iat": 740.001, "exp": 1040.001},
        {"iat": 1000, "exp": 1100, "nbf": 1000},
    ):
        assert run(verifier(material).verify(signed(material[0], **changes))).subject == "subject-a"


@pytest.mark.parametrize(
    "headers", [{"jku": "http://evil"}, {"x5u": "http://evil"}, {"crit": []}, {"kid": ""}]
)
def test_header_urls_and_invalid_kid_never_fetch(material, headers):
    requests = []
    instance = verifier(material, handler=lambda request: requests.append(request))
    with pytest.raises(AuthFailure):
        run(instance.verify(signed(material[0], headers=headers)))
    assert not requests


def test_wrong_algorithm_malformed_oversized_never_fetch(material):
    instance = verifier(material, handler=lambda request: pytest.fail("unexpected fetch"))
    for token in (
        "bad",
        "t" * 16385,
        jwt.encode({"sub": "a"}, "s" * 32, algorithm="HS256", headers={"kid": "first"}),
    ):
        with pytest.raises(AuthFailure) as error:
            run(instance.verify(token))
        assert error.value.status == 401


def test_refresh_singleflight_unknown_kid_bounded_memory_and_rotation(material):
    clock, requests = [0], []
    response = {"keys": [material[1]]}

    async def handler(request):
        requests.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=response)

    async def scenario():
        instance = verifier(material, clock=clock, handler=handler)
        await instance.verify(signed(material[0]))
        failures = await asyncio.gather(
            *(instance.verify(signed(material[0], kid=f"bad-{i}")) for i in range(100)),
            return_exceptions=True,
        )
        assert all(isinstance(item, AuthFailure) and item.status == 401 for item in failures)
        assert len(requests) == 1
        assert set(instance._keys) == {"first"}
        clock[0] = 5
        rotated = dict(material[1], kid="rotated")
        response["keys"] = [rotated]
        principals = await asyncio.gather(
            *(instance.verify(signed(material[0], kid="rotated")) for _ in range(30))
        )
        assert len(principals) == 30
        assert len(requests) == 2
        assert set(instance._keys) == {"rotated"}

    run(scenario())


def test_fresh_cache_survives_outage_expired_cache_fails_and_cooldown(material):
    clock, requests = [0], []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"keys": [material[1]]})
        raise httpx.ConnectError("provider down")

    async def scenario():
        instance = verifier(material, clock=clock, handler=handler)
        await instance.verify(signed(material[0]))
        clock[0] = 5
        with pytest.raises(AuthFailure) as unknown:
            await instance.verify(signed(material[0], kid="missing"))
        assert unknown.value.status == 503
        assert (await instance.verify(signed(material[0]))).subject == "subject-a"
        clock[0] = 900
        for _ in range(10):
            with pytest.raises(AuthFailure) as expired:
                await instance.verify(signed(material[0]))
            assert expired.value.status == 503 and expired.value.retry_after == 5
        assert len(requests) == 3

    run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "http://evil"}),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, headers={"content-length": "65537"}, content=b"{}"),
        httpx.Response(200, json={"keys": [{}] * 33}),
        httpx.Response(200, json={"keys": None}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(b"{}")),
    ],
)
def test_bounded_fetch_and_no_redirect(material, response):
    requests = []

    def handler(request):
        requests.append(request)
        return response

    with pytest.raises(AuthFailure) as error:
        run(verifier(material, handler=handler).verify(signed(material[0])))
    assert error.value.status == 503
    assert [str(request.url) for request in requests] == ["https://keys.example/certs"]


@pytest.mark.parametrize("keys", [[], [{"kty": "EC", "kid": "other", "alg": "ES256"}]])
def test_successful_jwks_without_matching_signing_key_returns_401(material, keys):
    with pytest.raises(AuthFailure) as error:
        run(
            verifier(
                material, handler=lambda request: httpx.Response(200, json={"keys": keys})
            ).verify(signed(material[0]))
        )
    assert error.value.status == 401


def test_total_fetch_deadline(material):
    async def handler(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"keys": [material[1]]})

    with pytest.raises(AuthFailure) as error:
        run(
            verifier(material, handler=handler, oidc_jwks_timeout_seconds=0.01).verify(
                signed(material[0])
            )
        )
    assert error.value.status == 503


@pytest.mark.parametrize(
    "changes",
    [
        {"oidc_allow_local_http": True},
        {"oidc_issuer": "http://127.0.0.1:8080/realms/test"},
        {"oidc_jwks_url": "https://user:password@keys.example/certs"},
        {"oidc_jwks_url": "https://keys.example/certs?untrusted=true"},
        {"oidc_jwks_url": "https://keys.example:invalid/certs"},
        {"oidc_jwks_url": "https://keys.example:0/certs"},
        {"oidc_jwks_cache_seconds": 901},
        {"oidc_jwks_timeout_seconds": 11},
    ],
)
def test_safe_configuration(changes):
    values = settings().model_dump()
    values.update(changes)
    with pytest.raises(ValidationError):
        Settings(**values)


def test_loopback_http_requires_isolated_environment():
    Settings(
        database_url="postgresql+psycopg://unused@localhost/calorie_test",
        environment="test",
        oidc_allow_local_http=True,
        oidc_issuer="http://127.0.0.1:8080/realms/calorie-dev",
        oidc_jwks_url="http://127.0.0.1:8080/realms/calorie-dev/protocol/openid-connect/certs",
    )
