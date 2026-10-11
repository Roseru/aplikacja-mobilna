"""HTTP boundary probes with real JWT verification, before database access."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from calorie_app.core.errors import DomainError
from calorie_app.modules.nemesis import service
from tests.support.e8_3_app import component_app
from tests.support.e8_3_jwt import SignedTokens


@pytest.fixture
def transport(monkeypatch):
    tokens = SignedTokens()
    calls = []

    def mutation(*args, **kwargs):
        calls.append((args, kwargs))
        raise DomainError(503, "nemesis_unavailable")

    monkeypatch.setattr(service, "mutate", mutation)
    monkeypatch.setattr(service, "read", mutation)
    monkeypatch.setattr(service, "statistics", mutation)
    with TestClient(component_app(object(), tokens.verifier)) as client:
        yield client, tokens, calls


def headers(tokens, **changes):
    return {
        "Authorization": "Bearer " + tokens.token("owner"),
        "X-Sync-Epoch": str(uuid4()),
        "Idempotency-Key": str(uuid4()),
    } | changes


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://wrong.example.test"},
        {"aud": "other"},
        {"typ": "ID"},
        {"exp": 1},
        {"roles": ("moderator",)},
        {"roles": ("admin",)},
    ],
)
def test_wrong_tokens_do_not_acquire_database(transport, claims):
    client, tokens, calls = transport
    result = client.post(
        "/api/v1/me/nemesis/share-code",
        headers={"Authorization": "Bearer " + tokens.token("owner", **claims)},
    )
    assert result.status_code in {401, 403}
    assert not calls
    assert result.headers["cache-control"] == "no-store"


def test_missing_or_forged_signature_denied(transport):
    client, tokens, calls = transport
    for auth in (None, "Bearer bad", "Bearer " + tokens.token("owner")[:-10] + "invalid"):
        result = client.post(
            "/api/v1/me/nemesis/share-code", headers={} if auth is None else {"Authorization": auth}
        )
        assert result.status_code == 401
        assert result.headers["cache-control"] == "no-store"
    assert not calls


@pytest.mark.parametrize(
    "header,value",
    [
        ("Idempotency-Key", "notuuid"),
        ("X-Sync-Epoch", "notuuid"),
        ("Idempotency-Key", "{" + str(uuid4()) + "}"),
    ],
)
def test_strict_headers_precede_database(transport, header, value):
    client, tokens, calls = transport
    result = client.post(
        "/api/v1/me/nemesis/share-code", headers=headers(tokens, **{header: value})
    )
    assert result.status_code == 422
    assert not calls


def test_duplicate_header_denied(transport):
    client, tokens, calls = transport
    h = list(headers(tokens).items()) + [("Idempotency-Key", str(uuid4()))]
    assert client.post("/api/v1/me/nemesis/share-code", headers=h).status_code == 422
    assert not calls


@pytest.mark.parametrize(
    "body",
    [
        b" " * 16385,
        b'{"destination_code":"PRIVATE", "terms":{}}',
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b"\xff",
    ],
)
def test_neutral_bounded_body_errors(transport, body):
    client, tokens, calls = transport
    result = client.post(
        "/api/v1/nemesis",
        headers=headers(tokens, **{"Content-Type": "application/json"}),
        content=body,
    )
    assert result.status_code in {413, 422}
    assert not calls
    assert "PRIVATE" not in result.text
    assert result.headers["cache-control"] == "no-store"


def test_unavailable_does_not_echo_auth_or_private_body(transport):
    client, tokens, calls = transport
    result = client.post("/api/v1/me/nemesis/share-code", headers=headers(tokens))
    assert result.status_code == 503 and len(calls) == 1
    assert result.headers["retry-after"] == "5"
    assert "Bearer" not in result.text


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=1&limit=2", "secret=x"])
def test_invalid_pagination_does_not_read_database(transport, query):
    client, tokens, calls = transport
    result = client.get("/api/v1/me/nemesis?" + query, headers=headers(tokens))
    assert result.status_code == 422 and not calls


def test_rate_limited_has_retry_after(transport, monkeypatch):
    client, tokens, _ = transport

    def refusal(*args, **kwargs):
        raise DomainError(429, "rate_limited")

    monkeypatch.setattr(service, "mutate", refusal)
    response = client.post("/api/v1/me/nemesis/share-code", headers=headers(tokens))
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/v1/nemesis/unknown/unrecognized", 404),
        ("PATCH", "/api/v1/nemesis", 405),
    ],
)
def test_private_factory_unknown_routes_are_safe_no_store(transport, method, path, expected):
    client, tokens, calls = transport
    response = client.request(method, path, headers=headers(tokens))
    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert not calls
