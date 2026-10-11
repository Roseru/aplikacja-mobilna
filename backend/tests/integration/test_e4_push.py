import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, Principal
from calorie_app.main import create_app
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.identity.models import UserAccount
from calorie_app.modules.identity.service import begin_deleting, bootstrap
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.models import RecoveryMapping, SyncChange, SyncCounter, SyncReceipt
from calorie_app.modules.sync.repository import entity
from calorie_app.modules.sync.router import execute_one, preflight
from calorie_app.modules.sync.schemas import preflight_structure, validate_wire
from calorie_app.modules.sync.service import apply_operation
from calorie_app.modules.sync.snapshots import pull
from calorie_app.modules.sync.tokens import sign_checkpoint

ROOT = Path(__file__).resolve().parents[3]
SECRET = SecretStr("e4" * 32)
pytestmark = pytest.mark.integration


@pytest.fixture
def synced(database):
    engine, _, url = database
    who = Principal("https://e4.example.test", str(uuid4()), frozenset({"user", "admin"}))
    with Session(engine) as session, session.begin():
        boot = bootstrap(session, who, uuid4())
    owner = UUID(boot["account_id"])
    factory = sessionmaker(engine, expire_on_commit=False)
    page = pull(factory, owner, {}, SECRET)
    return engine, factory, who, owner, boot, page["checkpoint"], url


def operation(boot, kind="weight", *, entity_id=None, base=None, action="upsert", payload=None):
    filename = "diary-day" if kind == "diary_day" else kind.replace("_", "-")
    payload = (
        payload
        if payload is not None
        else json.loads(
            (ROOT / f"contracts/examples/valid/{filename}.json").read_text(encoding="utf-8")
        )
    )
    if kind == "meal":
        payload["goal_id"] = None
        payload["ration"] = None
        for item in payload["items"]:
            item["product"] = None
    return {
        "operation_id": str(uuid4()),
        "entity_type": kind,
        "entity_id": str(entity_id or uuid4()),
        "action": action,
        "base_revision": base,
        "sync_epoch": boot["sync_epoch"],
        "payload": payload if action == "upsert" else None,
    }


def request(boot, checkpoint, operations):
    return {
        "protocol_version": 1,
        "sync_epoch": boot["sync_epoch"],
        "checkpoint": checkpoint,
        "operations": operations,
    }


def send(synced, operations, checkpoint=None):
    engine, factory, who, owner, boot, cp, _ = synced
    data = request(boot, checkpoint or cp, operations)
    preflight_structure(data)
    owner, generation = preflight(factory, who, data, SECRET)
    results = [execute_one(factory, owner, generation, data, op, SECRET)[0] for op in operations]
    with Session(engine) as session:
        now = database_now(session)
    result = {
        "sync_epoch": boot["sync_epoch"],
        "server_time": now.isoformat().replace("+00:00", "Z"),
        "results": results,
    }
    validate_wire(result, "PushResponse")
    return results


@pytest.mark.parametrize(
    "kind", ["profile", "goal", "meal", "weight", "diary_day", "product_draft"]
)
def test_all_types_and_lost_response_replay(synced, kind):
    op = operation(synced[4], kind)
    if kind == "goal":
        op["payload"]["timeline_base_revision"] = 0
    assert send(synced, [op])[0]["status"] == "accepted"
    assert send(synced, [op])[0]["status"] == "already_applied"
    engine, _, _, owner, *_ = synced
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(SyncReceipt).where(SyncReceipt.owner_id == owner)
            )
            == 1
        )
        assert session.get(SyncCounter, owner).position == (2 if kind == "meal" else 1)


@pytest.mark.parametrize("kind", ["profile", "meal", "weight", "diary_day", "product_draft"])
def test_update_delete_replay_original_revision(synced, kind):
    op = operation(synced[4], kind)
    send(synced, [op])
    newer = operation(synced[4], kind, entity_id=op["entity_id"], base=1)
    assert send(synced, [newer])[0]["revision"] == 2
    assert send(synced, [op])[0]["revision"] == 1
    deleted = operation(synced[4], kind, entity_id=op["entity_id"], base=2, action="delete")
    assert send(synced, [deleted])[0]["revision"] == 3
    recreate = operation(synced[4], kind, entity_id=op["entity_id"])
    assert send(synced, [recreate])[0]["code"] == "entity_id_reserved"


def test_immutable_goal_before_axis_and_meal_day_effect(synced):
    goal = operation(synced[4], "goal")
    goal["payload"]["timeline_base_revision"] = 0
    send(synced, [goal])
    same = operation(synced[4], "goal", entity_id=goal["entity_id"], base=1)
    same["payload"]["timeline_base_revision"] = 999
    assert send(synced, [same])[0]["code"] == "goal_immutable"
    meal = operation(synced[4], "meal")
    meal["payload"]["goal_id"] = goal["entity_id"]
    assert send(synced, [meal])[0]["status"] == "accepted"
    deletion = operation(synced[4], "goal", entity_id=goal["entity_id"], base=1, action="delete")
    assert send(synced, [deletion])[0]["code"] == "goal_in_use"
    day = operation(synced[4], "diary_day")
    day["payload"]["local_date"] = meal["payload"]["local_date"]
    assert send(synced, [day])[0]["current"]["entity_type"] == "diary_day"


def test_mixed_results_durable_rejection_and_hash_reuse(synced):
    first = operation(synced[4])
    send(synced, [first])
    conflict = operation(synced[4], entity_id=first["entity_id"])
    rejected = operation(synced[4], "meal")
    rejected["payload"]["goal_id"] = str(uuid4())
    accepted = operation(synced[4])
    results = send(synced, [accepted, conflict, rejected])
    assert [r["status"] for r in results] == ["accepted", "conflict", "rejected"]
    assert results[2]["code"] == "dependency_missing"
    assert send(synced, [conflict, rejected]) == results[1:]
    changed = dict(first, payload=first["payload"] | {"weight_kg": "99"})
    assert send(synced, [changed])[0]["code"] == "operation_id_reused"


def test_savepoint_rolls_back_partial_domain_flush(synced, monkeypatch):
    from calorie_app.core.errors import DomainError
    from calorie_app.modules.diary import service as diary
    from calorie_app.modules.diary.models import DiaryDay

    original = diary.save_meal

    def failed(session, owner, entity_id, payload, **kwargs):
        original(session, owner, entity_id, payload, **kwargs)
        raise DomainError(422, "invalid_request")

    monkeypatch.setattr(diary, "save_meal", failed)
    op = operation(synced[4], "meal")
    assert send(synced, [op])[0]["code"] == "invalid_payload"
    with Session(synced[0]) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(DiaryDay).where(DiaryDay.owner_id == synced[3])
            )
            == 0
        )
        assert session.get(SyncCounter, synced[3]).position == 0


def test_receipt_minimization_61days_retains_original_ack(synced):
    op = operation(synced[4])
    send(synced, [op])
    with synced[0].begin() as c:
        c.execute(
            text(
                "UPDATE app.sync_receipts SET created_at=clock_timestamp()-interval '61 days' "
                "WHERE owner_id=:o"
            ),
            {"o": synced[3]},
        )
        c.execute(text("SET LOCAL ROLE calorie_app_worker"))
        assert c.scalar(text("SELECT app.prune_sync(:o,1000)"), {"o": synced[3]})["receipts"] == 1
    assert send(synced, [op])[0]["revision"] == 1


def test_counter_commit_order_with_actual_blocking(synced):
    engine, factory, _, owner, boot, cp, _ = synced
    ops = [operation(boot), operation(boot)]
    data = request(boot, cp, ops)
    entered, release = Event(), Event()

    def first():
        with factory() as session, session.begin():
            result = apply_operation(session, owner, data, ops[0], SECRET, 1)
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            entered.pid = pid
            entered.set()
            assert release.wait(10)
        return result

    with ThreadPoolExecutor(2) as pool:
        slow = pool.submit(first)
        assert entered.wait(10)
        fast = pool.submit(execute_one, factory, owner, 1, data, ops[1], SECRET)
        deadline = monotonic() + 10
        found = False
        with engine.connect() as c:
            while monotonic() < deadline:
                if c.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                        "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"pid": entered.pid},
                ):
                    found = True
                    break
        release.set()
        assert found
        assert slow.result()["status"] == fast.result()[0]["status"] == "accepted"
    with Session(engine) as session:
        changes = list(
            session.scalars(
                select(SyncChange).where(SyncChange.owner_id == owner).order_by(SyncChange.position)
            )
        )
        assert [r.entity["entity_id"] for r in changes] == [op["entity_id"] for op in ops]


@pytest.mark.parametrize("drift", ["deleting", "generation", "epoch", "provider"])
def test_http_late_failure_preserves_prefix_without_ack(synced, drift):
    engine, _, who, owner, boot, cp, url = synced
    app = create_app(Settings(database_url=url, catalog_page_token_secret=SECRET), engine=engine)

    class Verifier:
        calls = 0

        async def verify(self, token):
            self.calls += 1
            if self.calls == 3:
                if drift == "provider":
                    raise AuthFailure(503, "identity_provider_unavailable")
                with Session(engine) as s, s.begin():
                    if drift == "deleting":
                        begin_deleting(s, owner)
                    elif drift == "generation":
                        s.get(UserAccount, owner).generation += 1
                    else:
                        s.execute(
                            text("UPDATE app.installation_state SET sync_epoch=:e"), {"e": uuid4()}
                        )
            return who

        async def close(self):
            pass

    app.state.oidc_verifier = Verifier()
    ops = [operation(boot), operation(boot)]
    with TestClient(app) as client:
        result = client.post(
            "/api/v1/sync/push",
            json=request(boot, cp, ops),
            headers={"Authorization": "Bearer synthetic"},
        )
    assert result.status_code in {403, 409, 503}, result.text
    assert set(result.json()) == {"code", "message", "details", "request_id"}
    with Session(engine) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(SyncReceipt).where(SyncReceipt.owner_id == owner)
            )
            == 1
        )
        assert entity(s, owner, "weight", UUID(ops[0]["entity_id"])) is not None
        assert entity(s, owner, "weight", UUID(ops[1]["entity_id"])) is None


def test_recovery_two_devices_mapping_and_changed_target(synced):
    source = uuid4()
    source_epoch = uuid4()

    def recover(value="82.5"):
        op = operation(synced[4])
        op["payload"]["weight_kg"] = value
        op["recovery"] = {
            "source_epoch": str(source_epoch),
            "source_entity_id": str(source),
            "source_revision": 1,
            "source_operation_id": None,
            "decision": "recreate_missing",
        }
        return op

    a, b = recover(), recover()
    first = send(synced, [a])[0]
    second = send(synced, [b])[0]
    assert first["status"] == "accepted" and second["status"] == "already_applied"
    assert second["entity_id"] == b["entity_id"]
    assert second["recovery_mapping"]["target_entity_id"] == a["entity_id"]
    assert send(synced, [recover("83")])[0]["code"] == "recovery_content_conflict"
    with Session(synced[0]) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RecoveryMapping)
                .where(RecoveryMapping.owner_id == synced[3])
            )
            == 1
        )


def test_db_clock_after_actual_lock_wait_expires_checkpoint_and_preserves_prefix(synced):
    engine, factory, who, owner, boot, _, _ = synced
    with Session(engine) as session:
        observed = database_now(session)
        epoch = UUID(boot["sync_epoch"])
    deadline = observed + timedelta(seconds=1)
    cp = sign_checkpoint(
        SECRET,
        owner_id=owner,
        generation=1,
        epoch=epoch,
        position=0,
        now=deadline - timedelta(days=30),
    )
    ops = [operation(boot), operation(boot)]
    data = request(boot, cp, ops)
    preflight(factory, who, data, SECRET)
    assert execute_one(factory, owner, 1, data, ops[0], SECRET)[0]["status"] == "accepted"
    with ThreadPoolExecutor(1) as pool, engine.begin() as blocker:
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        blocker.execute(
            text("SELECT id FROM app.user_accounts WHERE id=:o FOR UPDATE"), {"o": owner}
        )
        pending = pool.submit(execute_one, factory, owner, 1, data, ops[1], SECRET)
        bound = monotonic() + 10
        with engine.connect() as observer:
            while not observer.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                    "WHERE :pid=ANY(pg_blocking_pids(pid)))"
                ),
                {"pid": pid},
            ):
                assert monotonic() < bound
            # Qualification uses DB clock after this actual wait; no guessed sleeps.
            while observer.scalar(text("SELECT clock_timestamp()")) <= deadline:
                assert monotonic() < bound
        blocker.commit()
        with pytest.raises(SyncFailure) as caught:
            pending.result(timeout=10)
        assert caught.value.code == "sync_reconciliation_required"
    fresh = pull(factory, owner, {}, SECRET)["checkpoint"]
    assert [r["status"] for r in send(synced, ops, fresh)] == ["already_applied", "accepted"]
    with Session(engine) as session:
        assert session.get(SyncCounter, owner).position == 2


def test_counter_exhaustion_is_request_failure_without_receipt(synced):
    engine, factory, _, owner, boot, cp, _ = synced
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.sync_counters(owner_id,position) VALUES(:o,9223372036854775807) "
                "ON CONFLICT(owner_id) DO UPDATE SET position=excluded.position"
            ),
            {"o": owner},
        )
    op = operation(boot)
    with pytest.raises(SyncFailure) as caught:
        execute_one(factory, owner, 1, request(boot, cp, [op]), op, SECRET)
    assert caught.value.code == "sync_counter_exhausted"
    with Session(engine) as session:
        assert session.get(SyncReceipt, (owner, UUID(op["operation_id"]))) is None
        assert entity(session, owner, "weight", UUID(op["entity_id"])) is None


def test_missing_exact_product_dependency_has_durable_receipt_and_no_automatic_day(synced):
    from calorie_app.modules.diary.models import DiaryDay

    op = operation(synced[4], "meal")
    op["payload"]["items"][0]["product"] = {"product_id": str(uuid4()), "revision": 1}
    op["payload"]["items"][0]["nutrition_origin"] = "catalog_snapshot"
    result = send(synced, [op])[0]
    assert result["code"] == "dependency_missing"
    assert send(synced, [op])[0] == result
    with Session(synced[0]) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(DiaryDay).where(DiaryDay.owner_id == synced[3])
            )
            == 0
        )
