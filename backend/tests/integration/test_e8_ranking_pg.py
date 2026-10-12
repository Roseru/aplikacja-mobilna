"""Real PG17/API-role tests for live ranking, opaque continuation and privacy."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, Principal
from calorie_app.main import create_app
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.profiles.schemas import ProfilePayload
from calorie_app.modules.profiles.service import save_profile

pytestmark = pytest.mark.integration


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
def ranking_state(database):
    engine, _, url = database
    people = {
        name: Principal("https://ranking.test", str(uuid4()), frozenset({"user"}))
        for name in ("a", "b")
    }
    people["admin"] = Principal("https://ranking.test", str(uuid4()), frozenset({"admin"}))
    owners = {}
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
        epoch = connection.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    with Session(engine) as session, session.begin():
        for name in ("a", "b"):
            owners[name] = UUID(bootstrap(session, people[name], uuid4())["account_id"])
    api = create_engine(
        url, connect_args={"options": "-c role=calorie_app_api"}, hide_parameters=True
    )
    app = create_app(Settings(), engine=api)
    app.state.oidc_verifier = Verifier(people)
    with TestClient(app) as client:
        yield engine, api, owners, epoch, client
    api.dispose()
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"), {"epoch": epoch}
        )


def participant(engine, epoch, pseudonym, points, owner=None, fresh=True):
    """Administrator-controlled projection fixture isolates ranking from reducer tests."""
    with Session(engine) as session, session.begin():
        if owner is None:
            person = Principal("https://ranking.test", str(uuid4()), frozenset({"user"}))
            owner = UUID(bootstrap(session, person, uuid4())["account_id"])
        save_profile(
            session,
            owner,
            uuid4(),
            ProfilePayload(
                pseudonym=pseudonym, height_cm=None, activity_class="line", time_zone="UTC"
            ),
        )
        # Synthetic source seed preserves the historical revision-1 baseline;
        # runtime consent transitions are exercised through the API separately.
        session.execute(
            text("DELETE FROM app.user_consents WHERE owner_id=:owner"), {"owner": owner}
        )
        session.execute(
            text("INSERT INTO app.user_consents(owner_id,ranking) VALUES(:owner,true)"),
            {"owner": owner},
        )
        session.execute(
            text("""
            INSERT INTO app.motivation_accounts(owner_id,sync_epoch,backfill_state,total_points)
            VALUES(:owner,:epoch,'ready',:points)
            ON CONFLICT(owner_id) DO UPDATE SET total_points=EXCLUDED.total_points,
                backfill_state='ready',sync_epoch=EXCLUDED.sync_epoch
        """),
            {"owner": owner, "epoch": epoch, "points": points},
        )
        if fresh:
            session.execute(
                text("SELECT app.e8_affirm_ranking(:owner,:epoch,:revision)"),
                {"owner": owner, "epoch": epoch, "revision": 1},
            )
    return owner


def get(client, token="a", **params):
    return client.get(
        "/api/v1/ranking", params=params, headers={"Authorization": "Bearer " + token}
    )


def test_ties_are_competition_rank_and_payload_minimal(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "Ż", 10, owners["a"])
    participant(engine, epoch, "A", 10, owners["b"])
    third = participant(engine, epoch, "第三", 8)
    response = get(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["position"] for item in body["items"]] == [1, 1, 3]
    assert [item["pseudonym"] for item in body["items"]] == ["A", "Ż", "第三"]
    for row in body["items"]:
        assert set(row) == {"position", "pseudonym", "points", "rank", "active_badges"}
    for private in [
        str(third),
        *(str(value) for value in owners.values()),
        "ranking.test",
        "weight_kg",
        "energy_kcal",
        "owner_id",
        "subject",
        "email",
    ]:
        assert private not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert body["has_more"] is False and body["next_page_token"] is None


@pytest.mark.parametrize("mutation", ["optout", "deleting", "profile", "pending", "epoch"])
def test_each_live_page_filters_current_publication(ranking_state, mutation):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "A", 10, owners["a"])
    participant(engine, epoch, "B", 9, owners["b"])
    participant(engine, epoch, "C", 8)
    first = get(client, limit=1).json()
    with engine.begin() as connection:
        sql = {
            "optout": (
                "UPDATE app.user_consents SET ranking=false,revision=revision+1 "
                "WHERE owner_id=:owner"
            ),
            "deleting": (
                "UPDATE app.user_accounts SET state='deleting',generation=generation+1 "
                "WHERE id=:owner"
            ),
            "profile": (
                "UPDATE app.user_profiles SET deleted_at=clock_timestamp(),revision=revision+1 "
                "WHERE owner_id=:owner"
            ),
            "pending": (
                "UPDATE app.motivation_accounts SET backfill_state='pending' WHERE owner_id=:owner"
            ),
            "epoch": (
                "UPDATE app.ranking_affirmations SET ranking_consent_epoch=:epoch "
                "WHERE owner_id=:owner"
            ),
        }[mutation]
        connection.execute(text(sql), {"owner": owners["b"], "epoch": uuid4()})
    second = get(client, limit=1, page_token=first["next_page_token"])
    assert second.status_code == 200, second.text
    assert [item["pseudonym"] for item in second.json()["items"]] == ["C"]
    assert second.json()["items"][0]["position"] == 2


def test_optout_anchor_still_seek_and_purged_anchor_requires_restart(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "A", 10, owners["b"])
    participant(engine, epoch, "B", 9)
    participant(engine, epoch, "C", 8)
    first = get(client, limit=1).json()
    token = first["next_page_token"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.user_consents SET ranking=false,revision=revision+1 "
                "WHERE owner_id=:owner"
            ),
            {"owner": owners["b"]},
        )
    assert get(client, limit=1, page_token=token).json()["items"][0]["pseudonym"] == "B"
    # Simulate the account-delete end of the narrow purge wrapper: its references
    # are removed in the production wrapper before account deletion.
    with engine.begin() as connection:
        for table in ("user_profiles", "user_consents", "online_receipts", "motivation_accounts"):
            connection.execute(
                text(f"DELETE FROM app.{table} WHERE owner_id=:owner"), {"owner": owners["b"]}
            )
        connection.execute(
            text("DELETE FROM app.user_accounts WHERE id=:owner"), {"owner": owners["b"]}
        )
    rejected = get(client, limit=1, page_token=token)
    assert rejected.status_code == 410, rejected.text
    assert rejected.json()["code"] == "ranking_cursor_restart_required"
    assert str(owners["b"]) not in rejected.text and token not in rejected.text


def test_cursor_ownership_limit_generation_epoch_ttl_and_replay(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    for index in range(5):
        participant(engine, epoch, str(index), 10 - index)
    first = get(client, limit=1).json()
    token = first["next_page_token"]
    page = get(client, limit=1, page_token=token)
    replay = get(client, limit=1, page_token=token)
    assert replay.json()["items"] == page.json()["items"]
    assert replay.json()["next_page_token"] == page.json()["next_page_token"]
    for who, limit in [("b", 1), ("a", 2)]:
        assert get(client, who, limit=limit, page_token=token).status_code == 410
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE app.user_accounts SET generation=generation+1 WHERE id=:owner"),
            {"owner": owners["a"]},
        )
    assert get(client, limit=1, page_token=token).status_code == 410
    renewed = get(client, limit=1).json()["next_page_token"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.ranking_sessions SET created_at=created_at-interval '11 minutes',"
                "expires_at=expires_at-interval '11 minutes' WHERE requester_id=:owner"
            ),
            {"owner": owners["a"]},
        )
    assert get(client, limit=1, page_token=renewed).status_code == 410
    renewed = get(client, limit=1).json()["next_page_token"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
            {"epoch": uuid4()},
        )
    assert get(client, limit=1, page_token=renewed).status_code == 410


@pytest.mark.parametrize(
    "params,token,status",
    [
        ({"owner": "private"}, "a", 422),
        ({"limit": 0}, "a", 422),
        ({"limit": 101}, "a", 422),
        ({"page_token": "private"}, "a", 422),
        ({}, "invalid", 401),
        ({}, "admin", 403),
        ([("limit", 1), ("limit", 2)], "a", 422),
    ],
)
def test_ranking_no_store_before_router_and_strict_queries(ranking_state, params, token, status):
    response = (
        get(ranking_state[-1], token, **params)
        if isinstance(params, dict)
        else (
            ranking_state[-1].get(
                "/api/v1/ranking", params=params, headers={"Authorization": "Bearer " + token}
            )
        )
    )
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


def test_ranking_more_than_10100_and_quota_never_caps_deep_continuation(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    # Separate bounded transactions keep deferred legacy constraint checks from
    # repeatedly traversing one growing 10103-owner transaction at commit.
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name='UTC')")
        )
    for first_index in range(1, 10104, 200):
        last_index = min(10103, first_index + 199)
        with engine.begin() as connection:
            bounds = {"lo": first_index, "hi": last_index, "epoch": epoch}
            connection.execute(
                text("""
                INSERT INTO app.user_accounts(id,issuer,subject)
                SELECT md5('e8-ranking-'||g)::uuid,'https://large.test',g::text

                FROM generate_series(CAST(:lo AS integer),CAST(:hi AS integer)) g
            """),
                bounds,
            )
            # Ranking/cursor oracle uses administrator-controlled synthetic
            # profiles in one independently checked IANA zone. Avoid 10103
            # redundant pg_timezone_names enumerations in the legacy validator.
            # Every other source/E8 CHECK/FK/owner/revision trigger stays enabled;
            # the real source-write tests separately exercise time-zone guard.
            connection.execute(
                text("ALTER TABLE app.user_profiles DISABLE TRIGGER private_time_zone")
            )
            try:
                connection.execute(
                    text("""
                    INSERT INTO app.user_profiles
                      (id,owner_id,revision,pseudonym,activity_class,time_zone)
                    SELECT md5('e8-ranking-profile-'||g)::uuid,md5('e8-ranking-'||g)::uuid,1,
                           'P'||lpad(g::text,5,'0'),'line','UTC'
                FROM generate_series(CAST(:lo AS integer),CAST(:hi AS integer)) g
                """),
                    bounds,
                )
            finally:
                connection.execute(
                    text("ALTER TABLE app.user_profiles ENABLE TRIGGER private_time_zone")
                )
            connection.execute(
                text("""
                INSERT INTO app.user_consents(owner_id,ranking)
                SELECT md5('e8-ranking-'||g)::uuid,true
                FROM generate_series(CAST(:lo AS integer),CAST(:hi AS integer)) g
            """),
                bounds,
            )
            connection.execute(
                text("""
                INSERT INTO app.motivation_accounts(owner_id,sync_epoch,backfill_state,total_points)
                SELECT md5('e8-ranking-'||g)::uuid,:epoch,'ready',10

                FROM generate_series(CAST(:lo AS integer),CAST(:hi AS integer)) g
            """),
                bounds,
            )
            connection.execute(
                text("""
                INSERT INTO app.ranking_affirmations(owner_id,ranking_consent_epoch,source_revision)
                SELECT md5('e8-ranking-'||g)::uuid,:epoch,1
                FROM generate_series(CAST(:lo AS integer),CAST(:hi AS integer)) g
            """),
                bounds,
            )
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT count(*) FROM app.user_profiles WHERE time_zone<>'UTC'"))
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT tgenabled FROM pg_trigger WHERE tgname='private_time_zone' "
                    "AND tgrelid='app.user_profiles'::regclass"
                )
            )
            == "O"
        )
    initial = [get(client, limit=100) for _ in range(8)]
    assert all(response.status_code == 200 for response in initial)
    exhausted = get(client, limit=100)
    assert exhausted.status_code == 429
    assert exhausted.headers["retry-after"] == "600"
    page, names = initial[0].json(), []
    while True:
        names.extend(row["pseudonym"] for row in page["items"])
        assert all(row["position"] == 1 for row in page["items"])
        if not page["has_more"]:
            break
        response = get(client, limit=100, page_token=page["next_page_token"])
        assert response.status_code == 200, response.text
        page = response.json()
    assert len(names) == 10103 and len(set(names)) == 10103
    assert names[-1] == "P10103"
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app.ranking_sessions")) == 8
        assert connection.scalar(text("SELECT count(*) FROM app.ranking_cursors")) <= 16
        connection.execute(
            text(
                "UPDATE app.ranking_sessions SET created_at=created_at-interval '11 minutes',"
                "expires_at=expires_at-interval '11 minutes' WHERE requester_id=:owner"
            ),
            {"owner": owners["a"]},
        )
    assert get(client, limit=100).status_code == 200


@pytest.mark.parametrize("endpoint", ["/api/v1/me/motivation", "/api/v1/ranking"])
def test_motivation_and_ranking_auth_owner_parser_no_store(ranking_state, endpoint):
    client = ranking_state[-1]
    for token, params, expected in [
        ("invalid", {}, 401),
        ("admin", {}, 403),
        ("a", {"owner": "private-sentinel"}, 422),
    ]:
        response = client.get(endpoint, params=params, headers={"Authorization": "Bearer " + token})
        assert response.status_code == expected, response.text
        assert response.headers["cache-control"] == "no-store"
        assert "private-sentinel" not in response.text
    response = client.get(endpoint)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_live_pseudonym_current_and_duplicate_presentation_sort(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "同じ", 10, owners["a"])
    participant(engine, epoch, "同じ", 10, owners["b"])
    participant(engine, epoch, "終", 8)
    first = get(client, limit=1).json()
    assert first["items"][0]["position"] == 1
    response = get(client, limit=1, page_token=first["next_page_token"])
    assert response.json()["items"][0]["position"] == 1
    assert response.json()["items"][0]["pseudonym"] == "同じ"
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.user_profiles SET pseudonym='New Unicode 🧭',revision=revision+1 "
                "WHERE owner_id=:owner"
            ),
            {"owner": owners["b"]},
        )
    assert "New Unicode 🧭" in [row["pseudonym"] for row in get(client).json()["items"]]


def test_live_query_rechecks_optout_after_cursor_validation_with_barrier(
    ranking_state, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from calorie_app.modules.analytics.motivation import ranking as module

    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "A", 10)
    participant(engine, epoch, "B", 9, owners["b"])
    participant(engine, epoch, "C", 8)
    first = get(client, limit=1).json()
    token = first["next_page_token"]
    ready, proceed = Event(), Event()
    original = module._load_cursor

    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        ready.set()
        assert proceed.wait(20), "ranking barrier timed out"
        return result

    monkeypatch.setattr(module, "_load_cursor", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(get, client, limit=1, page_token=token)
        assert ready.wait(20), "ranking did not reach cursor barrier"
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE app.user_consents SET ranking=false,revision=revision+1 "
                        "WHERE owner_id=:owner"
                    ),
                    {"owner": owners["b"]},
                )
        finally:
            proceed.set()
        response = running.result(20)
    assert response.status_code == 200, response.text
    assert [row["pseudonym"] for row in response.json()["items"]] == ["C"]
    assert response.json()["items"][0]["position"] == 2


def test_same_cursor_concurrent_retries_return_one_continuation(ranking_state):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine, _, _, epoch, client = ranking_state
    for index in range(4):
        participant(engine, epoch, str(index), 10 - index)
    first = get(client, limit=1).json()
    barrier = Barrier(2)

    def concurrent():
        barrier.wait(20)
        return get(client, limit=1, page_token=first["next_page_token"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(concurrent) for _ in range(2)]
        responses = [future.result(30) for future in futures]
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["items"] == responses[1].json()["items"]
    assert responses[0].json()["next_page_token"] == responses[1].json()["next_page_token"]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app.ranking_sessions")) == 1
        assert connection.scalar(text("SELECT count(*) FROM app.ranking_cursors")) == 2
