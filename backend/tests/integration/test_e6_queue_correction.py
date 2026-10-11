"""Canonical corrections invalidate moderator pages without rewriting reported history."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_e6_community_publication import community_db  # noqa: F401
from test_e6_feedback_moderation import actors, merge, mutation, product

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog.community.feedback import create_report
from calorie_app.modules.catalog.community.idempotency import execute_mutation
from calorie_app.modules.catalog.community.models import (
    CatalogState,
    CommunityAudit,
    CommunityProduct,
    CommunityReport,
)
from calorie_app.modules.catalog.community.schemas import ReportRequest
from calorie_app.modules.catalog.community.service import read_community
from calorie_app.modules.catalog.models import ProductVersion
from calorie_app.modules.catalog.moderation.schemas import ModerateProductRequest
from calorie_app.modules.catalog.moderation.service import moderate_product
from calorie_app.modules.identity.dependencies import current_principal

pytestmark = pytest.mark.integration
CORRECTION_FIELDS = (
    "name",
    "aliases",
    "identity",
    "basis_unit",
    "nutrition_per_100",
    "portion",
    "density",
    "source_kind",
    "source_description",
)


def case(engine, transitive):
    author, reporter, third, mod = actors(engine)
    source = product(engine, author[1], author[0], author[2], "Original reported recipe")
    report = ReportRequest(
        product={"product_id": str(source), "revision": 1},
        reason="nutrition",
        description="synthetic independent correction probe",
    )
    for _ in range(2):
        outcome = mutation(
            engine,
            reporter[0],
            reporter[2],
            "report",
            lambda session, account, operation: create_report(
                session, account, source, report, operation
            ),
        )
        assert outcome.error is None
    canonical, expected_state = source, 1
    if transitive:
        intermediate = product(engine, reporter[1], reporter[0], reporter[2], "Intermediate recipe")
        canonical = product(engine, third[1], third[0], third[2], "Canonical recipe")
        assert merge(engine, mod, source, intermediate).error is None
        assert merge(engine, mod, intermediate, canonical, source_revision=2).error is None
        expected_state = 2
    with Session(engine) as session, session.begin():
        previous = read_community(session, mod[0], canonical)
    correction = {field: previous[field] for field in CORRECTION_FIELDS}
    correction["name"] = "Corrected canonical recipe"
    correction["nutrition_per_100"] = correction["nutrition_per_100"] | {"energy_kcal": "210"}
    body = ModerateProductRequest.model_validate(
        {
            "expected_state_revision": expected_state,
            "reason": "synthetic source revision reviewed",
            "correction": correction,
        }
    )
    return mod, source, canonical, body


def client_app(engine, mod):
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://unused/isolated_test"),
        environment="test",
        catalog_page_token_secret=SecretStr("36" * 32),
    )
    app = create_app(settings, engine=engine)
    app.dependency_overrides[current_principal] = lambda: mod[0]
    return app


def versions(engine):
    with Session(engine) as session:
        state = session.get(CatalogState, 1)
        return state.revision, state.queue_revision


def old_history(engine):
    with Session(engine) as session:
        # Full exact old shared snapshot rows, including source IDs and sealed hashes.
        return session.execute(
            select(*ProductVersion.__table__.columns)
            .where(ProductVersion.revision == 1)
            .order_by(ProductVersion.product_id)
        ).all()


def durable_effects(engine, canonical):
    with Session(engine) as session:
        state = session.get(CommunityProduct, canonical)
        return (
            state.current_revision,
            state.state_revision,
            session.scalar(select(func.count()).select_from(ProductVersion)),
            session.scalar(select(func.count()).select_from(CommunityAudit)),
        )


def first_page(client, canonical, revision=1):
    response = client.get("/api/v1/moderation/reports", params={"limit": 1, "status": "open"})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    page = response.json()
    assert page["next_page_token"].startswith("mq1.")
    assert page["items"][0]["canonical_ref"] == {"product_id": str(canonical), "revision": revision}
    return page


def continuation(client, token):
    return client.get(
        "/api/v1/moderation/reports",
        params={
            "limit": 1,
            "status": "open",
            "page_token": token,
        },
    )


def assert_stale_page(client, token):
    response = continuation(client, token)
    assert response.status_code == 409
    assert response.json()["code"] == "moderation_queue_changed"
    assert "items" not in response.json()
    assert response.headers["Cache-Control"] == "no-store"


def assert_current_queue_keeps_reported_exact(client, source, canonical, revision):
    response = client.get("/api/v1/moderation/reports", params={"status": "open"})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    reports = response.json()["items"]
    assert len(reports) == 2
    for report in reports:
        assert report["product"] == {"product_id": str(source), "revision": 1}
        assert report["canonical_ref"] == {"product_id": str(canonical), "revision": revision}
        assert report["revision"] == 1 and report["status"] == "open"


@pytest.mark.parametrize("transitive", [False, True], ids=["direct", "A-to-B-to-C"])
def test_committed_canonical_correction_invalidates_http_queue_once(request, transitive):
    engine = request.getfixturevalue("community_db")
    mod, source, canonical, body = case(engine, transitive)
    history = old_history(engine)
    before = versions(engine)
    with TestClient(client_app(engine, mod)) as client:
        page = first_page(client, canonical)
        operation = uuid4()
        headers = {"Idempotency-Key": str(operation), "X-Sync-Epoch": str(mod[2])}
        path = f"/api/v1/moderation/products/{canonical}"
        corrected = client.patch(path, json=body.model_dump(mode="json"), headers=headers)
        assert corrected.status_code == 200
        assert corrected.json()["product"] == {"product_id": str(canonical), "revision": 2}
        assert_stale_page(client, page["next_page_token"])
        assert versions(engine) == (before[0] + 1, before[1] + 1)
        effects = durable_effects(engine, canonical)
        fresh = first_page(client, canonical, revision=2)
        assert_current_queue_keeps_reported_exact(client, source, canonical, 2)
        replay = client.patch(path, json=body.model_dump(mode="json"), headers=headers)
        assert replay.status_code == 200 and replay.json() == corrected.json()
        assert versions(engine) == (before[0] + 1, before[1] + 1)
        assert durable_effects(engine, canonical) == effects
        # A new key with old resource revision records a denial, not another bump.
        denied = client.patch(
            path,
            json=body.model_dump(mode="json"),
            headers={
                **headers,
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert denied.status_code == 409 and denied.json()["code"] == "product_state_conflict"
        assert denied.headers["Cache-Control"] == "no-store"
        assert versions(engine) == (before[0] + 1, before[1] + 1)
        assert durable_effects(engine, canonical) == effects
        assert continuation(client, fresh["next_page_token"]).status_code == 200
        exact = client.get(f"/api/v1/community/products/{source}", params={"revision": 1})
        assert exact.status_code == 200
        assert exact.json()["name"] == "Original reported recipe"
        assert exact.json()["nutrition_per_100"]["energy_kcal"] == "200"
    assert old_history(engine) == history


@pytest.mark.parametrize("transitive", [False, True], ids=["direct", "A-to-B-to-C"])
def test_denial_and_outer_rollback_preserve_queue_token_and_history(request, transitive):
    engine = request.getfixturevalue("community_db")
    mod, source, canonical, body = case(engine, transitive)
    history, before = old_history(engine), versions(engine)
    effects = durable_effects(engine, canonical)
    with TestClient(client_app(engine, mod)) as client:
        page = first_page(client, canonical)
        stale = body.model_dump(mode="json") | {"expected_state_revision": 99}
        denied = client.patch(
            f"/api/v1/moderation/products/{canonical}",
            json=stale,
            headers={
                "Idempotency-Key": str(uuid4()),
                "X-Sync-Epoch": str(mod[2]),
            },
        )
        assert denied.status_code == 409 and denied.json()["code"] == "product_state_conflict"
        assert versions(engine) == before
        assert durable_effects(engine, canonical) == effects
        operation = uuid4()
        with pytest.raises(RuntimeError, match="controlled rollback after queue bump"):
            with Session(engine) as session, session.begin():
                session.execute(text("SET LOCAL ROLE calorie_app_api"))
                outcome = execute_mutation(
                    session,
                    mod[0],
                    "moderate_product",
                    operation,
                    mod[2],
                    {
                        "method": "PATCH",
                        "target": str(canonical),
                        "body": body.model_dump(mode="json"),
                    },
                    lambda account: moderate_product(session, account, canonical, body, operation),
                )
                assert outcome.error is None
                state = session.get(CatalogState, 1)
                assert (state.revision, state.queue_revision) == (before[0] + 1, before[1] + 1)
                raise RuntimeError("controlled rollback after queue bump")
        assert versions(engine) == before
        assert durable_effects(engine, canonical) == effects
        valid = continuation(client, page["next_page_token"])
        assert valid.status_code == 200 and valid.headers["Cache-Control"] == "no-store"
        assert_current_queue_keeps_reported_exact(client, source, canonical, 1)
    assert old_history(engine) == history
    with Session(engine) as session:
        assert all(row.product_revision == 1 for row in session.scalars(select(CommunityReport)))
