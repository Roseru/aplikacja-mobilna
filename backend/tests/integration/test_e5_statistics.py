"""PostgreSQL17 + runtime-role HTTP statistics and shared resolver regressions."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, Principal
from calorie_app.main import create_app
from calorie_app.modules.analytics import service
from calorie_app.modules.analytics.repository import window_inputs
from calorie_app.modules.analytics.router import router
from calorie_app.modules.diary.models import Meal, Weight
from calorie_app.modules.diary.repository import day_for_date
from calorie_app.modules.diary.service import (
    delete_entity,
    save_diary_day,
    save_meal,
    save_weight,
)
from calorie_app.modules.identity.service import begin_deleting
from calorie_app.modules.profiles.schemas import GoalPayload, ProfilePayload
from calorie_app.modules.profiles.service import (
    create_goal,
    goal_for_date,
    goal_for_dates,
    save_profile,
)

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
AS_OF = datetime(2026, 10, 11, 10, tzinfo=UTC)


def example(name):
    return json.loads((ROOT / f"contracts/examples/valid/{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def api(database, monkeypatch):
    engine, _, url = database
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    runtime = create_engine(
        url, hide_parameters=True, connect_args={"options": "-c role=calorie_app_api"}
    )
    app = create_app(
        Settings(
            database_url=url, environment="test", catalog_page_token_secret=SecretStr("e5" * 32)
        ),
        engine=runtime,
    )
    if "/api/v1/me/statistics" not in app.openapi()["paths"]:
        app.include_router(router)
    principals = {
        token: Principal("https://analytics.test/realm", str(uuid4()), roles)
        for token, roles in [
            ("a", frozenset({"user"})),
            ("b", frozenset({"user"})),
            ("admin", frozenset({"admin"})),
            ("moderator", frozenset({"catalog_moderator"})),
        ]
    }

    async def verify(token):
        if token not in principals:
            raise AuthFailure(401, "unauthorized")
        return principals[token]

    monkeypatch.setattr(app.state.oidc_verifier, "verify", verify)
    monkeypatch.setattr(service, "database_now", lambda session: AS_OF)
    with TestClient(app) as client:
        owners = {}
        for token in ("a", "b"):
            response = client.post(
                "/api/v1/me/bootstrap",
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
            )
            assert response.status_code == 200, response.text
            owners[token] = UUID(response.json()["account_id"])
        yield client, engine, runtime, owners
    runtime.dispose()
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))


def profile(engine, owner, zone="Europe/Warsaw"):
    with Session(engine) as session, session.begin():
        return save_profile(
            session,
            owner,
            uuid4(),
            ProfilePayload.model_validate(example("profile") | {"time_zone": zone}),
        ).id


def meal(engine, owner, day="2026-10-09", energy="100", protein="10", declared=True):
    entity = uuid4()
    payload = example("meal")
    payload.update(local_date=day, occurred_at=day + "T06:00:00Z")
    payload["items"][0]["quantity"]["amount"] = "100"
    payload["items"][0]["nutrition_per_100"].update(energy_kcal=energy, protein_g=protein)
    with Session(engine) as session, session.begin():
        save_meal(session, owner, entity, payload)
        if declared:
            row = day_for_date(session, owner, date.fromisoformat(day))
            save_diary_day(
                session,
                owner,
                row.id,
                {"local_date": day, "time_zone": "Europe/Warsaw", "declared_complete": True},
                base_revision=row.revision,
            )
    return entity


def goal(engine, owner, revision=0, **changes):
    entity = uuid4()
    with Session(engine) as session, session.begin():
        create_goal(
            session,
            owner,
            entity,
            GoalPayload.model_validate(
                example("goal")
                | {"timeline_base_revision": revision, "energy_kcal": "100"}
                | changes
            ),
        )
    return entity


def get(client, days=7, token="a"):
    return client.get(
        "/api/v1/me/statistics", params={"days": days}, headers={"Authorization": f"Bearer {token}"}
    )


@pytest.mark.parametrize("days", [7, 30, 90])
def test_real_http_empty_statistics_window(api, days):
    client, engine, _, owners = api
    profile(engine, owners["a"])
    response = get(client, days)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["daily"]) == days
    assert result["to"] == "2026-10-11"
    assert result["averages"]["energy_kcal"] == {"value": None, "day_count": 0}
    assert result["daily"][-1]["closed"] is False
    assert result["account_id"] == str(owners["a"])


@pytest.mark.parametrize("days", ["07", 0, 1, 91, "no", 7.5])
def test_real_http_invalid_days(api, days):
    client, *_ = api
    assert get(client, days).status_code == 422


def test_live_profile_required_and_owner_isolation(api):
    client, engine, _, owners = api
    response = get(client)
    assert response.status_code == 409 and response.json()["code"] == "profile_required"
    profile(engine, owners["a"])
    meal(engine, owners["a"])
    profile(engine, owners["b"])
    assert get(client).json()["complete_day_count"] == 1
    b = get(client, token="b").json()
    assert b["days_with_meals"] == 0
    assert b["averages"]["energy_kcal"]["value"] is None


@pytest.mark.parametrize("token,status", [("admin", 403), ("moderator", 403), ("invalid", 401)])
def test_privileged_or_invalid_principal_has_no_diary_access(api, token, status):
    client, *_ = api
    response = get(client, token=token)
    assert response.status_code == status
    assert "daily" not in response.json()


def test_complete_fields_denominators_and_preliminary(api):
    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    goal(engine, owner, effective_from="2026-10-08", decided_at="2026-10-08T06:00:00Z")
    meal(engine, owner, "2026-10-09", energy="90", protein=None)
    meal(engine, owner, "2026-10-10", energy="110", protein="0")
    meal(engine, owner, "2026-10-11", energy="100", protein="99")
    result = get(client).json()
    assert result["complete_day_count"] == 2
    assert result["in_goal_day_count"] == 2 and result["goal_eligible_day_count"] == 2
    assert result["averages"]["energy_kcal"] == {"value": "100", "day_count": 2}
    assert result["averages"]["protein_g"] == {"value": "0", "day_count": 1}
    assert result["daily"][-1]["preliminary_in_goal"] is True
    assert result["daily"][-1]["in_goal"] is None


@pytest.mark.parametrize("energy", [None, "0"])
def test_unknown_or_zero_energy_excludes_day(api, energy):
    client, engine, _, owners = api
    profile(engine, owners["a"])
    meal(engine, owners["a"], energy=energy)
    result = get(client).json()
    assert result["daily"][4]["status"] == "incomplete"
    assert result["averages"]["protein_g"]["day_count"] == 0
    assert result["daily"][4]["totals"]["energy_kcal"]["known_sum"] == energy


def test_last_meal_tombstone_revokes_declared_completeness(api):
    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    entity = meal(engine, owner)
    assert get(client).json()["complete_day_count"] == 1
    with Session(engine) as session, session.begin():
        delete_entity(session, Meal, owner, entity, base_revision=1)
    day = get(client).json()["daily"][4]
    assert day["declared_complete"] and not day["effective_complete"]
    assert day["status"] == "no_data" and day["totals"]["energy_kcal"]["known_sum"] is None


def test_daily_actual_weights_order_and_negative_change(api):
    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    ids = [
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
        uuid4(),
    ]
    with Session(engine) as session, session.begin():
        for entity, day, kg in [
            (ids[0], "2026-10-09", "80"),
            (ids[1], "2026-10-09", "79"),
            (ids[2], "2026-10-10", "78"),
        ]:
            save_weight(
                session,
                owner,
                entity,
                example("weight")
                | {"local_date": day, "occurred_at": day + "T07:00:00Z", "weight_kg": kg},
            )
    result = get(client).json()
    assert result["daily"][4]["latest_weight"]["entity_id"] == str(ids[1])
    assert result["weight"] == {
        "observation_count": 3,
        "day_count": 2,
        "first_date": "2026-10-09",
        "last_date": "2026-10-10",
        "change_kg": "-1",
    }
    with Session(engine) as session, session.begin():
        delete_entity(session, Weight, owner, ids[2], base_revision=1)
    assert get(client).json()["weight"]["change_kg"] is None


def test_historical_goal_moved_and_branched_corrections(api):
    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    root = goal(engine, owner, effective_from="2026-10-05", decided_at="2026-10-05T06:00:00Z")
    left = goal(
        engine,
        owner,
        1,
        effective_from="2026-10-09",
        energy_kcal="200",
        reason="history_correction",
        correction_of=str(root),
    )
    goal(
        engine,
        owner,
        2,
        effective_from="2026-10-10",
        energy_kcal="300",
        reason="history_correction",
        correction_of=str(root),
    )
    head = goal(
        engine,
        owner,
        3,
        effective_from="2026-10-08",
        energy_kcal="400",
        reason="history_correction",
        correction_of=str(left),
    )
    result = get(client).json()
    assert result["goal_timeline_revision"] == 4
    assert result["daily"][2]["goal"] is None
    assert result["daily"][3]["goal"]["entity_id"] == str(head)
    assert result["daily"][5]["goal"]["energy_kcal"] == "400"
    with Session(engine) as session, session.begin():
        old = goal_for_dates(session, owner, [date(2026, 10, 6), date(2026, 10, 10)], 1)
        assert old[date(2026, 10, 6)].id == root
        assert goal_for_date(session, owner, date(2026, 10, 10), 2).id == left


@pytest.mark.parametrize("days", [7, 90])
def test_goal_graph_query_count_constant_across_windows(api, days):
    client, engine, runtime, owners = api
    profile(engine, owners["a"])
    goal(engine, owners["a"])
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM app.goal_versions" in statement:
            statements.append(statement)

    event.listen(runtime, "before_cursor_execute", capture)
    try:
        response = get(client, days)
        assert response.status_code == 200, response.text
    finally:
        event.remove(runtime, "before_cursor_execute", capture)
    assert len(statements) == 1


def test_statistics_row_resource_limit_returns_safe_http_error(api, monkeypatch):
    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    meal(engine, owner)
    monkeypatch.setattr(
        service,
        "window_inputs",
        lambda session, owner, start, end: window_inputs(session, owner, start, end, maximum=1),
    )
    response = get(client)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "statistics_resource_limit"
    assert response.json()["details"] == []


def test_goal_graph_resource_limit_returns_safe_http_error(api, monkeypatch):
    client, engine, _, owners = api
    profile(engine, owners["a"])
    goal(engine, owners["a"])
    goal(engine, owners["a"], 1)
    monkeypatch.setattr(
        service,
        "goal_for_dates",
        lambda session, owner, days, revision: goal_for_dates(
            session, owner, days, revision, max_versions=1
        ),
    )
    response = get(client)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "statistics_resource_limit"


def test_deleting_account_refuses_statistics(api):
    client, engine, _, owners = api
    profile(engine, owners["a"])
    meal(engine, owners["a"])
    with Session(engine) as session, session.begin():
        begin_deleting(session, owners["a"])
    response = get(client)
    assert response.status_code == 403 and response.json()["code"] == "account_deleting"
    assert "daily" not in response.json()


@pytest.mark.parametrize(
    "zone,as_of,today",
    [
        ("America/Los_Angeles", datetime(2026, 10, 11, 0, 30, tzinfo=UTC), "2026-10-10"),
        ("Europe/Warsaw", datetime(2026, 10, 25, 0, 30, tzinfo=UTC), "2026-10-25"),
        ("Europe/Warsaw", datetime(2026, 10, 25, 1, 30, tzinfo=UTC), "2026-10-25"),
    ],
)
def test_http_profile_midnight_dst_anchor(api, monkeypatch, zone, as_of, today):
    client, engine, _, owners = api
    profile(engine, owners["a"], zone)
    monkeypatch.setattr(service, "database_now", lambda session: as_of)
    result = get(client).json()
    assert result["to"] == today and result["time_zone"] == zone
    assert result["daily"][-1]["closed"] is False


def test_statistics_holds_coherent_profile_goal_diary_while_writer_waits(api, monkeypatch):
    client, engine, _, owners = api
    owner = owners["a"]
    profile_id = profile(engine, owner)
    meal_id = meal(engine, owner)
    entered, release, attempted = Event(), Event(), Event()
    original = service.window_inputs

    def barrier_inputs(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(service, "window_inputs", barrier_inputs)

    writer_name = "e5-stat-writer-" + str(uuid4())
    writer_engine = create_engine(engine.url, connect_args={"application_name": writer_name})

    def change():
        attempted.set()
        with Session(writer_engine) as session, session.begin():
            save_profile(
                session,
                owner,
                profile_id,
                ProfilePayload.model_validate(
                    example("profile") | {"time_zone": "America/Los_Angeles"}
                ),
                base_revision=1,
            )
            create_goal(
                session,
                owner,
                uuid4(),
                GoalPayload.model_validate(example("goal") | {"energy_kcal": "50"}),
            )
            payload = example("meal")
            payload["items"][0]["quantity"]["amount"] = "100"
            payload["items"][0]["nutrition_per_100"]["energy_kcal"] = "50"
            save_meal(session, owner, meal_id, payload, base_revision=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(get, client)
        assert entered.wait(10)
        writer = pool.submit(change)
        assert attempted.wait(10)
        # Observe the actual PG row-lock wait before releasing the controlled
        # reader barrier; elapsed time alone is not evidence of concurrency.
        deadline = monotonic() + 5
        try:
            while True:
                with engine.connect() as observer:
                    waiting = observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE application_name=:name "
                            "AND wait_event_type='Lock'"
                        ),
                        {"name": writer_name},
                    )
                if waiting:
                    break
                assert monotonic() < deadline, "writer never reached its actual account lock"
                attempted.wait(0.01)
        finally:
            release.set()
        response = reader.result(timeout=10)
        writer.result(timeout=10)
    writer_engine.dispose()
    assert response.status_code == 200, response.text
    assert response.json()["time_zone"] == "Europe/Warsaw"
    assert response.json()["profile_revision"] == 1
    assert response.json()["complete_day_count"] == 1
    assert response.json()["daily"][4]["goal"] is None
    assert response.json()["daily"][4]["totals"]["energy_kcal"]["known_sum"] == "100"
    changed = get(client).json()
    assert changed["time_zone"] == "America/Los_Angeles"
    assert changed["daily"][4]["goal"]["energy_kcal"] == "50"
    assert changed["daily"][4]["totals"]["energy_kcal"]["known_sum"] == "50"


def test_real_http_density_conversion_and_high_precision_sum(api):
    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    payload = example("meal")
    payload["items"][0]["quantity"] = {"amount": "50", "unit": "ml"}
    payload["items"][0]["nutrition_per_100"]["energy_kcal"] = "200"
    payload["items"][0]["density_g_per_ml"] = "1.2"
    payload["items"][0]["density_source"] = "saved label density"
    entity = uuid4()
    with Session(engine) as session, session.begin():
        save_meal(session, owner, entity, payload)
        day = day_for_date(session, owner, date(2026, 10, 9))
        save_diary_day(session, owner, day.id, example("diary-day"), base_revision=1)
    result = get(client).json()
    assert result["daily"][4]["totals"]["energy_kcal"]["known_sum"] == "120"
    assert result["averages"]["energy_kcal"]["value"] == "120"
    payload["items"][0]["quantity"] = {"amount": "0.000001", "unit": "g"}
    payload["items"][0]["nutrition_per_100"]["energy_kcal"] = "0.000001"
    payload["items"][0]["density_g_per_ml"] = None
    payload["items"][0]["density_source"] = None
    with Session(engine) as session, session.begin():
        save_meal(session, owner, entity, payload, base_revision=1)
    response = get(client)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["daily"][4]["totals"]["energy_kcal"]["known_sum"] == "0.00000000000001"
    assert result["daily"][4]["effective_complete"] is True
    assert result["averages"]["energy_kcal"]["value"] == "0"


def test_density_missing_conversion_rejected_then_statistics_unchanged(api):
    from calorie_app.core.errors import DomainError

    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    payload = example("meal")
    payload["items"][0]["quantity"]["unit"] = "ml"
    with Session(engine) as session, session.begin(), pytest.raises(DomainError):
        save_meal(session, owner, uuid4(), payload)
    assert get(client).json()["days_with_meals"] == 0


def test_catalog_new_revision_does_not_recalculate_http_statistics(api):
    from decimal import Decimal

    from calorie_app.db.models import Product, ProductSource, ProductVersion

    client, engine, _, owners = api
    owner = owners["a"]
    profile(engine, owner)
    source, product = uuid4(), uuid4()
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [Product(id=product), ProductSource(id=source, description="test label")]
            )
            session.flush()
            session.add(
                ProductVersion(
                    product_id=product,
                    revision=1,
                    source_id=source,
                    name="original",
                    basis_unit="g",
                    energy_kcal=Decimal("87"),
                )
            )
            session.flush()
            payload = example("meal")
            payload["items"][0]["product"] = {"product_id": str(product), "revision": 1}
            payload["items"][0]["nutrition_origin"] = "catalog_snapshot"
            save_meal(session, owner, uuid4(), payload)
            day = day_for_date(session, owner, date(2026, 10, 9))
            save_diary_day(session, owner, day.id, example("diary-day"), base_revision=1)
        before = get(client).json()
        with Session(engine) as session, session.begin():
            session.add(
                ProductVersion(
                    product_id=product,
                    revision=2,
                    source_id=source,
                    name="new label",
                    basis_unit="g",
                    energy_kcal=Decimal("900"),
                )
            )
        after = get(client).json()
        assert before["daily"][4]["totals"] == after["daily"][4]["totals"]
        assert after["daily"][4]["totals"]["energy_kcal"]["known_sum"] == "130.5"
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
            connection.execute(text("TRUNCATE app.products,app.product_sources CASCADE"))


def test_no_store_for_private_success_and_all_auth_validation_errors(api):
    client, engine, _, owners = api
    for response in (
        get(client),
        get(client, token="invalid"),
        get(client, token="admin"),
        get(client, days=1),
    ):
        assert response.headers["cache-control"] == "no-store"
    profile(engine, owners["a"])
    assert get(client).headers["cache-control"] == "no-store"


def test_database_error_safe_no_store_and_retry(api, monkeypatch):
    import importlib

    from sqlalchemy.exc import SQLAlchemyError

    client, engine, _, owners = api
    profile(engine, owners["a"])

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private payload must not be echoed")

    monkeypatch.setattr(
        importlib.import_module("calorie_app.modules.analytics.router"), "statistics", unavailable
    )
    response = get(client)
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["retry-after"] == "5"
    assert "private payload" not in response.text
