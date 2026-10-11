from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.diary.models import Weight
from calorie_app.modules.diary.service import save_weight
from calorie_app.modules.identity.models import UserAccount
from calorie_app.modules.identity.service import current_epoch, lock_account
from calorie_app.modules.sync import snapshots
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.models import RecoveryMapping, SyncChange, SyncReceipt
from calorie_app.modules.sync.repository import append_change, entity, lock_counter
from calorie_app.modules.sync.retention import prune
from calorie_app.modules.sync.snapshot_models import SyncSession, SyncSessionItem
from calorie_app.modules.sync.tokens import read_token, sign_checkpoint, timestamp

pytestmark = pytest.mark.integration
SECRET = SecretStr("31" * 32)


@pytest.fixture
def owners(database):
    engine, _, _ = database
    a, b = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                UserAccount(id=value, issuer="https://snapshot.test", subject=str(value))
                for value in (a, b)
            ]
        )
    yield engine, sessionmaker(engine), a, b
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")


def add_weight(engine, owner, entity_id=None, base=0):
    entity_id = entity_id or uuid4()
    with Session(engine) as session, session.begin():
        lock_account(session, owner)
        counter = lock_counter(session, owner)
        save_weight(
            session,
            owner,
            entity_id,
            {
                "weight_kg": str(70 + base),
                "occurred_at": "2026-10-10T12:00:00Z",
                "local_date": "2026-10-10",
                "time_zone": "UTC",
            },
            base_revision=base,
        )
        append_change(session, counter, entity(session, owner, "weight", entity_id))
    return entity_id


def follow(factory, owner, response, limit, checkpoint=None):
    query = {
        "sync_epoch": response["sync_epoch"],
        "page_token": response["page_token"],
        "limit": limit,
    }
    query["checkpoint" if checkpoint else "snapshot_token"] = (
        checkpoint or response["snapshot_token"]
    )
    return snapshots.pull(factory, owner, query, SECRET)


def test_full_snapshot_three_arrays_shared_limit_frozen_data_and_final_retry(owners, monkeypatch):
    engine, factory, a, b = owners
    ids = [add_weight(engine, a) for _ in range(3)]
    add_weight(engine, b)
    requested = [uuid4(), uuid4()]
    with Session(engine) as session, session.begin():
        epoch = current_epoch(session)
        for target in ids:
            session.add(
                RecoveryMapping(
                    owner_id=a,
                    source_epoch=uuid4(),
                    source_entity_id=uuid4(),
                    entity_type="weight",
                    target_entity_id=target,
                )
            )
        for operation in requested:
            session.add(
                SyncReceipt(
                    owner_id=a,
                    operation_id=operation,
                    request_hash="a" * 64,
                    source_epoch=epoch,
                    entity_type="weight",
                    entity_id=ids[0],
                    status="accepted",
                    revision=1,
                )
            )
    first = snapshots.pull(
        factory, a, {"limit": 4, "recovery_operation_ids": [str(x) for x in requested]}, SECRET
    )
    assert (
        len(first["entities"]) + len(first["recovery_mappings"]) + len(first["operation_receipts"])
        == 4
    )
    assert first["checkpoint"] is None
    add_weight(engine, a, ids[0], base=1)
    add_weight(engine, a)
    final = follow(factory, a, first, 4)
    assert final["page_token"] is None and final["checkpoint"]
    assert len(final["recovery_mappings"]) + len(final["operation_receipts"]) == 4
    assert all(
        x["target_revision"] == 1 for x in first["recovery_mappings"] + final["recovery_mappings"]
    )
    assert {x["operation_id"] for x in final["operation_receipts"]} == {str(x) for x in requested}
    with Session(engine) as session:
        frozen = session.scalar(select(SyncSession).where(SyncSession.owner_id == a))
        assert frozen.high_position == 3
        endtime = frozen.created_at + timedelta(minutes=5)
    monkeypatch.setattr(snapshots, "database_now", lambda _: endtime)
    assert follow(factory, a, first, 4) == final


def test_incremental_freezes_high_and_keeps_original_checkpoint_age(owners, monkeypatch):
    engine, factory, a, _ = owners
    base = snapshots.pull(factory, a, {}, SECRET)["checkpoint"]
    ids = [add_weight(engine, a) for _ in range(3)]
    with Session(engine) as session:
        now = database_now(session)
        epoch = current_epoch(session)
    first = snapshots.pull(
        factory, a, {"checkpoint": base, "sync_epoch": str(epoch), "limit": 1}, SECRET
    )
    add_weight(engine, a, ids[0], base=1)
    second = follow(factory, a, first, 1, base)
    third = follow(factory, a, second, 1, base)
    assert all(x["revision"] == 1 for page in (first, second, third) for x in page["entities"])
    assert third["checkpoint"] and third["page_token"] is None
    nextread = snapshots.pull(
        factory, a, {"checkpoint": third["checkpoint"], "sync_epoch": str(epoch)}, SECRET
    )
    assert len(nextread["entities"]) == 1 and nextread["entities"][0]["revision"] == 2
    claims = read_token(base, SECRET, kind="checkpoint", owner_id=a, generation=1, epoch=epoch)
    monkeypatch.setattr(
        snapshots,
        "database_now",
        lambda _: timestamp(claims["issued"]) + timedelta(days=30, microseconds=1),
    )
    with pytest.raises(SyncFailure, match="sync_cursor_expired"):
        follow(factory, a, first, 1, base)
    assert now >= timestamp(claims["issued"])


def test_page_binding_combined_tokens_filters_epoch_precedence_and_deleting(owners):
    engine, factory, a, b = owners
    for _ in range(3):
        add_weight(engine, a)
    first = snapshots.pull(factory, a, {"limit": 1}, SECRET)
    other = snapshots.pull(factory, a, {"limit": 1}, SECRET)
    with pytest.raises(SyncFailure, match="invalid_sync_token"):
        follow(factory, b, first, 1)
    with pytest.raises(SyncFailure, match="invalid_sync_token"):
        follow(factory, a, first, 2)
    with pytest.raises(SyncFailure, match="invalid_sync_token"):
        follow(factory, a, first | {"snapshot_token": other["snapshot_token"]}, 1)
    with Session(engine) as session:
        epoch = current_epoch(session)
        now = database_now(session)
    expired = sign_checkpoint(
        SECRET, owner_id=a, generation=1, epoch=epoch, position=0, now=now - timedelta(days=31)
    )
    with pytest.raises(SyncFailure, match="sync_epoch_changed"):
        snapshots.pull(factory, a, {"sync_epoch": str(uuid4()), "checkpoint": expired}, SECRET)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE app.user_accounts SET generation=2 WHERE id=:id"), {"id": a}
        )
    with pytest.raises(SyncFailure, match="account_generation_changed"):
        follow(factory, a, first, 1)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.user_accounts SET state='deleting',generation=generation+1 WHERE id=:id"
            ),
            {"id": a},
        )
    with pytest.raises(SyncFailure, match="account_deleting"):
        follow(factory, a, first, 1)


def test_snapshot_exact_60minute_ttl_including_final_retry(owners, monkeypatch):
    engine, factory, a, _ = owners
    add_weight(engine, a)
    add_weight(engine, a)
    first = snapshots.pull(factory, a, {"limit": 1}, SECRET)
    final = follow(factory, a, first, 1)
    with Session(engine) as session:
        state = session.scalar(select(SyncSession).where(SyncSession.owner_id == a))
        expires = state.expires_at
    monkeypatch.setattr(snapshots, "database_now", lambda _: expires - timedelta(microseconds=1))
    assert follow(factory, a, first, 1) == final
    monkeypatch.setattr(snapshots, "database_now", lambda _: expires)
    with pytest.raises(SyncFailure, match="snapshot_expired"):
        follow(factory, a, first, 1)


def test_byte_pages_do_not_drop_elements_and_resource_failure_rolls_back(owners, monkeypatch):
    engine, factory, a, _ = owners
    for _ in range(10):
        add_weight(engine, a)
    monkeypatch.setattr(snapshots, "MAX_RESPONSE_BYTES", 5500)
    response = snapshots.pull(factory, a, {}, SECRET)
    found = response["entities"][:]
    while response["page_token"]:
        response = follow(factory, a, response, 500)
        found.extend(response["entities"])
    assert len(found) == 10 and len({x["entity_id"] for x in found}) == 10
    monkeypatch.setattr(snapshots, "MAX_SESSION_BYTES", 1)
    with pytest.raises(SyncFailure, match="sync_resources_exhausted"):
        snapshots.pull(factory, a, {}, SECRET)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(SyncSession).where(SyncSession.owner_id == a)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SyncSessionItem)
                .where(SyncSessionItem.owner_id == a)
            )
            == 10
        )


def test_account_session_limit_is_serialized_and_expired_copies_are_bounded_pruned(owners):
    engine, factory, a, _ = owners
    for _ in range(4):
        snapshots.pull(factory, a, {}, SECRET)
    with pytest.raises(SyncFailure, match="sync_resources_exhausted"):
        snapshots.pull(factory, a, {}, SECRET)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.sync_sessions SET created_at=created_at-interval '2 hours',"
                "expires_at=expires_at-interval '2 hours' WHERE owner_id=:owner"
            ),
            {"owner": a},
        )
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_worker")
        result = connection.scalar(text("SELECT app.prune_sync(:owner,2)"), {"owner": a})
        assert result["sessions"] == 2
    snapshots.pull(factory, a, {}, SECRET)


def test_retention_minimizes_receipts_preserves_mapping_and_active_incremental(owners):
    engine, factory, a, b = owners
    checkpoint = snapshots.pull(factory, a, {}, SECRET)["checkpoint"]
    ids = [add_weight(engine, a) for _ in range(3)]
    opid = uuid4()
    with Session(engine) as session, session.begin():
        epoch = current_epoch(session)
        session.add(
            SyncReceipt(
                owner_id=a,
                operation_id=opid,
                request_hash="b" * 64,
                source_epoch=epoch,
                entity_type="weight",
                entity_id=ids[0],
                status="accepted",
                revision=1,
                response={"status": "accepted"},
            )
        )
        session.add(
            RecoveryMapping(
                owner_id=a,
                source_epoch=uuid4(),
                source_entity_id=uuid4(),
                entity_type="weight",
                target_entity_id=ids[0],
            )
        )
    first = snapshots.pull(
        factory, a, {"checkpoint": checkpoint, "sync_epoch": str(epoch), "limit": 1}, SECRET
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.sync_changes SET created_at=created_at-interval '61 days' "
                "WHERE owner_id=:owner"
            ),
            {"owner": a},
        )
        connection.execute(
            text(
                "UPDATE app.sync_receipts SET created_at=created_at-interval '61 days' "
                "WHERE owner_id=:owner"
            ),
            {"owner": a},
        )
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL ROLE calorie_app_worker"))
        result = prune(session, a, 1)
        assert result == {
            "changes": 0,
            "receipts": 1,
            "items": 0,
            "sessions": 0,
            "read_items": 0,
            "read_sessions": 0,
        }
    with Session(engine) as session:
        receipt = session.get(SyncReceipt, (a, opid))
        assert (
            receipt.response is None and receipt.revision == 1 and receipt.request_hash == "b" * 64
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(RecoveryMapping)
                .where(RecoveryMapping.owner_id == a)
            )
            == 1
        )
    assert follow(factory, a, first, 1, checkpoint)["entities"][0]["revision"] == 1
    for table in ("sync_changes", "sync_receipts", "sync_sessions", "sync_session_items"):
        with pytest.raises(ProgrammingError), engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_worker")
            connection.execute(text(f"DELETE FROM app.{table} WHERE owner_id=:owner"), {"owner": a})
    with pytest.raises(ProgrammingError), engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
        connection.execute(text("SELECT app.prune_sync(:owner,1)"), {"owner": b})
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE app.sync_sessions SET created_at=created_at-interval '2 hours',"
                "expires_at=expires_at-interval '2 hours' WHERE owner_id=:owner"
            ),
            {"owner": a},
        )
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_worker")
        result = connection.scalar(text("SELECT app.prune_sync(:owner,1)"), {"owner": a})
        assert result["changes"] == 1 and result["items"] == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(SyncChange).where(SyncChange.owner_id == a)
            )
            == 2
        )


def test_snapshot_materialization_failure_leaves_no_published_copy(owners, monkeypatch):
    engine, factory, a, _ = owners
    for _ in range(3):
        add_weight(engine, a)
    original = snapshots._add_item

    def abort(session, state, kind, value):
        original(session, state, kind, value)
        if state.item_count == 2:
            session.flush()
            raise SyncFailure(503, "service_unavailable")

    monkeypatch.setattr(snapshots, "_add_item", abort)
    with pytest.raises(SyncFailure, match="service_unavailable"):
        snapshots.pull(factory, a, {}, SECRET)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyncSession)) == 0
        assert session.scalar(select(func.count()).select_from(SyncSessionItem)) == 0


def test_500_limit_counts_mappings_and_requested_receipts_together(owners):
    engine, factory, a, _ = owners
    ids = [uuid4() for _ in range(251)]
    operation = uuid4()
    with Session(engine) as session, session.begin():
        lock_account(session, a)
        lock_counter(session, a)
        epoch = current_epoch(session)
        # A representative existing E3 graph is a fixture, not 251 HTTP pushes.
        # Exercise the real constraints while keeping fixture setup bounded.
        session.execute(
            insert(Weight),
            [
                {
                    "id": target,
                    "owner_id": a,
                    "revision": 1,
                    "weight_kg": Decimal("70"),
                    "occurred_at": datetime(2026, 10, 10, 12, tzinfo=UTC),
                    "local_date": date(2026, 10, 10),
                    "time_zone": "UTC",
                }
                for target in ids
            ],
        )
        for target in ids[:250]:
            session.add(
                RecoveryMapping(
                    owner_id=a,
                    source_epoch=uuid4(),
                    source_entity_id=uuid4(),
                    entity_type="weight",
                    target_entity_id=target,
                )
            )
        session.add(
            SyncReceipt(
                owner_id=a,
                operation_id=operation,
                request_hash="c" * 64,
                source_epoch=epoch,
                entity_type="weight",
                entity_id=ids[0],
                status="accepted",
                revision=1,
            )
        )
    first = snapshots.pull(factory, a, {"recovery_operation_ids": [str(operation)]}, SECRET)
    assert len(first["entities"]) == 251
    assert len(first["recovery_mappings"]) == 249
    assert first["operation_receipts"] == []
    assert first["checkpoint"] is None
    last = follow(factory, a, first, 500)
    assert len(last["entities"]) == 0
    assert len(last["recovery_mappings"]) == 1
    assert len(last["operation_receipts"]) == 1
    assert last["checkpoint"] and last["page_token"] is None


def test_materialization_blocks_writer_and_captures_one_repeatable_read(owners, monkeypatch):
    engine, factory, a, _ = owners
    original_id = add_weight(engine, a)
    copying, release, writer_ready = Event(), Event(), Event()
    pid = []
    original = snapshots._add_item

    def pause(session, state, kind, value):
        original(session, state, kind, value)
        if state.item_count == 1:
            copying.set()
            assert release.wait(10), "test did not release materializer"

    monkeypatch.setattr(snapshots, "_add_item", pause)

    def writer():
        with Session(engine) as session, session.begin():
            pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            writer_ready.set()
            lock_account(session, a)
            counter = lock_counter(session, a)
            save_weight(
                session,
                a,
                original_id,
                {
                    "weight_kg": "71",
                    "occurred_at": "2026-10-10T12:00:00Z",
                    "local_date": "2026-10-10",
                    "time_zone": "UTC",
                },
                base_revision=1,
            )
            append_change(session, counter, entity(session, a, "weight", original_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        frozen = pool.submit(snapshots.pull, factory, a, {}, SECRET)
        assert copying.wait(10)
        mutation = pool.submit(writer)
        assert writer_ready.wait(10)
        try:
            blocked = False
            deadline = monotonic() + 5
            with engine.connect() as connection:
                while monotonic() < deadline:
                    blockers = connection.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid[0]}
                    )
                    if blockers:
                        blocked = True
                        break
            assert blocked, "writer must wait for materializer's account lock"
        finally:
            release.set()
        response = frozen.result(timeout=10)
        mutation.result(timeout=10)
    assert response["entities"][0]["revision"] == 1
    epoch = UUID(response["sync_epoch"])
    claims = read_token(
        response["checkpoint"], SECRET, kind="checkpoint", owner_id=a, generation=1, epoch=epoch
    )
    assert claims["position"] == 1
    current = snapshots.pull(
        factory, a, {"checkpoint": response["checkpoint"], "sync_epoch": str(epoch)}, SECRET
    )
    assert current["entities"][0]["revision"] == 2
