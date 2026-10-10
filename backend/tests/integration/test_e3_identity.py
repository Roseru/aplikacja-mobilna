import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.models import InstallationState, OnlineReceipt, UserAccount
from calorie_app.modules.identity.service import (
    begin_deleting,
    bootstrap,
    current_epoch,
    lock_account,
)
from calorie_app.modules.profiles.models import GoalTimeline, GoalVersion, Profile, UserConsent
from calorie_app.modules.profiles.pagination import goal_page, parse_goal_cursor, sign_goal_cursor
from calorie_app.modules.profiles.schemas import ConsentInput, GoalPayload, ProfilePayload
from calorie_app.modules.profiles.service import (
    create_goal,
    delete_profile,
    goal_for_date,
    profile_data,
    prune_consent_responses,
    put_consents,
    read_profile,
    save_profile,
)

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
SECRET = SecretStr("e3" * 32)
CONSENT = ConsentInput(ranking=True, automatic_energy_adjustment=False)


def principal():
    return Principal("https://identity.example.test/realm", str(uuid4()), frozenset({"user"}))


def goal_payload(revision=0, **changes):
    data = json.loads((ROOT / "contracts/examples/valid/goal.json").read_text())
    return GoalPayload.model_validate(data | {"timeline_base_revision": revision} | changes)


@pytest.fixture
def identity_db(database):
    # The shared database fixture verifies PostgreSQL17 and a dedicated *_test DB.
    engine, _, _ = database
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
        epoch = connection.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    yield engine
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"), {"epoch": epoch}
        )


def boot(engine, who=None, key=None):
    who = who or principal()
    with Session(engine) as session, session.begin():
        result = bootstrap(session, who, key or uuid4())
    return who, UUID(result["account_id"]), result


def write_consent(engine, owner, key=None, base=1):
    with Session(engine) as session, session.begin():
        return put_consents(session, owner, CONSENT, base, key or uuid4())


def test_bootstrap_replay_persists_and_is_not_a_profile(identity_db):
    key, who = uuid4(), principal()
    _, owner, first = boot(identity_db, who, key)
    _, again, replay = boot(identity_db, who, key)
    assert owner == again and first == replay
    with Session(identity_db) as session, session.begin():
        result = read_profile(session, owner)
        assert result["profile"] is None
        assert result["goal_timeline_revision"] == 0
        assert result["consents"]["revision"] == 1
        assert result["consents"]["ranking"] is False
        assert result["consents"]["automatic_energy_adjustment"] is False
        assert session.scalar(select(func.count()).select_from(GoalVersion)) == 0
        assert current_epoch(session) == UUID(first["sync_epoch"])
    write_consent(identity_db, owner)
    _, _, new_boot = boot(identity_db, who)
    with Session(identity_db) as session:
        assert session.get(UserConsent, owner).revision == 2
    assert new_boot["account_id"] == first["account_id"]


@pytest.mark.parametrize("same_key", [True, False])
def test_natural_bootstrap_race_same_and_different_keys(identity_db, same_key):
    who, shared_key = principal(), uuid4()
    barrier = Barrier(6)

    def attempt(_):
        barrier.wait(timeout=10)
        return boot(identity_db, who, shared_key if same_key else uuid4())[2]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert len({item["account_id"] for item in results}) == 1
    if same_key:
        assert all(result == results[0] for result in results)
    with Session(identity_db) as session:
        assert session.scalar(select(func.count()).select_from(UserAccount)) == 1
        assert session.scalar(select(func.count()).select_from(UserConsent)) == 1
        assert session.scalar(select(func.count()).select_from(OnlineReceipt)) == (
            1 if same_key else 6
        )


def test_bootstrap_failure_rolls_back_account_consent_and_receipt(identity_db):
    who = principal()
    with Session(identity_db) as session:
        bootstrap(session, who, uuid4())
        session.rollback()
    with Session(identity_db) as session:
        assert session.scalar(select(func.count()).select_from(UserAccount)) == 0
        assert session.scalar(select(func.count()).select_from(UserConsent)) == 0
        assert session.scalar(select(func.count()).select_from(OnlineReceipt)) == 0


def test_epoch_and_generation_replay_context_and_deleting_priority(identity_db):
    who, key = principal(), uuid4()
    _, owner, initial = boot(identity_db, who, key)
    changed = uuid4()
    with identity_db.begin() as connection:
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
            {"epoch": changed},
        )
    with pytest.raises(DomainError) as error:
        boot(identity_db, who, key)
    assert error.value.code == "sync_epoch_changed"
    assert error.value.details == [{"field": "sync_epoch", "reason": str(changed)}]
    new_key = uuid4()
    assert boot(identity_db, who, new_key)[2]["account_id"] == initial["account_id"]
    with identity_db.begin() as connection:
        connection.execute(
            text("UPDATE app.user_accounts SET generation=generation+1 WHERE id=:id"), {"id": owner}
        )
    with pytest.raises(DomainError) as error:
        boot(identity_db, who, new_key)
    assert error.value.code == "account_generation_changed"
    assert boot(identity_db, who)[2]["account_generation"] == 2
    with Session(identity_db) as session, session.begin():
        begin_deleting(session, owner)
    for retry_key in (key, new_key, uuid4()):
        with pytest.raises(DomainError) as error:
            boot(identity_db, who, retry_key)
        assert error.value.status == 403 and error.value.code == "account_deleting"
    with Session(identity_db) as session:
        assert session.scalar(select(func.count()).select_from(UserAccount)) == 1


def test_consents_replay_before_revision_and_independent_owner_keys(identity_db):
    _, a, _ = boot(identity_db)
    _, b, _ = boot(identity_db)
    key = uuid4()
    first = write_consent(identity_db, a, key)
    write_consent(identity_db, a, base=2)
    assert write_consent(identity_db, a, key) == first
    assert write_consent(identity_db, b, key)["revision"] == 2
    for changes in (
        {"base": 2},
        {"body": ConsentInput(ranking=False, automatic_energy_adjustment=False)},
    ):
        with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
            put_consents(session, a, changes.get("body", CONSENT), changes.get("base", 1), key)
        assert error.value.code == "idempotency_key_reused"
    with pytest.raises(DomainError) as error:
        write_consent(identity_db, a, base=1)
    assert error.value.code == "version_conflict"


@pytest.mark.parametrize("same_key", [True, False])
def test_consents_parallel_replays_or_revision_conflict(identity_db, same_key):
    _, owner, _ = boot(identity_db)
    key, barrier = uuid4(), Barrier(4)

    def attempt(_):
        barrier.wait(timeout=10)
        try:
            return write_consent(identity_db, owner, key if same_key else uuid4())
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(4)))
    accepted = [item for item in outcomes if isinstance(item, dict)]
    assert len(accepted) == (4 if same_key else 1)
    assert all(item == accepted[0] for item in accepted)
    assert all(item == "version_conflict" for item in outcomes if isinstance(item, str))
    with Session(identity_db) as session:
        assert session.get(UserConsent, owner).revision == 2


def test_consent_rollback_discards_both_mutation_and_receipt(identity_db):
    _, owner, _ = boot(identity_db)
    key = uuid4()
    with Session(identity_db) as session:
        put_consents(session, owner, CONSENT, 1, key)
        session.rollback()
    with Session(identity_db) as session:
        assert session.get(UserConsent, owner).revision == 1
        assert session.get(OnlineReceipt, (owner, "consents", key)) is None
    assert write_consent(identity_db, owner, key)["revision"] == 2


@pytest.mark.parametrize("deleting_first", [True, False])
def test_common_account_lock_serializes_deleting_and_mutation(identity_db, deleting_first):
    _, owner, _ = boot(identity_db)
    ready, key, contender_pid = Event(), uuid4(), []

    def contender():
        try:
            with Session(identity_db) as other, other.begin():
                contender_pid.append(other.scalar(text("SELECT pg_backend_pid()")))
                ready.set()
                if deleting_first:
                    return put_consents(other, owner, CONSENT, 1, key)
                return begin_deleting(other, owner).generation
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(identity_db) as first, first.begin():
            if deleting_first:
                begin_deleting(first, owner)
            else:
                put_consents(first, owner, CONSENT, 1, key)
            pending = pool.submit(contender)
            assert ready.wait(timeout=5)
            deadline = monotonic() + 5
            blocked = False
            with identity_db.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while monotonic() < deadline and not pending.done():
                    blocked = observer.scalar(
                        text("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": contender_pid[0]},
                    )
                    if blocked:
                        break
                    Event().wait(0.01)
            assert blocked, "The contender must actually wait for the account lock in PostgreSQL"
            assert not pending.done()
        outcome = pending.result(timeout=10)
    assert outcome == ("account_deleting" if deleting_first else 2)
    with Session(identity_db) as session:
        assert session.get(UserConsent, owner).revision == (1 if deleting_first else 2)
        receipt = session.get(OnlineReceipt, (owner, "consents", key))
        assert (receipt is None) == deleting_first


def test_consent_retention_minimum_evidence_never_reexecutes(identity_db):
    _, owner, _ = boot(identity_db)
    keys = [uuid4(), uuid4()]
    with Session(identity_db) as session, session.begin():
        account = lock_account(session, owner)
        now = database_now(session)
        consent = session.get(UserConsent, owner)
        consent.revision = 2
        consent.ranking = True
        response = {
            "revision": 2,
            "ranking": True,
            "automatic_energy_adjustment": False,
            "updated_at": "2026-08-01T00:00:00Z",
        }
        fingerprint = hashlib.sha256(
            canonical_json({"body": CONSENT.model_dump(mode="json"), "if_match": 1})
        ).hexdigest()
        for key, age in zip(keys, (59, 61), strict=True):
            session.add(
                OnlineReceipt(
                    owner_id=owner,
                    operation="consents",
                    key=key,
                    generation=account.generation,
                    sync_epoch=current_epoch(session),
                    request_hash=fingerprint,
                    accepted_revision=2,
                    response=response,
                    created_at=now - timedelta(days=age),
                )
            )
    with Session(identity_db) as session, session.begin():
        assert prune_consent_responses(session) == 1
        assert prune_consent_responses(session) == 0
    assert write_consent(identity_db, owner, keys[0]) == response
    with pytest.raises(DomainError) as error:
        write_consent(identity_db, owner, keys[1])
    assert error.value.code == "idempotency_result_expired"
    with Session(identity_db) as session:
        assert session.get(UserConsent, owner).revision == 2
        assert session.get(OnlineReceipt, (owner, "consents", keys[1])).accepted_revision == 2


def test_profiles_ownership_one_live_and_tombstone(identity_db):
    _, a, _ = boot(identity_db)
    _, b, _ = boot(identity_db)
    entity = uuid4()
    payload = ProfilePayload(
        pseudonym="A", height_cm="180.000001", activity_class="line", time_zone="Europe/Warsaw"
    )
    with Session(identity_db) as session, session.begin():
        profile = save_profile(session, a, entity, payload)
        assert profile_data(profile)["payload"]["height_cm"] == "180.000001"
        assert read_profile(session, b)["profile"] is None
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        save_profile(session, b, entity, payload)
    assert error.value.status == 404
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        save_profile(session, a, uuid4(), payload)
    assert error.value.code == "profile_already_exists"
    with Session(identity_db) as session, session.begin():
        delete_profile(session, a, entity, 1)
        assert read_profile(session, a)["profile"] is None
        save_profile(session, a, uuid4(), payload.model_copy(update={"height_cm": None}))


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "0", "-1", "300.000001"])
def test_raw_sql_profile_numeric_constraints(identity_db, bad):
    _, owner, _ = boot(identity_db)
    with pytest.raises(DBAPIError), identity_db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.user_profiles "
                "(id,owner_id,revision,pseudonym,height_cm,activity_class,time_zone) "
                "VALUES (:id,:owner,1,'A',CAST(:value AS numeric),'line','Europe/Warsaw')"
            ),
            {"id": uuid4(), "owner": owner, "value": bad},
        )


def test_raw_sql_profile_unique_revision_zone_fk(identity_db):
    _, owner, _ = boot(identity_db)
    row = dict(
        id=uuid4(),
        owner_id=owner,
        revision=1,
        pseudonym="A",
        height_cm=None,
        activity_class="line",
        time_zone="Europe/Warsaw",
    )
    with identity_db.begin() as connection:
        connection.execute(insert(Profile).values(**row))
    for changes in (
        {"id": uuid4()},
        {"id": uuid4(), "owner_id": uuid4()},
        {"id": uuid4(), "revision": 2147483648},
        {"id": uuid4(), "time_zone": "Europe/Imaginary"},
    ):
        with pytest.raises(DBAPIError), identity_db.begin() as connection:
            connection.execute(insert(Profile).values(**(row | changes)))


def test_goal_immutable_manual_correction_owner_and_timeline(identity_db):
    _, a, _ = boot(identity_db)
    _, b, _ = boot(identity_db)
    first, corrected = uuid4(), uuid4()
    with Session(identity_db) as session, session.begin():
        create_goal(session, a, first, goal_payload())
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        create_goal(session, a, uuid4(), goal_payload())
    assert error.value.code == "goal_timeline_conflict"
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        create_goal(
            session, b, uuid4(), goal_payload(reason="history_correction", correction_of=str(first))
        )
    assert error.value.status == 404
    with Session(identity_db) as session, session.begin():
        create_goal(
            session,
            a,
            corrected,
            goal_payload(
                1, reason="history_correction", correction_of=str(first), energy_kcal="2600"
            ),
        )
        assert goal_for_date(session, a, goal_payload().effective_from).id == corrected
        assert (
            goal_for_date(session, a, goal_payload().effective_from, snapshot_revision=1).id
            == first
        )
        assert session.get(GoalVersion, first).payload["energy_kcal"] == "2500"
    for operation in (
        "UPDATE app.goal_versions SET energy_kcal=1 WHERE id=:id",
        "DELETE FROM app.goal_versions WHERE id=:id",
    ):
        with pytest.raises(IntegrityError), identity_db.begin() as connection:
            connection.execute(text(operation), {"id": first})


@pytest.mark.parametrize(
    "field,value",
    [
        ("energy_kcal", "NaN"),
        ("energy_kcal", "Infinity"),
        ("energy_kcal", "-Infinity"),
        ("energy_kcal", "0"),
        ("energy_kcal", "20000.000001"),
        ("protein_g", "NaN"),
        ("protein_g", "5000.000001"),
        ("fat_g", "-1"),
    ],
)
def test_raw_sql_goal_ranges(identity_db, field, value):
    _, owner, _ = boot(identity_db)
    data = goal_payload().model_dump(exclude={"estimate"})
    with pytest.raises(DBAPIError) as error, identity_db.begin() as connection:
        connection.execute(insert(GoalTimeline).values(owner_id=owner, revision=1))
        connection.execute(
            insert(GoalVersion).values(
                id=uuid4(),
                owner_id=owner,
                revision=1,
                timeline_revision=1,
                payload=goal_payload().model_dump(mode="json") | {field: value},
                **(data | {field: value}),
            )
        )
    assert error.value.orig.sqlstate in {"23514", "22003"}
    if error.value.orig.sqlstate == "23514":
        constraint = "energy_range" if field == "energy_kcal" else f"{field}_range"
        assert error.value.orig.diag.constraint_name == f"ck_goal_versions_{constraint}"


def test_raw_sql_goal_correction_cannot_cross_owner(identity_db):
    _, a, _ = boot(identity_db)
    _, b, _ = boot(identity_db)
    goal = uuid4()
    with Session(identity_db) as session, session.begin():
        create_goal(session, a, goal, goal_payload())
    payload = goal_payload(reason="history_correction", correction_of=str(goal))
    with pytest.raises(IntegrityError) as error, identity_db.begin() as connection:
        connection.execute(insert(GoalTimeline).values(owner_id=b, revision=1))
        # Isolate the composite FK from the earlier target-presence trigger.
        # This ALTER belongs to the rejected test transaction and rolls back.
        connection.execute(text("ALTER TABLE app.goal_versions DISABLE TRIGGER goal_axis_insert"))
        connection.execute(
            insert(GoalVersion).values(
                id=uuid4(),
                owner_id=b,
                revision=1,
                timeline_revision=1,
                payload=payload.model_dump(mode="json"),
                **payload.model_dump(exclude={"estimate"}),
            )
        )
    assert error.value.orig.sqlstate == "23503"


def test_goal_snapshot_stays_fixed_owner_limit_epoch_ttl_and_stateless(identity_db):
    _, a, _ = boot(identity_db)
    _, b, _ = boot(identity_db)
    ids = [UUID(int=n) for n in (20, 40, 60)]
    with Session(identity_db) as session, session.begin():
        for index, entity in enumerate(ids):
            create_goal(session, a, entity, goal_payload(index))
        create_goal(session, b, uuid4(), goal_payload())
    with Session(identity_db) as session, session.begin():
        first = goal_page(session, a, limit=1, secret=SECRET)
    token = first["next_page_token"]
    original_cursor = parse_goal_cursor(token, SECRET)
    with Session(identity_db) as session, session.begin():
        create_goal(session, a, UUID(int=30), goal_payload(3))
    with Session(identity_db) as session, session.begin():
        second = goal_page(session, a, limit=1, page_token=token, secret=SECRET)
        third = goal_page(session, a, limit=1, page_token=second["next_page_token"], secret=SECRET)
        assert [
            first["items"][0]["entity_id"],
            second["items"][0]["entity_id"],
            third["items"][0]["entity_id"],
        ] == list(map(str, ids))
        assert third["next_page_token"] is None
        assert (
            parse_goal_cursor(second["next_page_token"], SECRET)["expires"]
            == original_cursor["expires"]
        )
        for _ in range(100):
            assert goal_page(session, a, limit=1, page_token=token, secret=SECRET) == second
        assert session.scalar(select(func.count()).select_from(OnlineReceipt)) == 2
    for owner, limit in ((b, 1), (a, 2)):
        with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
            goal_page(session, owner, limit=limit, page_token=token, secret=SECRET)
        assert error.value.status == 422
    expired = sign_goal_cursor(original_cursor | {"expires": 1}, SECRET)
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        goal_page(session, a, 1, expired, SECRET)
    assert error.value.code == "page_expired"
    with identity_db.begin() as connection:
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
            {"epoch": uuid4()},
        )
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        goal_page(session, a, 1, token, SECRET)
    assert error.value.status == 422


def test_private_http_requires_bootstrap_and_forbids_extra_writes(identity_db, database):
    _, _, url = database
    who = principal()
    app = create_app(
        Settings(database_url=url, catalog_page_token_secret=SECRET), engine=identity_db
    )
    app.dependency_overrides[current_principal] = lambda: who
    with TestClient(app) as client:
        for method, path, kwargs in (
            ("get", "/me", {}),
            ("get", "/me/goals", {}),
            ("get", "/products", {}),
            (
                "post",
                "/energy-estimates",
                {
                    "json": {
                        "age_years": 30,
                        "height_cm": "180",
                        "weight_kg": "80",
                        "equation_variant": "plus_5",
                        "activity_class": "line",
                    }
                },
            ),
            (
                "put",
                "/me/consents",
                {
                    "json": CONSENT.model_dump(),
                    "headers": {"Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
                },
            ),
        ):
            response = getattr(client, method)("/api/v1" + path, **kwargs)
            assert response.status_code == 403, response.text
            assert response.json()["code"] == "account_bootstrap_required"
        header = {"Idempotency-Key": str(uuid4())}
        assert client.post("/api/v1/me/bootstrap", headers=header, json={}).status_code == 422
        result = client.post("/api/v1/me/bootstrap", headers=header)
        assert result.status_code == 200, result.text
        assert client.post("/api/v1/me/bootstrap", headers=header).json() == result.json()
        assert client.get("/api/v1/me").json()["profile"] is None
        assert client.get("/api/v1/me/goals").json()["items"] == []
        assert client.patch("/api/v1/me", json={}).status_code == 405
        assert client.post("/api/v1/me/goals", json={}).status_code == 405
        for headers in (
            {},
            {"Idempotency-Key": str(uuid4()), "If-Match": "1"},
            {"Idempotency-Key": "x", "If-Match": '"1"'},
        ):
            assert (
                client.put(
                    "/api/v1/me/consents", headers=headers, json=CONSENT.model_dump()
                ).status_code
                == 422
            )


def test_runtime_api_can_bootstrap_but_cannot_rotate_epoch_or_rewrite_evidence(identity_db):
    who = principal()
    with Session(identity_db) as session, session.begin():
        session.execute(text("SET LOCAL ROLE calorie_app_api"))
        result = bootstrap(session, who, uuid4())
        assert result["account_generation"] == 1
        put_consents(session, UUID(result["account_id"]), CONSENT, 1, uuid4())
    for statement in (
        "UPDATE app.installation_state SET sync_epoch=gen_random_uuid()",
        "DELETE FROM app.online_receipts",
        "UPDATE app.online_receipts SET response=NULL",
        "SELECT app.prune_consent_responses()",
    ):
        with pytest.raises(ProgrammingError), identity_db.begin() as connection:
            connection.execute(text("SET LOCAL ROLE calorie_app_api"))
            connection.execute(text(statement))
    with identity_db.begin() as connection:
        connection.execute(text("SET LOCAL ROLE calorie_app_worker"))
        assert connection.scalar(text("SELECT app.prune_consent_responses()")) == 0


@pytest.mark.parametrize("role", ["calorie_app_api", "calorie_app_worker"])
def test_runtime_sql_cannot_transfer_private_owner_or_resurrect_profile(identity_db, role):
    _, a, _ = boot(identity_db)
    _, b, _ = boot(identity_db)
    entity = uuid4()
    with Session(identity_db) as session, session.begin():
        save_profile(
            session,
            a,
            entity,
            ProfilePayload(
                pseudonym="A", height_cm=None, activity_class="line", time_zone="Europe/Warsaw"
            ),
        )
        create_goal(session, a, uuid4(), goal_payload())
    for statement, params in (
        (
            "UPDATE app.user_profiles SET owner_id=:b,revision=revision+1 WHERE id=:id",
            {"b": b, "id": entity},
        ),
        (
            "UPDATE app.user_profiles SET id=:new,revision=revision+1 WHERE id=:id",
            {"new": uuid4(), "id": entity},
        ),
        (
            "UPDATE app.user_consents SET owner_id=:b,revision=revision+1 WHERE owner_id=:a",
            {"a": a, "b": b},
        ),
        (
            "UPDATE app.goal_timelines SET owner_id=:b,revision=revision+1 WHERE owner_id=:a",
            {"a": a, "b": b},
        ),
        ("UPDATE app.user_profiles SET pseudonym='B' WHERE id=:id", {"id": entity}),
        ("UPDATE app.user_consents SET ranking=true WHERE owner_id=:a", {"a": a}),
        ("UPDATE app.goal_timelines SET revision=revision+2 WHERE owner_id=:a", {"a": a}),
    ):
        with pytest.raises(IntegrityError) as error, identity_db.begin() as connection:
            connection.execute(text(f"SET LOCAL ROLE {role}"))
            connection.execute(text(statement), params)
        assert error.value.orig.sqlstate == "23514"
    with Session(identity_db) as session, session.begin():
        delete_profile(session, a, entity, 1)
    with pytest.raises(IntegrityError), identity_db.begin() as connection:
        connection.execute(text(f"SET LOCAL ROLE {role}"))
        connection.execute(
            text("UPDATE app.user_profiles SET deleted_at=NULL,revision=revision+1 WHERE id=:id"),
            {"id": entity},
        )
    with Session(identity_db) as session:
        assert session.get(Profile, entity).owner_id == a
        assert session.get(Profile, entity).deleted_at is not None


def test_account_anchor_and_deleting_guard_apply_to_raw_runtime_sql(identity_db):
    _, owner, _ = boot(identity_db)
    with identity_db.begin() as connection:
        connection.execute(text("SET LOCAL ROLE calorie_app_api"))
        connection.execute(
            text("UPDATE app.user_accounts SET generation=generation+1 WHERE id=:id"), {"id": owner}
        )
    for change in (
        "issuer='https://other.example.test'",
        "subject='new-subject'",
        "id=gen_random_uuid()",
        "created_at=clock_timestamp()",
        "generation=1",
        "state='deleting'",
    ):
        with pytest.raises(IntegrityError), identity_db.begin() as connection:
            connection.execute(text("SET LOCAL ROLE calorie_app_api"))
            connection.execute(
                text(f"UPDATE app.user_accounts SET {change} WHERE id=:id"), {"id": owner}
            )
    with Session(identity_db) as session, session.begin():
        begin_deleting(session, owner)
    for statement in (
        "UPDATE app.user_accounts SET state='active' WHERE id=:id",
        "UPDATE app.user_consents SET ranking=true,revision=revision+1 WHERE owner_id=:id",
        "INSERT INTO app.user_profiles(id,owner_id,revision,pseudonym,activity_class,time_zone) "
        "VALUES(gen_random_uuid(),:id,1,'A','line','Europe/Warsaw')",
    ):
        with pytest.raises(IntegrityError), identity_db.begin() as connection:
            connection.execute(text("SET LOCAL ROLE calorie_app_worker"))
            connection.execute(text(statement), {"id": owner})
    with pytest.raises(ProgrammingError), identity_db.begin() as connection:
        connection.execute(text("SET LOCAL ROLE calorie_app_api"))
        connection.execute(text("DELETE FROM app.user_accounts WHERE id=:id"), {"id": owner})


def test_moved_and_branched_goal_corrections_replace_heads_preserve_versions(identity_db):
    _, owner, _ = boot(identity_db)
    first, moved, branch, descendant = [uuid4() for _ in range(4)]
    day = goal_payload().effective_from
    with Session(identity_db) as session, session.begin():
        create_goal(session, owner, first, goal_payload())
        create_goal(
            session,
            owner,
            moved,
            goal_payload(
                1,
                reason="history_correction",
                correction_of=str(first),
                effective_from="2026-10-11",
            ),
        )
        assert goal_for_date(session, owner, day) is None
        assert goal_for_date(session, owner, day, 1).id == first
        create_goal(
            session,
            owner,
            branch,
            goal_payload(
                2,
                reason="history_correction",
                correction_of=str(first),
                effective_from="2026-10-12",
                energy_kcal="2600",
            ),
        )
        assert goal_for_date(session, owner, day + timedelta(days=2)) is None
        assert goal_for_date(session, owner, day + timedelta(days=3)).id == branch
        create_goal(
            session,
            owner,
            descendant,
            goal_payload(
                3,
                reason="history_correction",
                correction_of=str(branch),
                effective_from="2026-10-10",
                energy_kcal="2700",
            ),
        )
        assert goal_for_date(session, owner, day + timedelta(days=1)).id == descendant
        assert session.get(GoalVersion, first).payload == goal_payload().model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(GoalVersion)) == 4


def test_upgrade_existing_e2_account_backfills_consents_preserves_identity(identity_db, database):
    engine, migrate, _ = database
    migrate("downgrade", "0005_ration_cursors")
    active, deleting = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(UserAccount).values(
                id=active,
                issuer="https://e2.example.test",
                subject="active",
                state="active",
                generation=7,
            )
        )
        connection.execute(
            insert(UserAccount).values(
                id=deleting,
                issuer="https://e2.example.test",
                subject="deleting",
                state="deleting",
                generation=3,
            )
        )
    migrate("upgrade", "head")
    migrate("check")
    with Session(engine) as session, session.begin():
        assert session.get(UserAccount, active).generation == 7
        assert session.get(UserAccount, deleting).state == "deleting"
        for account in (active, deleting):
            consent = session.get(UserConsent, account)
            assert consent.revision == 1
            assert consent.ranking is False and consent.automatic_energy_adjustment is False
        assert read_profile(session, active)["profile"] is None
        epoch = session.get(InstallationState, 1).sync_epoch
    with Session(engine) as restarted:
        assert current_epoch(restarted) == epoch


def test_goal_page_expiry_boundary_and_generation_binding(identity_db, monkeypatch):
    from calorie_app.modules.profiles import pagination

    _, owner, _ = boot(identity_db)
    with Session(identity_db) as session, session.begin():
        create_goal(session, owner, UUID(int=1), goal_payload())
        create_goal(session, owner, UUID(int=2), goal_payload(1))
        token = goal_page(session, owner, 1, secret=SECRET)["next_page_token"]
    cursor = parse_goal_cursor(token, SECRET)
    expiry = pagination.EPOCH + timedelta(microseconds=cursor["expires"])
    with monkeypatch.context() as patch:
        patch.setattr(pagination, "database_now", lambda _: expiry - timedelta(microseconds=1))
        with Session(identity_db) as session, session.begin():
            assert goal_page(session, owner, 1, token, SECRET)["items"][0]["entity_id"] == str(
                UUID(int=2)
            )
        patch.setattr(pagination, "database_now", lambda _: expiry)
        with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
            goal_page(session, owner, 1, token, SECRET)
        assert error.value.code == "page_expired"
    with identity_db.begin() as connection:
        connection.execute(
            text("UPDATE app.user_accounts SET generation=generation+1 WHERE id=:id"), {"id": owner}
        )
    with pytest.raises(DomainError) as error, Session(identity_db) as session, session.begin():
        goal_page(session, owner, 1, token, SECRET)
    assert error.value.status == 422


def test_raw_sql_goal_axis_cannot_commit_gaps_or_silent_counter_updates(identity_db):
    _, owner, _ = boot(identity_db)
    with pytest.raises(IntegrityError) as error, identity_db.begin() as connection:
        connection.execute(insert(GoalTimeline).values(owner_id=owner, revision=1))
    assert error.value.orig.sqlstate == "23514"
    with Session(identity_db) as session, session.begin():
        create_goal(session, owner, uuid4(), goal_payload())
    with pytest.raises(IntegrityError) as error, identity_db.begin() as connection:
        connection.execute(text("SET LOCAL ROLE calorie_app_worker"))
        connection.execute(
            text("UPDATE app.goal_timelines SET revision=revision+1 WHERE owner_id=:id"),
            {"id": owner},
        )
    assert error.value.orig.sqlstate == "23514"
    with Session(identity_db) as session:
        assert session.get(GoalTimeline, owner).revision == 1


def test_raw_sql_multirow_correction_cycle_requires_existing_earlier_version(identity_db):
    _, owner, _ = boot(identity_db)
    a, b = uuid4(), uuid4()
    rows = []
    for index, entity, target in ((0, a, b), (1, b, a)):
        payload = goal_payload(index, reason="history_correction", correction_of=str(target))
        rows.append(
            dict(
                id=entity,
                owner_id=owner,
                revision=1,
                timeline_revision=index + 1,
                payload=payload.model_dump(mode="json"),
                **payload.model_dump(exclude={"estimate"}),
            )
        )
    with pytest.raises(IntegrityError) as error, identity_db.begin() as connection:
        connection.execute(insert(GoalTimeline).values(owner_id=owner, revision=1))
        connection.execute(insert(GoalVersion).values(rows))
    assert error.value.orig.sqlstate == "23514"
    assert "earlier owner version" in error.value.orig.diag.message_primary
    with Session(identity_db) as session:
        assert session.scalar(select(func.count()).select_from(GoalVersion)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"energy_kcal": "20001"},
        {"energy_kcal": 2500},
        {"protein_g": "NaN"},
        {"time_zone": "Europe/Imaginary"},
        {"timeline_base_revision": 0.0},
    ],
)
def test_raw_sql_goal_snapshot_cannot_override_typed_domain_fields(identity_db, changes):
    _, owner, _ = boot(identity_db)
    payload = goal_payload()
    with pytest.raises(IntegrityError), identity_db.begin() as connection:
        connection.execute(insert(GoalTimeline).values(owner_id=owner, revision=1))
        connection.execute(
            insert(GoalVersion).values(
                id=uuid4(),
                owner_id=owner,
                revision=1,
                timeline_revision=1,
                payload=payload.model_dump(mode="json") | changes,
                **payload.model_dump(exclude={"estimate"}),
            )
        )
