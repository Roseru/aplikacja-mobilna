import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.integrations.keycloak import Principal
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
from calorie_app.modules.sync.router import execute_one, preflight
from calorie_app.modules.sync.schemas import preflight_structure, validate_wire
from calorie_app.modules.sync.snapshot_models import SyncSession, SyncSessionItem
from calorie_app.modules.sync.tokens import read_token, sign_checkpoint, timestamp
from tests.integration.test_e4_push import operation, request
from tests.support.deletion_regression import begin as begin_deletion

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
    from calorie_app.modules.sync.tokens import sign_token

    claims = read_token(
        first["page_token"], SECRET, kind="page", owner_id=a, generation=1, epoch=epoch
    )
    wrong_generation = first | {"page_token": sign_token(claims | {"generation": 2}, SECRET)}
    with pytest.raises(SyncFailure, match="account_generation_changed"):
        follow(factory, a, wrong_generation, 1)
    with engine.begin() as connection:
        begin_deletion(connection, a, uuid4(), 1)
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
    for _ in range(2):
        add_weight(engine, a)
    for _ in range(4):
        assert snapshots.pull(factory, a, {"limit": 1}, SECRET)["page_token"]
    with pytest.raises(SyncFailure, match="sync_resources_exhausted"):
        snapshots.pull(factory, a, {"limit": 1}, SECRET)
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
        assert result["items"] == 2 and result["sessions"] == 1
    snapshots.pull(factory, a, {"limit": 1}, SECRET)


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
            "community_receipts": 0,
            "community_quotas": 0,
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
        snapshots.pull(factory, a, {"limit": 1}, SECRET)
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
    original = snapshots._item_size

    def pause(state, value):
        size = original(state, value)
        if state.item_count == 0:
            copying.set()
            assert release.wait(10), "test did not release materializer"
        return size

    monkeypatch.setattr(snapshots, "_item_size", pause)

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


def test_single_page_initial_reads_leave_no_retained_copy(owners):
    engine, factory, owner, _ = owners
    for _ in range(6):
        response = snapshots.pull(factory, owner, {}, SECRET)
        assert response["page_token"] is None and response["checkpoint"]
        assert response["snapshot_token"] and response["entities"] == []
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyncSession)) == 0
        assert session.scalar(select(func.count()).select_from(SyncSessionItem)) == 0


def graph_fingerprint(engine, owner):
    with engine.connect() as connection:
        return {
            table: tuple(
                connection.execute(
                    text(
                        "SELECT count(*),encode(sha256(convert_to(COALESCE("
                        "jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text,"
                        "'UTF8')),'hex') FROM app." + table + " t WHERE owner_id=:owner"
                    ),
                    {"owner": owner},
                ).one()
            )
            for table in ("sync_sessions", "sync_session_items")
        }


@pytest.mark.parametrize("scope", ["calorie-app", "calorie-app:energy_estimates_v1"])
def test_small_reads_at_four_live_graphs_preserve_them_without_writes(owners, monkeypatch, scope):
    engine, factory, owner, _ = owners
    for _ in range(10):
        add_weight(engine, owner)
    pages = [snapshots.pull(factory, owner, {"limit": 1}, SECRET) for _ in range(4)]
    assert all(page["page_token"] and page["checkpoint"] is None for page in pages)
    frozen = graph_fingerprint(engine, owner)
    assert frozen["sync_sessions"][0] == 4 and frozen["sync_session_items"][0] == 40
    graph_writes = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        sql = statement.lower().lstrip()
        if sql.startswith(("insert", "update", "delete")) and "sync_session" in sql:
            graph_writes.append(sql)

    event.listen(engine, "before_cursor_execute", record)
    try:
        small = snapshots.pull(factory, owner, {}, SECRET, installation_id=scope)
        assert small["page_token"] is None and small["checkpoint"]
        assert len(small["entities"]) == 10 and small["snapshot_token"]
        read = snapshots.pull(
            factory,
            owner,
            {"sync_epoch": small["sync_epoch"], "checkpoint": small["checkpoint"]},
            SECRET,
            installation_id=scope,
        )
        assert read["entities"] == [] and read["checkpoint"] and read["page_token"] is None
        with pytest.raises(SyncFailure, match="sync_resources_exhausted"):
            snapshots.pull(factory, owner, {"limit": 1}, SECRET, installation_id=scope)
        # Count exactly fits; byte packing alone requires continuation.
        monkeypatch.setattr(snapshots, "MAX_RESPONSE_BYTES", 5500)
        with pytest.raises(SyncFailure, match="sync_resources_exhausted"):
            snapshots.pull(factory, owner, {"limit": 10}, SECRET, installation_id=scope)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert graph_writes == []
    assert graph_fingerprint(engine, owner) == frozen
    assert follow(factory, owner, pages[0], 1)["entities"][0]["revision"] == 1


def test_six_ordinary_write_cycles_use_stateless_checkpoints_and_stable_retry(owners):
    engine, factory, owner, _ = owners
    who = Principal("https://snapshot.test", str(owner), frozenset({"user"}))
    checkpoint = None
    epoch = None
    for _ in range(6):
        query = {} if checkpoint is None else {"checkpoint": checkpoint, "sync_epoch": epoch}
        before = snapshots.pull(factory, owner, query, SECRET)
        epoch = before["sync_epoch"]
        op = operation({"sync_epoch": epoch})
        data = request({"sync_epoch": epoch}, before["checkpoint"], [op])
        frozen = snapshots._json(data)
        preflight_structure(data)
        actual_owner, generation = preflight(factory, who, data, SECRET)
        accepted, _at = execute_one(factory, actual_owner, generation, data, op, SECRET)
        assert accepted["status"] == "accepted" and accepted["revision"] == 1
        retried, _at = execute_one(factory, actual_owner, generation, data, op, SECRET)
        assert retried["status"] == "already_applied" and retried["revision"] == 1
        assert snapshots._json(data) == frozen
        after = snapshots.pull(
            factory, owner, {"sync_epoch": epoch, "checkpoint": before["checkpoint"]}, SECRET
        )
        validate_wire(before, "PullResponse")
        validate_wire(after, "PullResponse")
        assert len(after["entities"]) == 1 and after["page_token"] is None
        checkpoint = after["checkpoint"]
    assert graph_fingerprint(engine, owner)["sync_sessions"][0] == 0
    assert graph_fingerprint(engine, owner)["sync_session_items"][0] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SyncReceipt)) == 6
        assert session.scalar(select(func.count()).select_from(Weight)) == 6


def test_single_page_recovery_proof_keeps_requested_receipts_and_mappings(owners):
    engine, factory, owner, _ = owners
    target = add_weight(engine, owner)
    found, missing, source_epoch, source_id = (uuid4() for _ in range(4))
    with Session(engine) as session, session.begin():
        epoch = current_epoch(session)
        session.add(
            RecoveryMapping(
                owner_id=owner,
                source_epoch=source_epoch,
                source_entity_id=source_id,
                entity_type="weight",
                target_entity_id=target,
            )
        )
        session.add(
            SyncReceipt(
                owner_id=owner,
                operation_id=found,
                request_hash="d" * 64,
                source_epoch=epoch,
                entity_type="weight",
                entity_id=target,
                status="accepted",
                revision=1,
                response={"unneeded_blob": "x" * 600000},
            )
        )
    response = snapshots.pull(
        factory, owner, {"limit": 3, "recovery_operation_ids": [str(found), str(missing)]}, SECRET
    )
    validate_wire(response, "PullResponse")
    assert response["page_token"] is None and response["checkpoint"]
    assert len(response["entities"]) == len(response["recovery_mappings"]) == 1
    assert [r["operation_id"] for r in response["operation_receipts"]] == [str(found)]
    assert response["operation_receipts"][0]["code"] is None
    assert response["recovery_mappings"][0]["target_revision"] == 1
    assert graph_fingerprint(engine, owner)["sync_sessions"][0] == 0


def push_one(factory, owner, checkpoint, epoch, op):
    data = request({"sync_epoch": epoch}, checkpoint, [op])
    preflight_structure(data)
    who = Principal("https://snapshot.test", str(owner), frozenset({"user"}))
    actual_owner, generation = preflight(factory, who, data, SECRET)
    return execute_one(factory, actual_owner, generation, data, op, SECRET)[0]


def test_single_page_keeps_null_zero_and_incremental_tombstone(owners):
    engine, factory, owner, _ = owners
    initial = snapshots.pull(factory, owner, {}, SECRET)
    epoch = initial["sync_epoch"]
    meal = operation({"sync_epoch": epoch}, "meal")
    meal["payload"]["items"][0]["nutrition_per_100"] = {
        "energy_kcal": "100",
        "protein_g": None,
        "fat_g": "0",
        "carbs_g": "20",
    }
    assert push_one(factory, owner, initial["checkpoint"], epoch, meal)["status"] == "accepted"
    full = snapshots.pull(factory, owner, {}, SECRET)
    copied = next(v for v in full["entities"] if v["entity_id"] == meal["entity_id"])
    assert copied["payload"]["items"][0]["nutrition_per_100"] == {
        "energy_kcal": "100",
        "protein_g": None,
        "fat_g": "0",
        "carbs_g": "20",
    }
    deleted = operation(
        {"sync_epoch": epoch}, "meal", entity_id=UUID(meal["entity_id"]), base=1, action="delete"
    )
    assert push_one(factory, owner, full["checkpoint"], epoch, deleted)["status"] == "accepted"
    after = snapshots.pull(
        factory, owner, {"checkpoint": full["checkpoint"], "sync_epoch": epoch}, SECRET
    )
    tombstone = next(v for v in after["entities"] if v["entity_id"] == meal["entity_id"])
    assert tombstone["deleted"] is True and tombstone["payload"] is None
    assert after["page_token"] is None and after["checkpoint"]
    validate_wire(full, "PullResponse")
    validate_wire(after, "PullResponse")
    assert graph_fingerprint(engine, owner)["sync_sessions"][0] == 0


def test_single_page_rechecks_starting_checkpoint_age_after_copy(owners, monkeypatch):
    engine, factory, owner, _ = owners
    with Session(engine) as session:
        epoch, now = current_epoch(session), database_now(session)
    checkpoint = sign_checkpoint(
        SECRET, owner_id=owner, generation=1, epoch=epoch, position=0, now=now - timedelta(days=30)
    )
    times = iter([now, now + timedelta(microseconds=1)])
    monkeypatch.setattr(snapshots, "database_now", lambda _: next(times))
    with pytest.raises(SyncFailure, match="sync_cursor_expired"):
        snapshots.pull(factory, owner, {"checkpoint": checkpoint, "sync_epoch": str(epoch)}, SECRET)
    assert graph_fingerprint(engine, owner)["sync_sessions"][0] == 0


def test_utf8_byte_budget_can_split_an_exact_count_limit(owners, monkeypatch):
    engine, factory, owner, _ = owners
    initial = snapshots.pull(factory, owner, {}, SECRET)
    epoch = initial["sync_epoch"]
    for _ in range(2):
        meal = operation({"sync_epoch": epoch}, "meal")
        meal["payload"]["title"] = "漢" * 60
        meal["payload"]["items"][0]["item_id"] = str(uuid4())
        assert push_one(factory, owner, initial["checkpoint"], epoch, meal)["status"] == "accepted"
    full = snapshots.pull(factory, owner, {}, SECRET)

    # Independent UTF-8 oracle over the wire DTO; no production size helper.
    def encoded(value):
        return len(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )

    envelope = full | {"entities": [], "checkpoint": None}
    largest_size = max(encoded(value) for value in full["entities"])
    monkeypatch.setattr(
        snapshots, "MAX_RESPONSE_BYTES", encoded(envelope) + 4096 + largest_size + 1
    )
    first = snapshots.pull(factory, owner, {"limit": len(full["entities"])}, SECRET)
    assert len(first["entities"]) == 1 and first["checkpoint"] is None and first["page_token"]
    assert len("漢".encode()) == 3
    values = first["entities"][:]
    page = first
    while page["page_token"]:
        page = follow(factory, owner, page, len(full["entities"]))
        values.extend(page["entities"])
    assert {v["entity_id"] for v in values} == {v["entity_id"] for v in full["entities"]}
    assert page["checkpoint"]
