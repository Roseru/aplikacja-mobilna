import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.core.config import Settings
from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import AuthFailure, Principal
from calorie_app.main import create_app
from calorie_app.modules.diary import read_repository
from calorie_app.modules.diary import read_service as reads
from calorie_app.modules.diary.models import DiaryDay, Meal, Weight
from calorie_app.modules.diary.read_models import ReadSession
from calorie_app.modules.diary.service import delete_entity, save_diary_day, save_meal, save_weight
from calorie_app.modules.identity.models import UserAccount
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.sync.repository import append_change, entity, lock_counter

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
SECRET = "e2" * 32
QUERY = {"from": "2026-10-09", "to": "2026-10-11", "limit": 1}


class Verifier:
    def __init__(self, people):
        self.people = people

    async def verify(self, token):
        if token not in self.people:
            raise AuthFailure(401, "unauthorized")
        return self.people[token]

    async def close(self):
        pass


@pytest.fixture
def state(database):
    engine, migrate, url = database
    people = {
        name: Principal("https://read.test", str(uuid4()), frozenset({"user"}))
        for name in ("a", "b")
    }
    owners = {}
    with Session(engine) as session, session.begin():
        for name, person in people.items():
            owners[name] = UUID(bootstrap(session, person, uuid4())["account_id"])
    api = create_engine(
        url, connect_args={"options": "-c role=calorie_app_api"}, hide_parameters=True
    )
    factory = sessionmaker(api)
    app = create_app(Settings(), engine=api)
    app.state.oidc_verifier = Verifier(people)
    with TestClient(app) as client:
        yield engine, factory, people, owners, client, migrate
    api.dispose()
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))


def write(engine, owner, kind="weight", entity_id=None, base=0, **changes):
    entity_id = entity_id or uuid4()
    name = {"weight": "weight", "meal": "meal", "diary_day": "diary-day"}[kind]
    payload = json.loads((ROOT / f"contracts/examples/valid/{name}.json").read_text())
    if kind in {"weight", "meal"}:
        payload.update(occurred_at="2026-10-10T12:00:00Z", local_date="2026-10-10", time_zone="UTC")
    else:
        payload.update(local_date="2026-10-10", time_zone="UTC")
    payload.update(changes)
    with Session(engine) as session, session.begin():
        counter = lock_counter(session, owner)
        {"weight": save_weight, "meal": save_meal, "diary_day": save_diary_day}[kind](
            session, owner, entity_id, payload, base_revision=base
        )
        append_change(session, counter, entity(session, owner, kind, entity_id))
    return entity_id


def get(client, endpoint="weights", who="a", query=None):
    return client.get(
        f"/api/v1/me/{endpoint}", params=query or QUERY, headers={"Authorization": f"Bearer {who}"}
    )


def follow(client, first, endpoint="weights", who="a", **changes):
    return get(client, endpoint, who, QUERY | {"page_token": first["next_page_token"]} | changes)


@pytest.mark.parametrize(
    "endpoint,kind", [("weights", "weight"), ("meals", "meal"), ("diary-days", "diary_day")]
)
def test_http_owned_live_and_metadata_without_profile(state, endpoint, kind):
    engine, _, _, owners, client, _ = state
    a = write(engine, owners["a"], kind)
    b = write(engine, owners["b"], kind)
    response = get(client, endpoint)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [x["entity_id"] for x in body["items"]] == [str(a)]
    assert str(b) not in response.text
    assert body["time_zone"] is None and body["profile_revision"] is None
    assert body["server_position"] == 1
    assert body["account_id"] == str(owners["a"])
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("endpoint", ["weights", "meals", "diary-days"])
def test_http_no_store_auth_and_query_errors(state, endpoint):
    _, _, _, _, client, _ = state
    for params, token, status in [
        (QUERY, "invalid", 401),
        (QUERY | {"owner_id": str(uuid4())}, "a", 422),
        (QUERY | {"limit": "501"}, "a", 422),
        ([("from", "2026-10-10"), ("from", "2026-10-10"), ("to", "2026-10-10")], "a", 422),
    ]:
        response = client.get(
            f"/api/v1/me/{endpoint}", params=params, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == status, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert set(response.json()) == {"code", "message", "details", "request_id"}


@pytest.mark.parametrize("mutation", ["edit", "delete", "insert"])
def test_stable_pages_changes_restart_and_retry(state, mutation):
    engine, factory, people, owners, client, _ = state
    ids = [write(engine, owners["a"], entity_id=UUID(int=i)) for i in (1, 2, 3)]
    first = get(client).json()
    if mutation == "edit":
        write(engine, owners["a"], entity_id=ids[1], base=1, weight_kg="99")
    elif mutation == "delete":
        with Session(engine) as session, session.begin():
            delete_entity(session, Weight, owners["a"], ids[1], base_revision=1)
    else:
        write(engine, owners["a"], entity_id=UUID(int=4))
    second = follow(client, first)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["items"][0]["entity_id"] == str(ids[1])
    assert body["items"][0]["revision"] == 1
    assert body["server_position"] == first["server_position"]
    assert body["as_of"] == first["as_of"]
    # A new session factory proves durable materialization rather than process RAM.
    restarted = reads.read(
        sessionmaker(factory.kw["bind"]),
        people["a"],
        "weights",
        QUERY | {"page_token": first["next_page_token"]},
        SECRET,
    )
    assert restarted == body
    assert follow(client, first).json() == body


@pytest.mark.parametrize(
    "change", ["owner", "endpoint", "filter", "limit", "generation", "epoch", "deleting"]
)
def test_http_context_binding(state, change):
    engine, _, _, owners, client, _ = state
    for _ in range(2):
        write(engine, owners["a"])
    first = get(client).json()
    if change == "owner":
        response = follow(client, first, who="b")
    elif change == "endpoint":
        response = follow(client, first, endpoint="meals")
    elif change == "filter":
        response = follow(client, first, to="2026-10-12")
    elif change == "limit":
        response = follow(client, first, limit=2)
    else:
        with engine.begin() as connection:
            if change == "epoch":
                old = connection.scalar(
                    text("SELECT sync_epoch FROM app.installation_state WHERE id=1")
                )
                connection.execute(
                    text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
                    {"epoch": uuid4()},
                )
            else:
                clause = (
                    "generation=generation+1"
                    if change == "generation"
                    else "state='deleting',generation=generation+1"
                )
                connection.execute(
                    text(f"UPDATE app.user_accounts SET {clause} WHERE id=:owner"),
                    {"owner": owners["a"]},
                )
        response = follow(client, first)
        if change == "epoch":
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
                    {"epoch": old},
                )
    assert response.status_code in {422, 409, 403}, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "weight_kg" not in response.text


@pytest.mark.parametrize("resource", ["sessions", "items", "bytes", "item_bytes"])
def test_resources_rollback_stable_503(state, monkeypatch, resource):
    engine, _, _, owners, client, _ = state
    for _ in range(2):
        write(engine, owners["a"])
    if resource == "sessions":
        for _ in range(4):
            assert get(client).status_code == 200
    else:
        monkeypatch.setattr(
            reads,
            {
                "items": "MAX_SESSION_ITEMS",
                "bytes": "MAX_SESSION_BYTES",
                "item_bytes": "MAX_ITEM_BYTES",
            }[resource],
            1,
        )
    response = get(client)
    assert response.status_code == 503 and response.json()["code"] == "read_resources_exhausted"
    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(ReadSession).where(ReadSession.owner_id == owners["a"])
        ) == (4 if resource == "sessions" else 0)


def test_ttl_fixed_and_expired_releases_active_cap(state, monkeypatch):
    engine, _, _, owners, client, _ = state
    for _ in range(2):
        write(engine, owners["a"])
    first = get(client).json()
    with Session(engine) as session:
        state_row = session.scalar(select(ReadSession).where(ReadSession.owner_id == owners["a"]))
        expires = state_row.expires_at
    monkeypatch.setattr(reads, "database_now", lambda _: expires - timedelta(microseconds=1))
    assert follow(client, first).status_code == 200
    monkeypatch.setattr(reads, "database_now", lambda _: expires)
    assert follow(client, first).status_code == 410
    # All pages retain initial expiry, which is never extended.
    with Session(engine) as session:
        assert session.get(ReadSession, state_row.id).expires_at == expires


def test_frozen_rr_context_with_real_barrier(state, monkeypatch):
    engine, _, _, owners, client, _ = state
    write(engine, owners["a"], entity_id=UUID(int=1))
    write(engine, owners["a"], entity_id=UUID(int=2))
    copied, release = Event(), Event()
    original = read_repository.records

    def barrier(*args):
        for index, value in enumerate(original(*args)):
            if index == 0:
                copied.set()
                assert release.wait(10)
            yield value

    monkeypatch.setattr(read_repository, "records", barrier)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(get, client)
        assert copied.wait(10)
        # Epoch metadata belongs to same RR state, even if independent restore metadata changes.
        with engine.begin() as connection:
            old = connection.scalar(
                text("SELECT sync_epoch FROM app.installation_state WHERE id=1")
            )
            connection.execute(
                text("UPDATE app.installation_state SET sync_epoch=:new WHERE id=1"),
                {"new": uuid4()},
            )
        release.set()
        response = pending.result(10)
    assert response.status_code == 200, response.text
    assert response.json()["sync_epoch"] == str(old)
    assert follow(client, response.json()).status_code == 409
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:old WHERE id=1"), {"old": old}
        )


def test_day_effective_completeness_after_last_meal_removed(state):
    engine, _, _, owners, client, _ = state
    meal = write(engine, owners["a"], "meal")
    with Session(engine) as session, session.begin():
        day = session.scalar(select(DiaryDay).where(DiaryDay.owner_id == owners["a"]))
        day.declared_complete = True
        day.revision += 1
    first = get(client, "diary-days").json()
    assert first["items"][0]["effective_complete"] is True
    with Session(engine) as session, session.begin():
        delete_entity(session, Meal, owners["a"], meal, base_revision=1)
    second = get(client, "diary-days").json()
    assert second["items"][0]["payload"]["declared_complete"] is True
    assert second["items"][0]["effective_complete"] is False


def test_narrow_acl_and_worker_prune(state):
    engine, _, _, owners, client, _ = state
    write(engine, owners["a"])
    write(engine, owners["a"])
    get(client)
    with engine.begin() as connection:
        for role in ("calorie_app_api", "calorie_app_worker", "calorie_app_deletion_operator"):
            assert not connection.scalar(
                text("SELECT has_table_privilege(:role,'app.read_sessions','DELETE')"),
                {"role": role},
            )
        assert not connection.scalar(
            text(
                "SELECT has_function_privilege('calorie_app_api',"
                "'app.prune_read_sessions(uuid,integer)','EXECUTE')"
            )
        )
        assert connection.scalar(
            text(
                "SELECT has_function_privilege('calorie_app_worker',"
                "'app.prune_read_sessions(uuid,integer)','EXECUTE')"
            )
        )
        connection.execute(
            text(
                "UPDATE app.read_sessions SET created_at=created_at-interval '61 minutes',"
                "expires_at=expires_at-interval '61 minutes' WHERE owner_id=:owner"
            ),
            {"owner": owners["a"]},
        )
        connection.execute(text("SET LOCAL ROLE calorie_app_worker"))
        result = connection.scalar(
            text("SELECT app.prune_read_sessions(:owner,1000)"), {"owner": owners["a"]}
        )
        assert result == {"read_items": 2, "read_sessions": 1}


def test_existing_account_purge_cascades_private_copies(state):
    engine, _, _, owners, client, _ = state
    write(engine, owners["a"])
    write(engine, owners["a"])
    get(client)
    operation = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("SELECT app.begin_account_deletion(:owner,:operation,1)"),
            {"owner": owners["a"], "operation": operation},
        )
        connection.execute(
            text("SELECT app.confirm_account_deletion(:operation)"), {"operation": operation}
        )
        connection.execute(
            text("SELECT app.purge_deleted_account(:operation)"), {"operation": operation}
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.read_sessions WHERE owner_id=:owner"),
                {"owner": owners["a"]},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.read_session_items WHERE owner_id=:owner"),
                {"owner": owners["a"]},
            )
            == 0
        )
    assert get(client).status_code == 403


def test_page_envelope_utf8_actual_one_mib(state):
    engine, _, _, owners, client, _ = state
    payload = json.loads((ROOT / "contracts/examples/valid/meal.json").read_text())
    template = payload["items"][0]
    items = [
        template
        | {
            "item_id": str(uuid4()),
            "name": "ą" * 200,
            "density_g_per_ml": "1",
            "density_source": "ą" * 500,
        }
        for _ in range(100)
    ]
    for _ in range(10):
        write(engine, owners["a"], "meal", items=items)
    query = QUERY | {"limit": 500}
    response = get(client, "meals", query=query)
    assert response.status_code == 200, response.text
    first = response.json()
    assert 0 < len(first["items"]) < 10 and first["next_page_token"]
    assert len(response.content) <= 1048576
    second = get(client, "meals", query=query | {"page_token": first["next_page_token"]})
    assert second.status_code == 200, second.text
    assert len(second.content) <= 1048576
    assert len(first["items"]) + len(second.json()["items"]) == 10


def test_concurrent_active_session_cap_real_transactions(state, monkeypatch):
    engine, factory, people, owners, _, _ = state
    from threading import Barrier, local

    write(engine, owners["a"])
    write(engine, owners["a"])
    arrived = local()
    barrier = Barrier(6)
    original = reads.require_account

    def synchronized_account(session, person):
        if not getattr(arrived, "seen", False):
            # Establish all six RR snapshots before any admission commits.
            session.scalar(select(UserAccount.id).where(UserAccount.id == owners["a"]))
            arrived.seen = True
            barrier.wait(timeout=10)
        return original(session, person)

    monkeypatch.setattr(reads, "require_account", synchronized_account)

    def attempt(_):
        try:
            return reads.read(factory, people["a"], "weights", QUERY, SECRET)
        except DomainError as error:
            return error

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(isinstance(value, dict) for value in results) == 4
    assert all(
        isinstance(value, dict) or value.code == "read_resources_exhausted" for value in results
    )
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReadSession)
                .where(ReadSession.owner_id == owners["a"])
            )
            == 4
        )


@pytest.mark.parametrize(
    "roles",
    [
        frozenset({"user", "admin"}),
        frozenset({"user", "moderator"}),
        frozenset({"admin"}),
        frozenset({"moderator"}),
    ],
)
def test_roles_never_grant_other_owner_diary(state, roles):
    engine, _, people, owners, client, _ = state
    write(engine, owners["b"])
    people["a"] = Principal(people["a"].issuer, people["a"].subject, roles)
    response = get(client)
    if "user" in roles:
        assert response.status_code == 200 and response.json()["items"] == []
    else:
        assert response.status_code == 403
    assert "weight_kg" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_upgrade_downgrade_retains_e4_domain_data(state):
    engine, _, _, owners, client, migrate = state
    identifier = write(engine, owners["a"])
    write(engine, owners["a"])
    assert get(client).status_code == 200
    migrate("downgrade", "0011_e4_deletion")
    with Session(engine) as session:
        assert session.get(Weight, identifier).owner_id == owners["a"]
    migrate("upgrade", "head")
    assert get(client).status_code == 200


@pytest.mark.parametrize(
    "resource", ["MAX_COMPLETENESS_MEALS", "MAX_COMPLETENESS_ITEMS", "MAX_COMPLETENESS_BYTES"]
)
def test_completeness_work_limits_rollback(state, monkeypatch, resource):
    engine, _, _, owners, client, _ = state
    write(engine, owners["a"], "meal")
    monkeypatch.setattr(read_repository, resource, 0)
    response = get(client, "diary-days")
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "read_resources_exhausted"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ReadSession)) == 0


@pytest.mark.parametrize(
    "endpoint,kind", [("weights", "weight"), ("meals", "meal"), ("diary-days", "diary_day")]
)
@pytest.mark.parametrize("count", [0, 1])
def test_unpaged_refresh_does_not_consume_slots(state, endpoint, kind, count):
    engine, _, _, owners, client, _ = state
    if count:
        write(engine, owners["a"], kind)
    for _ in range(20):
        response = get(client, endpoint)
        assert response.status_code == 200, response.text
        assert response.json()["next_page_token"] is None
        assert len(response.json()["items"]) == count
    with engine.begin() as connection:
        for table in ("read_sessions", "read_session_items"):
            assert (
                connection.scalar(
                    text(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"),
                    {"owner": owners["a"]},
                )
                == 0
            )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.read_admissions WHERE owner_id=:owner"),
                {"owner": owners["a"]},
            )
            == 1
        )


def test_discard_acl_and_wrong_owner_paged_context_denied(state):
    engine, _, _, owners, client, _ = state
    for _ in range(2):
        write(engine, owners["a"])
    response = get(client)
    assert response.status_code == 200 and response.json()["next_page_token"]
    with engine.begin() as connection:
        identifier = connection.scalar(
            text("SELECT id FROM app.read_sessions WHERE owner_id=:owner"), {"owner": owners["a"]}
        )
        for role in ("PUBLIC", "calorie_app_worker", "calorie_app_deletion_operator"):
            if role == "PUBLIC":
                continue
            assert not connection.scalar(
                text(
                    "SELECT has_function_privilege(:role,"
                    "'app.discard_unpaged_read(uuid,uuid)','EXECUTE')"
                ),
                {"role": role},
            )
        assert connection.scalar(
            text(
                "SELECT has_function_privilege('calorie_app_api',"
                "'app.discard_unpaged_read(uuid,uuid)','EXECUTE')"
            )
        )
        assert not connection.scalar(
            text("SELECT has_table_privilege('calorie_app_api','app.read_sessions','DELETE')")
        )
    from sqlalchemy.exc import DBAPIError

    for owner in (owners["a"], owners["b"]):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE calorie_app_api"))
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text("SELECT app.discard_unpaged_read(:owner,:session)"),
                        {"owner": owner, "session": identifier},
                    )
    assert follow(client, response.json()).status_code == 200
