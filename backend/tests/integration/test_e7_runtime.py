"""Real PG17/SCRAM, private storage and process transport; no live Google calls."""

import json
import os
import secrets
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.ai.service import create_analysis
from calorie_app.modules.ai.storage import PhotoStorage, _Windows
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.jobs.runner import Runner

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
METADATA = {
    "consent": {
        "accepted": True,
        "notice_version": "food-photo-notice-v1",
        "provider": "mock",
        "scope": "this_photo",
    }
}


def private_root(root):
    root.mkdir()
    if os.name == "nt":
        sid = _Windows().sid
        subprocess.run(
            [
                "icacls",
                str(root),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    else:
        root.chmod(0o700)
    return root


def role_engine(database, role):
    engine, _, url = database
    login = "e7_test_" + secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    with engine.begin() as connection:
        pg = connection.connection.driver_connection
        hashed = pg.pgconn.encrypt_password(
            password.encode(), login.encode(), b"scram-sha-256"
        ).decode()
        connection.exec_driver_sql(
            sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {}")
            .format(sql.Identifier(login), sql.Literal(hashed))
            .as_string(pg)
        )
        connection.exec_driver_sql(
            sql.SQL("GRANT {} TO {}")
            .format(sql.Identifier(role), sql.Identifier(login))
            .as_string(pg)
        )
        connection.exec_driver_sql(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}")
            .format(sql.Identifier(make_url(url).database), sql.Identifier(login))
            .as_string(pg)
        )
    parsed = make_url(url).set(username=login, password=password)
    runtime = create_engine(parsed, hide_parameters=True, pool_size=8)
    return runtime, login


@pytest.fixture
def e7(database, tmp_path):
    admin, _, url = database

    def clear():
        with admin.begin() as c:
            c.execute(
                text(
                    "TRUNCATE app.user_accounts,app.products,app.product_sources,"
                    "app.offline_packages,app.rations CASCADE"
                )
            )
            c.execute(
                text("TRUNCATE app.ai_cleanup_intents,app.ai_attempts,app.ai_transport_permits")
            )
            c.execute(
                text(
                    "INSERT INTO app.ai_transport_permits(environment,slot) "
                    "VALUES('local',1),('local',2)"
                )
            )
            c.execute(
                text(
                    "UPDATE app.ai_controls SET sync_epoch=(SELECT sync_epoch FROM "
                    "app.installation_state WHERE id=1),dispatch_open=true,closed_at=NULL"
                )
            )
            c.execute(
                text(
                    "UPDATE app.ai_pools SET rpm=100,tpm=1000000,rpd=10000,enabled=true "
                    "WHERE provider='mock'"
                )
            )

    clear()
    api, api_login = role_engine(database, "calorie_app_api")
    worker, worker_login = role_engine(database, "calorie_app_ai_worker")
    root = private_root(tmp_path / "private-photos")
    settings = Settings(database_url=url, environment="test", ai_photo_root=root)
    principals = [
        Principal("https://identity.e7.test", str(uuid4()), frozenset({"user"})) for _ in range(2)
    ]
    boots = []
    for principal in principals:
        with Session(api) as session, session.begin():
            boots.append(bootstrap(session, principal, uuid4()))
    state = {
        "admin": admin,
        "api": api,
        "worker": worker,
        "root": root,
        "settings": settings,
        "principals": principals,
        "boots": boots,
        "factory": lambda: Session(worker),
    }
    yield state
    api.dispose()
    worker.dispose()
    clear()
    with admin.begin() as c:
        for login in (api_login, worker_login):
            pg = c.connection.driver_connection
            c.exec_driver_sql(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
            )
            c.exec_driver_sql(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg))


def image():
    output = BytesIO()
    Image.new("RGB", (24, 18), "yellow").save(output, format="PNG")
    return output.getvalue()


def client(e7, who=0):
    app = create_app(e7["settings"], engine=e7["api"])
    app.dependency_overrides[current_principal] = lambda: e7["principals"][who]
    app.state.oidc_verifier.verify = AsyncMock(return_value=e7["principals"][who])
    return TestClient(app, headers={"Authorization": "Bearer synthetic-e7-test"})


def headers(e7, key=None, who=0):
    return {"Idempotency-Key": str(key or uuid4()), "X-Sync-Epoch": e7["boots"][who]["sync_epoch"]}


def create(e7, key=None):
    with client(e7) as http:
        response = http.post(
            "/api/v1/ai/food-analyses",
            headers=headers(e7, key),
            files={
                "metadata": (None, json.dumps(METADATA), "application/json"),
                "image": ("private-gps-name.png", image(), "image/png"),
            },
        )
    assert response.status_code == 202, response.json()
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def run(e7):
    return Runner(e7["worker"], e7["factory"], e7["settings"]).cycle()


def counts(e7):
    with e7["admin"].connect() as c:
        return {
            t: c.scalar(text("SELECT count(*) FROM app." + t))
            for t in (
                "ai_analyses",
                "ai_jobs",
                "ai_photo_consents",
                "ai_decisions",
                "ai_receipts",
                "ai_attempts",
                "meals",
                "product_drafts",
            )
        }


def test_actual_photo_worker_confirmation_and_standard_sync(e7):
    created = create(e7)
    assert counts(e7)["meals"] == 0
    assert PhotoStorage(e7["root"]).availability() and len(list(e7["root"].iterdir())) == 1
    assert run(e7) == 1
    assert list(e7["root"].iterdir()) == []
    path = "/api/v1/ai/food-analyses/" + created["analysis_id"]
    with client(e7) as http:
        found = http.get(path)
        assert found.status_code == 200, found.json()
        analysis = found.json()
        assert analysis["state"] == "succeeded", analysis
        item = analysis["proposal"]["items"][0]
        assert analysis["proposal"]["totals"]["energy_kcal"]["known_sum"] == "106.8"
        meal = json.loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
        meal["items"] = [
            {
                "item_id": str(uuid4()),
                "name": item["name"],
                "product": None,
                "quantity": item["quantity"],
                "basis_unit": item["basis_unit"],
                "nutrition_per_100": item["nutrition_per_100"],
                "density_g_per_ml": None,
                "density_source": None,
                "nutrition_origin": "ai_estimate",
                "formula_version": "nutrition_v1",
                "ration_component_position": None,
            }
        ]
        draft = {
            "name": item["name"],
            "brand": None,
            "variant": None,
            "basis_unit": item["basis_unit"],
            "nutrition_per_100": item["nutrition_per_100"],
            "package_quantity": item["quantity"],
            "density_g_per_ml": None,
            "density_source": None,
            "source_description": "AI mock: consciously approved estimate",
        }
        body = {
            "expected_revision": analysis["revision"],
            "meal": {"meal_id": str(uuid4()), "payload": meal},
            "drafts": [{"draft_id": str(uuid4()), "payload": draft}],
        }
        key = uuid4()
        response = http.post(path + "/confirm", headers=headers(e7, key), json=body)
        assert response.status_code == 200, response.json()
        confirmed = response.json()
        assert counts(e7)["meals"] == counts(e7)["product_drafts"] == 0
        assert http.post(path + "/confirm", headers=headers(e7, key), json=body).json() == confirmed
        assert http.post(path + "/confirm", headers=headers(e7), json=body).json() == confirmed
        push = json.loads(
            (ROOT / "contracts/examples/valid/sync-push-request.json").read_text(encoding="utf-8")
        )
        push["sync_epoch"] = e7["boots"][0]["sync_epoch"]
        checkpoint = http.get(
            "/api/v1/sync/pull", params={"sync_epoch": e7["boots"][0]["sync_epoch"]}
        )
        assert checkpoint.status_code == 200, checkpoint.json()
        push["checkpoint"] = checkpoint.json()["checkpoint"]
        push["operations"] = [
            {
                "operation_id": str(uuid4()),
                "entity_type": kind,
                "entity_id": template[id_field],
                "action": "upsert",
                "base_revision": None,
                "sync_epoch": push["sync_epoch"],
                "payload": template["payload"],
            }
            for kind, template, id_field in (
                ("product_draft", confirmed["drafts"][0], "draft_id"),
                ("meal", confirmed["meal"], "meal_id"),
            )
        ]
        ack = http.post("/api/v1/sync/push", json=push)
        assert ack.status_code == 200, ack.json()
        assert [result["status"] for result in ack.json()["results"]] == ["accepted", "accepted"]
        retried = http.post("/api/v1/sync/push", json=push)
        assert retried.status_code == 200, retried.json()
        assert [result["status"] for result in retried.json()["results"]] == [
            "already_applied",
            "already_applied",
        ]
        assert [result["entity_id"] for result in retried.json()["results"]] == [
            result["entity_id"] for result in ack.json()["results"]
        ]
        assert [result["revision"] for result in retried.json()["results"]] == [1, 1]
        # Publication is a separate conscious existing E6 operation after sync.
        published = http.post(
            "/api/v1/products",
            headers=headers(e7),
            json={
                "draft_id": confirmed["drafts"][0]["draft_id"],
                "draft_revision": 1,
                "source_kind": "ai",
                "source_description": "AI mock: approved estimate",
                "identity": item["identity"],
                "aliases": [],
                "confirm_new": True,
            },
        )
        assert published.status_code == 200, published.json()
        with e7["admin"].connect() as connection:
            assert connection.scalar(text("SELECT source_kind FROM app.community_versions")) == "ai"
    assert counts(e7)["meals"] == counts(e7)["product_drafts"] == 1
    assert counts(e7)["ai_decisions"] == 1


def test_create_replay_before_codec_staging_and_current_profile_change(e7):
    key = uuid4()
    original = create(e7, key)
    before = counts(e7)
    changed = e7["settings"].model_copy(update={"ai_mock_scenario": "null"})
    with (
        patch(
            "calorie_app.modules.ai.service.prepare_image",
            side_effect=AssertionError("codec replay"),
        ),
        patch.object(PhotoStorage, "activate", side_effect=AssertionError("file replay")),
    ):
        replay = create_analysis(
            e7["api"],
            e7["principals"][0],
            UUID(e7["boots"][0]["sync_epoch"]),
            key,
            METADATA,
            image(),
            changed,
        )
    assert replay.payload == original and replay.replayed
    assert counts(e7) == before
    with e7["admin"].begin() as c:
        c.execute(
            text("UPDATE app.ai_receipts SET created_at=clock_timestamp()-interval '61 days'")
        )
    with Session(e7["worker"]) as session, session.begin():
        session.execute(
            text("SELECT app.e7_prune_receipts(:owner)"),
            {"owner": UUID(e7["boots"][0]["account_id"])},
        )
    with patch(
        "calorie_app.modules.ai.service.prepare_image", side_effect=AssertionError("pruned codec")
    ):
        replay = create_analysis(
            e7["api"],
            e7["principals"][0],
            UUID(e7["boots"][0]["sync_epoch"]),
            key,
            METADATA,
            image(),
            changed,
        )
    assert replay.payload == original and counts(e7)["ai_jobs"] == 1


@pytest.mark.parametrize("consent", [None, False, "stale", "provider", "scope"])
def test_rejected_consent_never_codec_file_or_admission(e7, consent):
    body = json.loads(json.dumps(METADATA))
    if consent is None:
        body = {}
    elif consent is False:
        body["consent"]["accepted"] = False
    elif consent == "stale":
        body["consent"]["notice_version"] = "obsolete"
    elif consent == "provider":
        body["consent"]["provider"] = "gemini"
    else:
        body["consent"]["scope"] = "all_photos"
    with (
        client(e7) as http,
        patch(
            "calorie_app.modules.ai.service.prepare_image",
            side_effect=AssertionError("codec before consent"),
        ),
        patch.object(PhotoStorage, "activate", side_effect=AssertionError("file before consent")),
    ):
        response = http.post(
            "/api/v1/ai/food-analyses",
            headers=headers(e7),
            files=[
                ("image", ("first.png", image(), "image/png")),
                ("metadata", (None, json.dumps(body), "application/json")),
            ],
        )
    assert response.status_code == 422, response.json()
    assert response.headers["cache-control"] == "no-store"
    assert not list(e7["root"].iterdir())
    assert (
        counts(e7)["ai_jobs"] == counts(e7)["ai_photo_consents"] == counts(e7)["ai_attempts"] == 0
    )


@pytest.mark.parametrize("extra_role", [None, "admin", "catalog_moderator"])
def test_foreign_admin_has_same404_as_missing_and_cancel_fences(e7, extra_role):
    if extra_role:
        principal = e7["principals"][1]
        e7["principals"][1] = Principal(
            principal.issuer, principal.subject, frozenset({"user", extra_role})
        )
    created = create(e7)
    path = "/api/v1/ai/food-analyses/" + created["analysis_id"]
    with client(e7, 1) as http:
        missing = http.get("/api/v1/ai/food-analyses/" + str(uuid4()))
        foreign = http.get(path)
        assert missing.status_code == foreign.status_code == 404
        assert missing.json()["code"] == foreign.json()["code"] == "not_found"
    with client(e7) as http:
        response = http.post(path + "/cancel", headers=headers(e7), json={"expected_revision": 1})
        assert response.status_code == 200, response.json()
    run(e7)
    assert counts(e7)["ai_attempts"] == 0 and list(e7["root"].iterdir()) == []


def test_invalid_ai_provider_closes_photo_and_preserves_diary_readiness(e7):
    e7["settings"] = Settings(
        database_url=e7["settings"].database_url,
        environment="test",
        ai_provider="invalid-provider",
        ai_photo_root=e7["root"],
    )
    with client(e7) as http:
        assert http.get("/health/live").status_code == 200
        assert http.get("/health/ready").status_code == 200
        response = http.get("/api/v1/ai/capabilities")
        assert response.status_code == 503
        assert response.json()["code"] == "ai_configuration_invalid"
        assert response.headers["cache-control"] == "no-store"
    assert counts(e7)["ai_jobs"] == 0 and not list(e7["root"].iterdir())
