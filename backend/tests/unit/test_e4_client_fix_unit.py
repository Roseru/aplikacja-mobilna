"""Byte-exact batching and narrow, context-bound Goal recovery checks."""

import copy
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.sync_client import ClientError, SyncHTTP, SyncStore  # noqa: E402
from tools.sync_client.wire import digest, dumps, encode_json, loads  # noqa: E402

TIME = "2026-10-10T12:00:00Z"


def uid():
    return str(uuid4())


def load_example(kind):
    return loads((ROOT / f"contracts/examples/valid/{kind}.json").read_text(encoding="utf-8"))


def finish_snapshot(store, context, *, timeline=0, entities=None, mappings=None, receipts=None):
    session = store.start_pull(context, full=True)
    store.apply_pull(
        context,
        session,
        store.prepare_pull(context, session),
        {
            "sync_epoch": context.sync_epoch,
            "mode": "snapshot",
            "snapshot_token": "synthetic-snapshot",
            "page_token": None,
            "checkpoint": "synthetic-checkpoint",
            "server_time": TIME,
            "entities": entities or [],
            "goal_timeline_revision": timeline,
            "recovery_mappings": mappings or [],
            "operation_receipts": receipts or [],
        },
    )


@pytest.fixture
def client(tmp_path):
    with SyncStore(tmp_path / "bytes.sqlite") as store:
        scope = store.register(issuer="https://id.example.test/realm", subject="synthetic-a")
        store.select(scope)
        store.bootstrap(
            scope,
            {
                "account_id": uid(),
                "account_generation": 1,
                "sync_epoch": uid(),
                "server_time": TIME,
            },
            lease_generation=1,
        )
        context = store.capture()
        finish_snapshot(store, context)
        yield store, context


def meal_bytes(size):
    payload = load_example("meal")
    template = payload["items"][0]
    payload["items"] = [
        copy.deepcopy(template)
        | {
            "item_id": uid(),
            "name": "🥣" * 200,
            "density_g_per_ml": "1",
            "density_source": "x",
        }
        for _ in range(100)
    ]
    missing = size - len(encode_json(payload))
    assert 0 <= missing <= 100 * 499
    for index, item in enumerate(payload["items"]):
        item["density_source"] += "x" * (missing // 100 + int(index < missing % 100))
    assert len(encode_json(payload)) == size
    return payload


def envelope(context, operations, checkpoint):
    return {
        "protocol_version": 1,
        "sync_epoch": context.sync_epoch,
        "checkpoint": checkpoint,
        "operations": operations,
    }


def queue(store, context, kind, payload, *, entity=None):
    source = store.import_source(context.scope, kind, entity or uid(), "create", dumps(payload))
    return store.materialize(context, source)


@pytest.mark.parametrize(
    "checkpoint", ["c", "ż" * 2048, "🥣" * 4096], ids=["short", "polish-2048", "emoji-4096"]
)
@pytest.mark.parametrize("extra", [0, 1])
def test_real_utf8_envelope_boundary_and_checkpoint_length(client, checkpoint, extra):
    store, context = client
    store.db.execute("UPDATE bindings SET checkpoint=?", (checkpoint,))
    operations = [queue(store, context, "meal", meal_bytes(149000)) for _ in range(6)]
    seventh = {
        "operation_id": uid(),
        "entity_type": "meal",
        "entity_id": uid(),
        "action": "upsert",
        "base_revision": None,
        "sync_epoch": context.sync_epoch,
        "payload": meal_bytes(145893),
    }
    size = (
        145893 + 1048576 - len(encode_json(envelope(context, [*operations, seventh], checkpoint)))
    )
    seventh["payload"] = meal_bytes(size + extra)
    draft = store.import_source(
        context.scope,
        "meal",
        seventh["entity_id"],
        "create",
        dumps(seventh["payload"]),
        source_id=seventh["operation_id"],
    )
    assert store.materialize(context, draft) == seventh
    operations.append(seventh)
    operations.append(queue(store, context, "weight", load_example("weight")))
    original_wire = [
        tuple(row)
        for row in store.db.execute(
            "SELECT operation_id,wire_json,wire_hash FROM wire_ops ORDER BY rowid"
        )
    ]
    observed = []

    def response(request):
        observed.append(request.content)
        body = loads(request.content)
        return httpx.Response(
            200,
            json={
                "sync_epoch": context.sync_epoch,
                "server_time": TIME,
                "results": [
                    {
                        "operation_id": op["operation_id"],
                        "entity_id": op["entity_id"],
                        "status": "accepted",
                        "revision": 1,
                        "recovery_mapping": None,
                    }
                    for op in body["operations"]
                ],
            },
        )

    transport = SyncHTTP(
        "http://127.0.0.1:1",
        token_supplier=lambda _: "synthetic",
        http=httpx.Client(transport=httpx.MockTransport(response)),
    )
    try:
        transport.push(store, context)
        selected = loads(observed[0])["operations"]
        assert selected == operations[: 7 if extra == 0 else 6]
        assert len(observed[0]) == (
            1048576
            if extra == 0
            else len(encode_json(envelope(context, operations[:6], checkpoint)))
        )
        assert observed[0] == encode_json(envelope(context, selected, checkpoint))
        assert store.db.execute("SELECT count(*) FROM wire_ops WHERE state='queued'").fetchone()[
            0
        ] == (1 if extra == 0 else 2)
        transport.push(store, context)
        assert all(len(raw) <= 1048576 for raw in observed)
        assert [op for raw in observed for op in loads(raw)["operations"]] == operations
        assert [
            tuple(row)
            for row in store.db.execute(
                "SELECT operation_id,wire_json,wire_hash FROM wire_ops ORDER BY rowid"
            )
        ] == original_wire
    finally:
        transport.close()


def test_count_limit_100_is_independent_of_bytes(client):
    store, context = client
    operations = [queue(store, context, "weight", load_example("weight")) for _ in range(101)]
    body = store.prepare_push(context)
    assert body["operations"] == operations[:100]
    assert len(encode_json(body)) < 1048576
    assert (
        store.db.execute("SELECT state FROM wire_ops ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        == "queued"
    )


def test_second_change_to_entity_ends_batch_without_reordering_later_operations(client):
    store, context = client
    first = queue(store, context, "weight", load_example("weight"))
    store.apply_push(
        context,
        store.prepare_push(context),
        {
            "sync_epoch": context.sync_epoch,
            "server_time": TIME,
            "results": [
                {
                    "operation_id": first["operation_id"],
                    "entity_id": first["entity_id"],
                    "status": "accepted",
                    "revision": 1,
                    "recovery_mapping": None,
                }
            ],
        },
    )
    second = queue(
        store,
        context,
        "weight",
        load_example("weight") | {"weight_kg": "81"},
        entity=first["entity_id"],
    )
    # Older imported queue state can contain the predecessor still awaiting replay.
    store.db.execute(
        "UPDATE wire_ops SET state='queued' WHERE operation_id=?", (first["operation_id"],)
    )
    third = queue(store, context, "weight", load_example("weight"))
    request = store.prepare_push(context)
    assert request["operations"] == [first]
    assert [row[0] for row in store.db.execute("SELECT state FROM wire_ops ORDER BY rowid")] == [
        "sent",
        "queued",
        "queued",
    ]
    store.db.execute(
        "UPDATE wire_ops SET state='accepted' WHERE operation_id=?", (first["operation_id"],)
    )
    assert store.prepare_push(context)["operations"] == [second, third]


def test_one_oversized_preserved_operation_is_explicit_and_never_marked_sent(client):
    store, context = client
    raw = dumps({"title": "🥣" * 300000})
    source = store.import_source(context.scope, "meal", uid(), "create", raw)
    # An imported older/adversarial queue may contain unvalidated oversized wire.
    # Current materialization rejects such payloads; preparation still fails safely.
    operation = {
        "operation_id": uid(),
        "entity_type": "meal",
        "entity_id": uid(),
        "action": "upsert",
        "base_revision": None,
        "sync_epoch": context.sync_epoch,
        "payload": loads(raw),
    }
    store.db.execute(
        "INSERT INTO wire_ops VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            operation["operation_id"],
            source,
            context.scope,
            "meal",
            operation["entity_id"],
            context.sync_epoch,
            dumps(operation),
            digest(operation),
            1,
            "queued",
            None,
        ),
    )
    before = [tuple(row) for row in store.db.execute("SELECT * FROM wire_ops")]
    originals = [tuple(row) for row in store.db.execute("SELECT * FROM originals")]
    for _ in range(2):
        with pytest.raises(ClientError, match="^operation_too_large$"):
            store.prepare_push(context)
    assert [tuple(row) for row in store.db.execute("SELECT * FROM wire_ops")] == before
    assert [tuple(row) for row in store.db.execute("SELECT * FROM originals")] == originals


def goal_mapping(store, context, *, target_type="goal", deleted=False, revision=1):
    source_entity, target = uid(), uid()
    recovery = {
        "source_epoch": uid(),
        "source_entity_id": source_entity,
        "source_revision": 1,
        "source_operation_id": None,
        "decision": "recreate_missing",
    }
    payload = load_example("goal")
    mapping = {
        "source_epoch": recovery["source_epoch"],
        "source_entity_id": source_entity,
        "target_entity_id": target,
        "target_revision": revision,
    }
    entity = {
        "entity_type": target_type,
        "entity_id": target,
        "revision": revision,
        "deleted": deleted,
        "payload": None if deleted else load_example(target_type),
    }
    finish_snapshot(store, context, timeline=1, entities=[entity], mappings=[mapping])
    source = store.import_source(context.scope, "goal", source_entity, "create", dumps(payload))
    return source, recovery, payload, mapping


@pytest.mark.parametrize(
    "change,error",
    [
        ("energy", "recovery_content_conflict"),
        ("reason", "recovery_content_conflict"),
        ("source_epoch", "timeline_review_required"),
        ("source_id", "recovery_source_mismatch"),
        ("target_type", "recovery_target_conflict"),
        ("target_deleted", "recovery_target_conflict"),
        ("target_revision", "recovery_target_conflict"),
        ("context", "recovery_mapping_context_required"),
        ("owner", "foreign_source"),
        ("unconfirmed", "explicit_epoch_recovery_required"),
        ("no_mapping", "timeline_review_required"),
        ("not_recovery", "timeline_review_required"),
    ],
)
def test_goal_axis_exception_requires_exact_confirmed_source_context_target(client, change, error):
    store, context = client
    source, recovery, payload, mapping = goal_mapping(
        store,
        context,
        target_type="weight" if change == "target_type" else "goal",
        deleted=change == "target_deleted",
    )
    options = {"recovery": recovery, "target_id": uid(), "confirmed": True}
    if change == "energy":
        options["reviewed_payload"] = payload | {"energy_kcal": "2501"}
    elif change == "reason":
        # An unrelated text field is also part of full recovery equality.
        options["reviewed_payload"] = payload | {"activity_class": "commando"}
    elif change == "source_epoch":
        recovery["source_epoch"] = uid()
    elif change == "source_id":
        recovery["source_entity_id"] = uid()
    elif change == "target_revision":
        store.db.execute(
            "UPDATE mappings SET mapping_json=?", (dumps(mapping | {"target_revision": 2}),)
        )
    elif change == "context":
        store.db.execute(
            "UPDATE mapping_contexts SET context_json=?",
            (dumps(asdict(context) | {"context_revision": 99}),),
        )
    elif change == "owner":
        guest = store.register()
        source = store.import_source(
            guest, "goal", recovery["source_entity_id"], "create", dumps(payload)
        )
    elif change == "unconfirmed":
        options["confirmed"] = False
    elif change == "no_mapping":
        store.db.execute("DELETE FROM mapping_contexts")
        store.db.execute("DELETE FROM mappings")
    elif change == "not_recovery":
        options.pop("recovery")
    before = store.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0]
    with pytest.raises(ClientError, match=f"^{error}$"):
        store.materialize(context, source, **options)
    assert store.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == before


def test_known_original_wire_and_receipt_must_match_recovery_source(client):
    store, context = client
    source, recovery, _, _ = goal_mapping(store, context)
    old_operation = queue(store, context, "weight", load_example("weight"))
    with pytest.raises(ClientError, match="recovery_source_mismatch"):
        store.materialize(
            context,
            source,
            recovery=recovery
            | {
                "source_operation_id": old_operation["operation_id"],
            },
            target_id=uid(),
            confirmed=True,
        )
    operation_id = uid()
    receipt = {
        "operation_id": operation_id,
        "source_epoch": recovery["source_epoch"],
        "entity_id": recovery["source_entity_id"],
        "status": "accepted",
        "revision": 1,
        "code": None,
    }
    store.db.execute(
        "INSERT INTO receipts VALUES(?,?,?)", (context.scope, operation_id, dumps(receipt))
    )
    operation = store.materialize(
        context,
        source,
        recovery=recovery
        | {
            "source_operation_id": operation_id,
        },
        target_id=uid(),
        confirmed=True,
    )
    assert operation["payload"]["timeline_base_revision"] == 0
    with pytest.raises(ClientError, match="recovery_source_mismatch"):
        store.materialize(
            context,
            source,
            recovery=recovery
            | {
                "source_operation_id": operation_id,
                "source_revision": 2,
            },
            target_id=uid(),
            confirmed=True,
        )


def test_upgrade_keeps_old_mapping_but_requires_current_confirmation(client):
    store, context = client
    source, recovery, payload, mapping = goal_mapping(store, context)
    store.db.execute("DROP TABLE mapping_contexts")
    with SyncStore(store.path) as reopened:
        assert reopened.db.execute("SELECT mapping_json FROM mappings").fetchone()[0] == dumps(
            mapping
        )
        with pytest.raises(ClientError, match="recovery_mapping_context_required"):
            reopened.materialize(
                context, source, recovery=recovery, target_id=uid(), confirmed=True
            )
        entity = {
            "entity_type": "goal",
            "entity_id": mapping["target_entity_id"],
            "revision": 1,
            "deleted": False,
            "payload": payload,
        }
        finish_snapshot(reopened, context, timeline=1, entities=[entity], mappings=[mapping])
        operation = reopened.materialize(
            context, source, recovery=recovery, target_id=uid(), confirmed=True
        )
        assert operation["payload"] == payload


def test_goal_recovery_delete_does_not_use_mapping_to_avoid_axis_or_immutability(client):
    store, context = client
    _, recovery, _, mapping = goal_mapping(store, context)
    source = store.import_source(
        context.scope, "goal", recovery["source_entity_id"], "delete", "null"
    )
    with pytest.raises(ClientError, match="^recovery_upsert_required$"):
        store.materialize(
            context,
            source,
            recovery=recovery | {"decision": "resolve_existing"},
            target_id=mapping["target_entity_id"],
            confirmed=True,
        )
    assert store.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == 0
