"""Real-service test gate: an absent provider or PostgreSQL is a failure, never a skip."""

import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import SecretStr

_spec = importlib.util.spec_from_file_location(
    "e3_postgres_fixtures", Path(__file__).parents[1] / "integration" / "conftest.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
database = _module.database
cursor_secret = _module.cursor_secret


@pytest.fixture(scope="session")
def provider():
    issuer = os.environ.get("E3_KEYCLOAK_ISSUER")
    credential_path = os.environ.get("E3_KEYCLOAK_CREDENTIALS")
    if not issuer or not credential_path:
        pytest.fail(
            "Real PKCE requires E3_KEYCLOAK_ISSUER and a local E3_KEYCLOAK_CREDENTIALS file"
        )
    parsed = urlsplit(issuer)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.path != "/realms/calorie-dev"
    ):
        pytest.fail("Real-service harness must use the isolated exact loopback calorie-dev issuer")
    with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
        try:
            response = client.get(issuer + "/.well-known/openid-configuration")
        except httpx.HTTPError:
            pytest.fail("Real Keycloak service is unavailable")
        assert response.status_code == 200, "Real Keycloak discovery did not succeed"
        discovery = response.json()
        assert discovery["issuer"] == issuer
        assert discovery["token_endpoint"] == issuer + "/protocol/openid-connect/token"
        assert discovery["jwks_uri"] == issuer + "/protocol/openid-connect/certs"
    try:
        raw_credentials = json.loads(Path(credential_path).read_text())
    except (OSError, ValueError):
        pytest.fail("Local ephemeral Keycloak credentials unavailable or invalid", pytrace=False)
    credentials = {
        who: {"username": values["username"], "password": SecretStr(values["password"])}
        for who, values in raw_credentials.items()
    }
    return issuer, credentials
