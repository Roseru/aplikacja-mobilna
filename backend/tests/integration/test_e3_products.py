"""Authenticated official products keep their release across catalog publication."""

import copy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_catalog_delivery import catalog_db, synthetic_official  # noqa: F401

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.export import publish_package
from calorie_app.modules.catalog.product_pages import decode_page, encode_page, expiry_integer
from calorie_app.modules.catalog.service import import_catalog
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import bootstrap

pytestmark = pytest.mark.integration


@pytest.fixture
def product_api(request):
    engine, _, url = request.getfixturevalue("catalog_db")
    principal = Principal(
        "https://identity.test/realms/calorie-dev", str(uuid4()), frozenset({"user"})
    )
    app = create_app(Settings(database_url=url), engine=engine)
    app.dependency_overrides[current_principal] = lambda: principal
    with TestClient(app) as client:
        yield client, engine, app, principal
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")


def complete_products(release=1):
    value = synthetic_official(count=1, release=release)
    for index in range(2):
        product = copy.deepcopy(value["products"][0])
        product["product_id"] = str(uuid4())
        product["name"] = f"Osobny produkt {index}"
        value["products"].append(product)
    value["counts"]["products"] = 3
    return value


def register(client):
    response = client.post("/api/v1/me/bootstrap", headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.json()
    return response.json()


def test_consent_revision_exhaustion_matches_normative_error(product_api):
    from calorie_app.modules.diary.validation import _validator

    client, engine, _, _ = product_api
    owner = UUID(register(client)["account_id"])
    # Prepare a valid boundary record only in the guarded disposable test DB.
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM app.user_consents WHERE owner_id=:owner"), {"owner": owner}
        )
        connection.execute(
            text(
                "INSERT INTO app.user_consents "
                "(owner_id,revision,ranking,automatic_energy_adjustment) "
                "VALUES (:owner,2147483647,false,false)"
            ),
            {"owner": owner},
        )
    response = client.put(
        "/api/v1/me/consents",
        json={"ranking": True, "automatic_energy_adjustment": False},
        headers={"Idempotency-Key": str(uuid4()), "If-Match": '"2147483647"'},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "revision_exhausted"
    _validator("Error").validate(response.json())


def test_all_reads_require_bootstrap_and_forbidden_writes_absent(product_api):
    client, _, _, _ = product_api
    for url in (
        "/api/v1/me",
        "/api/v1/me/goals",
        "/api/v1/products",
        "/api/v1/products/" + str(uuid4()),
    ):
        response = client.get(url)
        assert response.status_code == 403
        assert response.json()["code"] == "account_bootstrap_required"
    data = {
        "age_years": 30,
        "height_cm": "180",
        "weight_kg": "80",
        "equation_variant": "plus_5",
        "activity_class": "line",
    }
    assert (
        client.post("/api/v1/energy-estimates", json=data).json()["code"]
        == "account_bootstrap_required"
    )
    assert (
        client.put(
            "/api/v1/me/consents",
            json={"ranking": False, "automatic_energy_adjustment": False},
            headers={"Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
        ).json()["code"]
        == "account_bootstrap_required"
    )
    for method, url in (
        ("PATCH", "/api/v1/me"),
        ("POST", "/api/v1/me/goals"),
        ("POST", "/api/v1/me/meals"),
        ("POST", "/api/v1/me/weights"),
    ):
        assert client.request(method, url, json={}).status_code in (404, 405)


def test_official_snapshot_filters_owner_ttl_and_exact_revision(product_api, tmp_path):
    client, engine, app, principal = product_api
    registration = register(client)
    assert client.get("/api/v1/products").json() == {"items": [], "next_page_token": None}
    value = complete_products()
    import_catalog(engine, value)
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    first = client.get("/api/v1/products?limit=1").json()
    token = first["next_page_token"]
    assert token.startswith("pp1.")
    newer = copy.deepcopy(value)
    newer["release"] = 2
    for product in newer["products"]:
        product["revision"] = 2
        product["nutrition_per_100"]["energy_kcal"] = "84"
    newer["rations"][0]["revision"] = 2
    newer["rations"][0]["components"][0]["product"]["revision"] = 2
    import_catalog(engine, newer)
    publish_package(engine, OFFICIAL_PACKAGE_ID, 2, tmp_path)
    seen = first["items"][:]
    while token:
        response = client.get("/api/v1/products", params={"limit": 1, "page_token": token})
        assert response.status_code == 200, response.json()
        seen.extend(response.json()["items"])
        token = response.json()["next_page_token"]
    assert len(seen) == 3 and all(p["revision"] == 1 for p in seen)
    assert [p["product_id"] for p in seen] == sorted(p["product_id"] for p in value["products"])
    assert all(p["revision"] == 2 for p in client.get("/api/v1/products").json()["items"])
    token = first["next_page_token"]
    assert (
        client.get("/api/v1/products", params={"limit": 2, "page_token": token}).status_code == 422
    )
    assert (
        client.get(
            "/api/v1/products", params={"limit": 1, "query": "fixture", "page_token": token}
        ).status_code
        == 422
    )
    other = Principal(principal.issuer, str(uuid4()), frozenset({"user", "admin"}))
    with Session(engine) as session, session.begin():
        bootstrap(session, other, uuid4())
    app.dependency_overrides[current_principal] = lambda: other
    assert (
        client.get("/api/v1/products", params={"limit": 1, "page_token": token}).status_code == 422
    )
    app.dependency_overrides[current_principal] = lambda: principal
    for needle in ("Baza testowa", "MARKA FIXTURE", "wersja testowa"):
        assert len(client.get("/api/v1/products", params={"query": needle}).json()["items"]) == 3
    pid = value["products"][0]["product_id"]
    assert (
        client.get(f"/api/v1/products/{pid}?revision=1").json()["nutrition_per_100"]["energy_kcal"]
        == "42"
    )
    assert client.get(f"/api/v1/products/{pid}").json()["revision"] == 2
    assert client.get(f"/api/v1/products/{pid}?revision=3").status_code == 404
    secret = app.state.catalog_page_token_secret
    now = datetime.now(UTC)
    decoded = decode_page(
        token,
        secret,
        owner=UUID(registration["account_id"]),
        generation=1,
        epoch=UUID(registration["sync_epoch"]),
        query=None,
        limit=1,
        now=now,
    )
    decoded["expiry"] = expiry_integer(now - timedelta(seconds=1))
    assert (
        client.get(
            "/api/v1/products", params={"limit": 1, "page_token": encode_page(decoded, secret)}
        ).status_code
        == 410
    )
    assert (
        client.get("/api/v1/products", params={"limit": 1, "page_token": token + "x"}).status_code
        == 422
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE app.user_accounts SET state='deleting',generation=2 WHERE id=:id"),
            {"id": UUID(registration["account_id"])},
        )
    assert (
        client.get("/api/v1/products", params={"limit": 1, "page_token": token}).json()["code"]
        == "account_deleting"
    )
