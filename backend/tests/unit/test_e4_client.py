"""Reference SQLite/HTTP evidence, never an Android/Room claim."""

import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.sync_client import ClientError, SyncHTTP, SyncStore  # noqa: E402
from tools.sync_client.wire import AdaptationRequired, exact_decimal  # noqa: E402

TIME = "2026-10-10T12:00:00Z"


def uid():
    return str(uuid4())


def boot(store, scope, *, epoch=None, generation=1, account=None):
    active = store.db.execute("SELECT * FROM active WHERE id=1").fetchone()
    existing = store.db.execute(
        "SELECT account_id FROM bindings WHERE scope=?", (scope,)
    ).fetchone()
    store.bootstrap(
        scope,
        {
            "account_id": account or (existing[0] if existing else uid()),
            "sync_epoch": epoch or uid(),
            "account_generation": generation,
            "server_time": TIME,
        },
        lease_generation=active["generation"],
    )
    return store.capture()


def page(
    context,
    *,
    entities=None,
    token=None,
    checkpoint="checkpoint",
    mode="snapshot",
    snapshot="snapshot",
    mappings=None,
    receipts=None,
):
    return {
        "sync_epoch": context.sync_epoch,
        "mode": mode,
        "snapshot_token": snapshot if mode == "snapshot" else None,
        "page_token": token,
        "checkpoint": None if token else checkpoint,
        "server_time": TIME,
        "entities": entities or [],
        "goal_timeline_revision": 0,
        "recovery_mappings": mappings or [],
        "operation_receipts": receipts or [],
    }


def snapshot(store, context, entities=None):
    session = store.start_pull(context, full=True)
    request = store.prepare_pull(context, session)
    store.apply_pull(context, session, request, page(context, entities=entities))


def weight():
    return json.loads((ROOT / "contracts/examples/valid/weight.json").read_text())


def source(store, context, *, action="create", entity_id=None, payload=None):
    entity_id = entity_id or uid()
    return store.import_source(
        context.scope, "weight", entity_id, action, json.dumps(payload or weight())
    ), entity_id


def ack(context, operation, *, status="accepted", revision=1, mapping=None):
    return {
        "sync_epoch": context.sync_epoch,
        "server_time": TIME,
        "results": [
            {
                "operation_id": operation["operation_id"],
                "entity_id": operation["entity_id"],
                "status": status,
                "revision": revision,
                "recovery_mapping": mapping,
            }
        ],
    }


@pytest.fixture
def ready(tmp_path):
    store = SyncStore(tmp_path / "device.sqlite")
    scope = store.register(issuer="https://id.example/realm", subject="A")
    store.select(scope)
    context = boot(store, scope)
    snapshot(store, context)
    yield store, context
    store.close()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.234567000000", "1.234567"),
        ("0.000001000000", "0.000001"),
        ("-0.0", "0"),
        (80.0, "80"),
        ("0", "0"),
    ],
)
def test_lossless_decimal(value, expected):
    assert exact_decimal(value) == expected


@pytest.mark.parametrize(
    "value",
    ["1.234567000001", "0.000000000001", float("nan"), float("inf"), "-1", True, "NaN", "1000000"],
)
def test_precision_loss_and_underflow_require_review(value):
    with pytest.raises(AdaptationRequired):
        exact_decimal(value)


def test_immutable_wire_originals_and_restart_after_send(ready):
    store, context = ready
    draft, _ = source(store, context)
    operation = store.materialize(context, draft)
    assert operation["operation_id"] == draft
    request = store.prepare_push(context)
    original = store.db.execute("SELECT source_json FROM originals").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="immutable_wire"):
        store.db.execute("UPDATE wire_ops SET wire_json='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable_original"):
        store.db.execute("UPDATE originals SET source_json='{}'")
    reopened = SyncStore(store.path)
    try:
        assert reopened.prepare_push(context) == request
        assert reopened.materialize(context, draft) == operation
        assert reopened.db.execute("SELECT source_json FROM originals").fetchone()[0] == original
    finally:
        reopened.close()


def test_later_edit_waits_for_ack_and_uses_server_revision(ready):
    store, context = ready
    first, entity = source(store, context)
    op = store.materialize(context, first)
    second, _ = source(
        store, context, action="update", entity_id=entity, payload=weight() | {"weight_kg": "81"}
    )
    with pytest.raises(ClientError, match="predecessor_unresolved"):
        store.materialize(context, second)
    request = store.prepare_push(context)
    store.apply_push(context, request, ack(context, op, revision=7))
    next_op = store.materialize(context, second)
    assert next_op["operation_id"] != op["operation_id"] and next_op["base_revision"] == 7
    assert (
        json.loads(
            store.db.execute(
                "SELECT wire_json FROM wire_ops WHERE operation_id=?", (op["operation_id"],)
            ).fetchone()[0]
        )
        == op
    )


def test_invalid_ack_has_no_partial_ack(ready):
    store, context = ready
    ops = [store.materialize(context, source(store, context)[0]) for _ in range(2)]
    request = store.prepare_push(context)
    response = ack(context, ops[0])
    response["results"].append(ack(context, ops[1])["results"][0] | {"entity_id": uid()})
    with pytest.raises(ClientError, match="ack_order_mismatch"):
        store.apply_push(context, request, response)
    assert [row[0] for row in store.db.execute("SELECT state FROM wire_ops")] == ["sent", "sent"]


def test_shadow_staging_restart_and_atomic_final_page(ready):
    store, context = ready
    draft, entity = source(store, context)
    original = store.db.execute(
        "SELECT source_json FROM originals WHERE id=?", (draft,)
    ).fetchone()[0]
    session = store.start_pull(context, full=True, limit=1)
    first = store.prepare_pull(context, session)
    entry = {
        "entity_type": "weight",
        "entity_id": entity,
        "revision": 3,
        "deleted": False,
        "payload": weight() | {"weight_kg": "90"},
    }
    assert not store.apply_pull(
        context, session, first, page(context, entities=[entry], token="next")
    )
    assert store.db.execute("SELECT count(*) FROM shadow").fetchone()[0] == 0
    with SyncStore(store.path) as reopened:
        next_request = reopened.prepare_pull(context, session)
        assert next_request == {
            "sync_epoch": context.sync_epoch,
            "limit": 1,
            "snapshot_token": "snapshot",
            "page_token": "next",
        }
        assert reopened.apply_pull(context, session, next_request, page(context))
        assert reopened.db.execute("SELECT count(*) FROM shadow").fetchone()[0] == 1
        assert (
            reopened.db.execute(
                "SELECT source_json FROM originals WHERE id=?", (draft,)
            ).fetchone()[0]
            == original
        )
        assert reopened.apply_pull(context, session, next_request, page(context))


def test_account_a_b_a_discards_late_response(ready):
    store, context = ready
    draft, _ = source(store, context)
    op = store.materialize(context, draft)
    request = store.prepare_push(context)
    other = store.register(issuer="https://id.example/realm", subject="B")
    store.select(other)
    boot(store, other)
    store.select(context.scope)
    assert store.capture().lease_generation > context.lease_generation
    with pytest.raises(ClientError, match="stale_context"):
        store.apply_push(context, request, ack(context, op))
    assert store.db.execute("SELECT state FROM wire_ops").fetchone()[0] == "sent"


def test_guest_binding_is_durable_single_account_no_age_limit(ready):
    store, context = ready
    guest = store.register()
    draft = store.import_source(guest, "weight", uid(), "create", json.dumps(weight()))
    with pytest.raises(ClientError, match="explicit_confirmation"):
        store.bind_guest(guest, context, confirmed=False)
    store.bind_guest(guest, context, confirmed=True)
    assert store.materialize(context, draft)["sync_epoch"] == context.sync_epoch
    other = store.register(issuer="https://id.example/realm", subject="B")
    store.select(other)
    b_context = boot(store, other)
    with SyncStore(store.path) as reopened, pytest.raises(ClientError, match="guest_already_bound"):
        reopened.bind_guest(guest, b_context, confirmed=True)


@pytest.mark.parametrize("change", ["epoch", "generation"])
def test_requires_recovery_survives_bootstrap_and_full_snapshot(ready, change):
    store, old = ready
    draft, _ = source(store, old)
    operation = store.materialize(old, draft)
    store.prepare_push(old)
    context = boot(
        store, old.scope, epoch=uid() if change == "epoch" else old.sync_epoch, generation=2
    )
    same = boot(store, old.scope, epoch=context.sync_epoch, generation=2)
    assert asdict(same) == asdict(context)
    with pytest.raises(ClientError, match="recovery_required"):
        store.prepare_push(context)
    snapshot(store, context)
    with pytest.raises(ClientError, match="recovery_required"):
        store.prepare_push(context)
    if change == "epoch":
        with pytest.raises(ClientError, match="old_outbox"):
            store.finish_reconciliation(context, confirmed=True)
        store.retire_old_operation(context, operation["operation_id"], confirmed=True)
    store.finish_reconciliation(context, confirmed=True)
    if change == "generation":
        assert store.prepare_push(context)["operations"] == [operation]


def test_epoch_recovery_requires_new_uuid_and_explicit_decision(ready):
    store, old = ready
    draft, entity = source(store, old)
    old_op = store.materialize(old, draft)
    request = store.prepare_push(old)
    store.apply_push(old, request, ack(old, old_op))
    context = boot(store, old.scope, epoch=uid())
    snapshot(store, context)
    recovery = {
        "source_epoch": old.sync_epoch,
        "source_entity_id": entity,
        "source_revision": 1,
        "source_operation_id": old_op["operation_id"],
        "decision": "recreate_missing",
    }
    with pytest.raises(ClientError, match="new_uuid"):
        store.materialize(context, draft, recovery=recovery, confirmed=True)
    with pytest.raises(ClientError, match="explicit_epoch"):
        store.materialize(context, draft, recovery=recovery, target_id=uid())
    op = store.materialize(context, draft, recovery=recovery, target_id=uid(), confirmed=True)
    assert op["operation_id"] != old_op["operation_id"] and op["base_revision"] is None
    assert store.prepare_push(context, recovery_only=True)["operations"] == [op]


def test_legacy_goal_is_preserved_and_not_invented(ready):
    store, context = ready
    raw = (
        '{"id":"legacy-goal","valid_from":"2020-01-01","kcal":2000,'
        '"protein":null,"fat":null,"carbs":null}'
    )
    draft = store.import_source(context.scope, "goal", uid(), "create", raw)
    with pytest.raises(AdaptationRequired, match="legacy_goal_metadata"):
        store.materialize(context, draft)
    assert (
        store.db.execute("SELECT source_json FROM originals WHERE id=?", (draft,)).fetchone()[0]
        == raw
    )
    assert store.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == 0


def test_real_transport_lost_response_retains_sent_and_exact_retry(ready):
    store, context = ready
    draft, _ = source(store, context)
    op = store.materialize(context, draft)
    received = []

    def server(request):
        received.append(request.content)
        return httpx.Response(
            200,
            json=ack(context, op, status="accepted" if len(received) == 1 else "already_applied"),
        )

    http = SyncHTTP(
        "http://127.0.0.1:9876",
        token_supplier=lambda _: "synthetic",
        http=httpx.Client(transport=httpx.MockTransport(server)),
    )

    def lose(_):
        raise ConnectionError("Lost after server commit, before local apply")

    with pytest.raises(ConnectionError):
        http.push(store, context, after_response=lose)
    with SyncStore(store.path) as reopened:
        http.push(reopened, context)
    assert received[0] == received[1]
    assert store.db.execute("SELECT state FROM wire_ops").fetchone()[0] == "already_applied"
    http.close()


@pytest.mark.parametrize(
    "code",
    [
        "sync_epoch_changed",
        "sync_cursor_expired",
        "account_deleting",
        "identity_provider_unavailable",
    ],
)
def test_non200_no_ack_and_deleting_never_recovery(ready, code):
    store, context = ready
    store.materialize(context, source(store, context)[0])
    http = SyncHTTP(
        "http://localhost:9876",
        token_supplier=lambda _: "synthetic",
        http=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(409, json={"code": code}))
        ),
    )
    with pytest.raises(ClientError, match=code):
        http.push(store, context)
    assert store.db.execute("SELECT state FROM wire_ops").fetchone()[0] == "sent"
    if code == "account_deleting":
        with pytest.raises(ClientError, match=code):
            store.start_pull(context, full=True)
    http.close()


def test_same_epoch_snapshot_absence_preserves_original_and_records_deletion(ready):
    store, context = ready
    draft, entity = source(store, context)
    snapshot(
        store,
        context,
        [
            {
                "entity_type": "weight",
                "entity_id": entity,
                "revision": 1,
                "deleted": False,
                "payload": weight(),
            }
        ],
    )
    snapshot(store, context)
    assert store.db.execute("SELECT reason FROM conflicts").fetchone()[0] == "absent_same_epoch"
    assert (
        store.db.execute("SELECT count(*) FROM originals WHERE id=?", (draft,)).fetchone()[0] == 1
    )


def test_equal_revision_different_epoch_keeps_ack_shadow_and_original(ready):
    store, old = ready
    _, entity = source(store, old)
    snapshot(
        store,
        old,
        [
            {
                "entity_type": "weight",
                "entity_id": entity,
                "revision": 1,
                "deleted": False,
                "payload": weight(),
            }
        ],
    )
    new = boot(store, old.scope, epoch=uid())
    snapshot(
        store,
        new,
        [
            {
                "entity_type": "weight",
                "entity_id": entity,
                "revision": 1,
                "deleted": False,
                "payload": weight() | {"weight_kg": "99"},
            }
        ],
    )
    assert store.db.execute("SELECT count(*) FROM shadow").fetchone()[0] == 2
    assert store.db.execute("SELECT count(*) FROM shadow_history").fetchone()[0] == 1
    assert store.db.execute("SELECT count(*) FROM originals").fetchone()[0] == 1


def test_precision_review_no_wire_or_changes_to_original(ready):
    store, context = ready
    draft, _ = source(store, context, payload=weight() | {"weight_kg": "80.000000000001"})
    with pytest.raises(AdaptationRequired, match="precision_review"):
        store.materialize(context, draft)
    store.mark_review(draft, "precision_review")
    assert (
        store.db.execute("SELECT review FROM drafts WHERE id=?", (draft,)).fetchone()[0]
        == "precision_review"
    )
    assert store.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == 0


@pytest.mark.parametrize(
    "kind,filename", [("profile", "profile.json"), ("diary_day", "diary-day.json")]
)
def test_existing_natural_key_requires_review_without_second_entity(ready, kind, filename):
    store, context = ready
    payload = json.loads((ROOT / "contracts/examples/valid" / filename).read_text())
    canonical, local = uid(), uid()
    snapshot(
        store,
        context,
        [
            {
                "entity_type": kind,
                "entity_id": canonical,
                "revision": 4,
                "deleted": False,
                "payload": payload,
            }
        ],
    )
    draft = store.import_source(context.scope, kind, local, "create", json.dumps(payload))
    with pytest.raises(ClientError, match="natural_key_review"):
        store.materialize(context, draft)
    op = store.materialize(context, draft, target_id=canonical, confirmed=True)
    assert op["entity_id"] == canonical and op["base_revision"] == 4
    assert (
        store.db.execute("SELECT entity_id FROM originals WHERE id=?", (draft,)).fetchone()[0]
        == local
    )


def test_recovery_mapping_adopts_real_target_and_rewrites_only_new_references(ready):
    store, context = ready
    draft, _ = source(store, context)
    op = store.materialize(context, draft)
    request = store.prepare_push(context)
    old_epoch, old_entity, target = uid(), uid(), uid()
    mapping = {
        "source_epoch": old_epoch,
        "source_entity_id": old_entity,
        "target_entity_id": target,
        "target_revision": 7,
    }
    store.apply_push(
        context, request, ack(context, op, status="already_applied", revision=7, mapping=mapping)
    )
    original = {"goal_id": old_entity, "correction_of": None}
    assert store.remap_new_references(context, original, old_epoch)["goal_id"] == target
    assert original["goal_id"] == old_entity
    assert json.loads(store.db.execute("SELECT wire_json FROM wire_ops").fetchone()[0]) == op
    with pytest.raises(ClientError, match="mapping_target_changed"), store.transaction() as db:
        store._mapping(db, context.scope, mapping | {"target_entity_id": uid()})


def test_failed_second_page_keeps_staging_cursor_and_previous_shadow(ready):
    store, context = ready
    session = store.start_pull(context, full=True, limit=1)
    request = store.prepare_pull(context, session)
    first = page(context, token="next")
    store.apply_pull(context, session, request, first)
    continuation = store.prepare_pull(context, session)
    with pytest.raises(ClientError, match="snapshot_metadata_changed"):
        store.apply_pull(
            context, session, continuation, page(context) | {"goal_timeline_revision": 1}
        )
    assert store.prepare_pull(context, session) == continuation
    assert (
        store.db.execute("SELECT count(*) FROM pages WHERE session_id=?", (session,)).fetchone()[0]
        == 1
    )


def test_reconciliation_cannot_finish_with_unaccepted_recovery(ready):
    store, old = ready
    draft, entity = source(store, old)
    context = boot(store, old.scope, epoch=uid())
    snapshot(store, context)
    recovery = {
        "source_epoch": old.sync_epoch,
        "source_entity_id": entity,
        "source_revision": None,
        "source_operation_id": None,
        "decision": "recreate_missing",
    }
    store.materialize(context, draft, recovery=recovery, target_id=uid(), confirmed=True)
    with pytest.raises(ClientError, match="recovery_operations_unresolved"):
        store.finish_reconciliation(context, confirmed=True)


@pytest.mark.parametrize(
    "kind,filename",
    [
        ("profile", "profile.json"),
        ("goal", "goal.json"),
        ("meal", "meal.json"),
        ("weight", "weight.json"),
        ("diary_day", "diary-day.json"),
        ("product_draft", "product-draft.json"),
    ],
)
def test_all_six_full_payloads_materialize_without_changing_original(ready, kind, filename):
    store, context = ready
    payload = json.loads((ROOT / "contracts/examples/valid" / filename).read_text())
    if kind == "goal":
        payload["timeline_base_revision"] = 0
    elif kind == "meal":
        payload["goal_id"] = None
    raw = json.dumps(payload, indent=3, ensure_ascii=False)
    draft = store.import_source(context.scope, kind, uid(), "create", raw)
    op = store.materialize(context, draft)
    assert op["payload"] == payload and op["base_revision"] is None
    assert (
        store.db.execute("SELECT source_json FROM originals WHERE id=?", (draft,)).fetchone()[0]
        == raw
    )


def test_guest_and_account_sources_never_leak_between_scopes(ready):
    store, a = ready
    draft, _ = source(store, a)
    b_scope = store.register(issuer="https://id.example/realm", subject="B")
    store.select(b_scope)
    b = boot(store, b_scope)
    snapshot(store, b)
    with pytest.raises(ClientError, match="foreign_source"):
        store.materialize(b, draft)
    assert store.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == 0
