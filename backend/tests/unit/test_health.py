import json
import logging
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from calorie_app.core.config import Settings
from calorie_app.main import create_app


def settings():
    return Settings(database_url="postgresql+psycopg://unused:secret@127.0.0.1:1/not_connected")


@pytest.fixture
def client():
    with TestClient(create_app(settings())) as client:
        yield client


def test_live_works_with_database_down(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["x-request-id"])


def test_ready_with_database_down_has_safe_error(client):
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "code": "service_unavailable",
        "message": "Baza nie jest gotowa.",
        "details": [],
        "request_id": response.headers["x-request-id"],
    }
    assert "secret" not in response.text


def test_not_found_and_request_id(client):
    request_id = str(uuid4())
    response = client.get("/not-implemented", headers={"X-Request-ID": request_id})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert response.json()["request_id"] == request_id
    assert response.headers["x-request-id"] == request_id


def test_invalid_request_id_is_replaced(client):
    response = client.get("/health/live", headers={"X-Request-ID": "untrusted text"})
    UUID(response.headers["x-request-id"])


def test_unexpected_error_and_logs_do_not_echo_secrets(caplog):
    app = create_app(settings())

    @app.get("/test-failure")
    def fail():
        raise RuntimeError("password=private-test-value")

    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="calorie_app"):
        response = client.get("/test-failure?token=private-test-value")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "private-test-value" not in response.text
    assert "private-test-value" not in caplog.text


def test_error_preserves_auth_challenge_and_retry_after():
    app = create_app(settings())

    @app.get("/test-auth")
    def auth():
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})

    @app.get("/test-limit")
    def limit():
        raise HTTPException(429, headers={"Retry-After": "60"})

    with TestClient(app) as client:
        assert client.get("/test-auth").headers["www-authenticate"] == "Bearer"
        response = client.get("/test-limit")
        assert response.json()["code"] == "rate_limited"
        assert response.headers["retry-after"] == "60"


@pytest.mark.parametrize("url", ["sqlite://", "not-a-url", "postgresql://localhost/db"])
def test_configuration_rejects_other_drivers(url):
    with pytest.raises(ValidationError):
        Settings(database_url=url)


def test_generated_api_only_claims_implemented_operations(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/health/live",
        "/health/ready",
        "/api/v1/rations",
        "/api/v1/rations/{id}",
        "/api/v1/offline-package/manifest",
        "/api/v1/offline-package/{filename}",
    }
    assert "/api/v1/products" not in schema["paths"]
    assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]
    # The committed artifact must equal the generated contract.
    from pathlib import Path

    expected = Path(__file__).resolve().parents[2] / "openapi.json"
    assert schema == json.loads(expected.read_text(encoding="utf-8"))
