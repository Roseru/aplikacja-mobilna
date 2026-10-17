"""Owned signed read tokens reconcile epoch/generation through real HTTP/PG."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_e6_community_publication import community_db  # noqa: F401
from test_e6_feedback_moderation import actors, mutation, product

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog.community.feedback import create_report
from calorie_app.modules.catalog.community.schemas import ReportRequest
from calorie_app.modules.identity.dependencies import current_principal

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("endpoint", ["community", "reports"])
@pytest.mark.parametrize("changed", ["epoch", "generation"])
def test_owned_http_page_token_context_change409_no_payload(request, endpoint, changed):
    engine = request.getfixturevalue("community_db")
    a, b, _, mod = actors(engine)
    first = product(engine, a[1], a[0], a[2], "Context soup A")
    product(engine, b[1], b[0], b[2], "Context soup B")
    if endpoint == "reports":
        body = ReportRequest(
            product={"product_id": str(first), "revision": 1},
            reason="synthetic",
            description="context probe",
        )
        for _ in range(2):
            assert (
                mutation(
                    engine,
                    b[0],
                    b[2],
                    "report",
                    lambda s, a, k: create_report(s, a, first, body, k),
                ).error
                is None
            )
    actor = mod if endpoint == "reports" else a
    path = "/api/v1/moderation/reports" if endpoint == "reports" else "/api/v1/community/products"
    app = create_app(
        Settings(
            database_url=engine.url.render_as_string(hide_password=False),
            catalog_page_token_secret="e6" * 32,
        ),
        engine=engine,
    )
    app.dependency_overrides[current_principal] = lambda: actor[0]
    with TestClient(app) as client:
        page = client.get(path, params={"limit": 1})
        assert page.status_code == 200
        token = page.json()["next_page_token"]
        assert token
        with engine.begin() as connection:
            if changed == "epoch":
                connection.execute(
                    text("UPDATE app.installation_state SET sync_epoch=:e WHERE id=1"),
                    {"e": uuid4()},
                )
            else:
                # A correctly signed token from a different generation must fail
                # without granting a raw lifecycle mutation to the test actor.
                import json

                from calorie_app.modules.catalog.community.tokens import encode_page
                from calorie_app.modules.catalog.pagination import _decode

                claims = json.loads(_decode(token.split(".")[1]))
                token = encode_page(
                    claims | {"generation": claims["generation"] + 1},
                    app.state.catalog_page_token_secret,
                    kind="reports" if endpoint == "reports" else "community",
                )
        continuation = client.get(path, params={"limit": 1, "page_token": token})
        assert continuation.status_code == 409
        assert continuation.json()["code"] == (
            "sync_epoch_changed" if changed == "epoch" else "account_generation_changed"
        )
        assert continuation.headers["Cache-Control"] == "no-store"
        assert "items" not in continuation.json()


@pytest.fixture(autouse=True)
def restore_test_epoch(request):
    owned_db = request.getfixturevalue("community_db")
    with owned_db.connect() as connection:
        epoch = connection.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    yield
    with owned_db.begin() as connection:
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"), {"epoch": epoch}
        )
