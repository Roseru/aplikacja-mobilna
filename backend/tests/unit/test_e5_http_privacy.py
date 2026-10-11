"""Cache protection includes OIDC and middleware failures before private routers."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure
from calorie_app.main import create_app

ROUTES = ("meals", "weights", "diary-days", "statistics")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("failure", (None, 401, 403, 503, 500))
def test_private_errors_never_cache(route, failure):
    app = create_app(Settings(database_url="postgresql+psycopg://unused@127.0.0.1:1/unused"))
    headers = {}
    expected = 401
    if failure is not None:
        headers["Authorization"] = "Bearer synthetic-private-token"
        expected = failure
        error = (
            RuntimeError("private payload")
            if failure == 500
            else AuthFailure(failure, "unauthorized")
        )
        app.state.oidc_verifier.verify = AsyncMock(side_effect=error)
    with TestClient(app) as client:
        response = client.get("/api/v1/me/" + route, headers=headers)
    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"
    assert "private payload" not in response.text
    assert "synthetic-private-token" not in response.text
