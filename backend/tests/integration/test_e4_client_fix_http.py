"""Regression evidence from durable SQLite clients and real loopback HTTP/PG17."""

import copy
import os
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from test_e4_client_http import ROOT, device

from calorie_app.modules.sync import transport as server_transport
from tools.sync_client import ClientError, SyncStore
from tools.sync_client.wire import digest, dumps, loads

pytestmark = pytest.mark.integration
pytest_plugins = ["test_e4_client_http"]


def large_meal():
    """Exactly the review's 145893 UTF-8 bytes, 100 independently named items."""
    payload = loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
    template = payload["items"][0]
    payload["items"] = [
        copy.deepcopy(template)
        | {
            "item_id": str(uuid4()),
            "name": "🥣" * 200,
            "density_g_per_ml": "1",
            "density_source": "x",
        }
        for _ in range(100)
    ]
    missing = 145893 - len(dumps(payload).encode("utf-8"))
    assert 0 <= missing < 100 * 499
    for index, item in enumerate(payload["items"]):
        item["density_source"] += "x" * (missing // 100 + int(index < missing % 100))
    assert len(dumps(payload).encode("utf-8")) == 145893
    return payload


def source_operation(store, context, kind, payload, *, entity=None):
    source_id = store.import_source(
        context.scope, kind, entity or str(uuid4()), "create", dumps(payload)
    )
    return store.materialize(context, source_id)


def wire_evidence(store):
    return [
        tuple(row)
        for row in store.db.execute(
            "SELECT operation_id,wire_json,wire_hash,epoch,draft_id FROM wire_ops ORDER BY rowid"
        )
    ]


def test_large_queue_default_http_retry_restart_then_cli(live_api, tmp_path, monkeypatch):
    api, who, engine = live_api
    path = tmp_path / "large-queue.sqlite"
    store, context, transport = device(path, api, who)
    bodies = []
    parse = server_transport.parse_push

    def observed_parse(raw):
        bodies.append(raw)
        return parse(raw)

    monkeypatch.setattr(server_transport, "parse_push", observed_parse)
    try:
        operations = [source_operation(store, context, "meal", large_meal()) for _ in range(8)]
        immutable = wire_evidence(store)
        originals = [
            tuple(row) for row in store.db.execute("SELECT * FROM originals ORDER BY rowid")
        ]

        def lost(_):
            raise ConnectionError("lost response after server commit")

        with pytest.raises(ConnectionError):
            transport.push(store, context, after_response=lost)
        selected = loads(bodies[0])["operations"]
        assert 1 <= len(selected) < 8
        states = [row[0] for row in store.db.execute("SELECT state FROM wire_ops ORDER BY rowid")]
        assert states == ["sent"] * len(selected) + ["queued"] * (8 - len(selected))
        store.close()
        store = SyncStore(path)
        replay = transport.push(store, context)
        assert all(result["status"] == "already_applied" for result in replay["results"])
        assert bodies[0] == bodies[1]
        store.close()
        # The default operator command must make progress on the remaining queue.
        env = os.environ.copy()
        env["SYNC_ACCESS_TOKEN"] = "synthetic-a"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.sync_client",
                "--database",
                str(path),
                "push",
                "--api",
                api,
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        store = SyncStore(path)
        assert not store.db.execute(
            "SELECT 1 FROM wire_ops WHERE state IN ('queued','sent')"
        ).fetchone()
        assert [loads(raw)["operations"] for raw in bodies[:2]] == [selected, selected]
        for body in bodies:
            assert len(body) <= 1048576
            assert 1 <= len(loads(body)["operations"]) <= 100
        assert [
            operation["operation_id"]
            for body in (bodies[0], *bodies[2:])
            for operation in loads(body)["operations"]
        ] == [operation["operation_id"] for operation in operations]
        assert [op["operation_id"] for op in selected] == [
            op["operation_id"] for op in operations[: len(selected)]
        ]
        assert wire_evidence(store) == immutable
        assert [
            tuple(row) for row in store.db.execute("SELECT * FROM originals ORDER BY rowid")
        ] == originals
        assert all(digest(loads(row[1])) == row[2] for row in immutable)
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.meals WHERE owner_id=:o"),
                    {"o": context.account_id},
                )
                == 8
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.sync_receipts WHERE owner_id=:o"),
                    {"o": context.account_id},
                )
                == 8
            )
    finally:
        store.close()
        transport.close()


def test_goal_second_device_identical_recovery_after_snapshot_and_restart(live_api, tmp_path):
    api, who, engine = live_api
    a, ac, ah = device(tmp_path / "goal-a.sqlite", api, who)
    b, bc, bh = device(tmp_path / "goal-b.sqlite", api, who)
    payload = loads((ROOT / "contracts/examples/valid/goal.json").read_text(encoding="utf-8"))
    source_entity = str(uuid4())
    recovery = {
        "source_epoch": str(uuid4()),
        "source_entity_id": source_entity,
        "source_revision": 1,
        "source_operation_id": None,
        "decision": "recreate_missing",
    }
    try:
        drafts = [
            store.import_source(context.scope, "goal", source_entity, "create", dumps(payload))
            for store, context in ((a, ac), (b, bc))
        ]
        first = a.materialize(
            ac, drafts[0], recovery=recovery, target_id=str(uuid4()), confirmed=True
        )
        reply = ah.push(a, ac, recovery_only=True)["results"][0]
        assert reply["status"] == "accepted"
        mapping = reply["recovery_mapping"]
        bh.pull(b, bc, full=True)
        assert b.db.execute("SELECT timeline FROM bindings").fetchone()[0] == 1
        assert b.db.execute("SELECT count(*) FROM mappings").fetchone()[0] == 1
        b.close()
        b = SyncStore(tmp_path / "goal-b.sqlite")
        # Independent server replay proves that the client may keep the full original payload.
        direct = first | {"operation_id": str(uuid4()), "entity_id": str(uuid4())}
        body = {
            "protocol_version": 1,
            "sync_epoch": bc.sync_epoch,
            "checkpoint": b.db.execute("SELECT checkpoint FROM bindings").fetchone()[0],
            "operations": [direct],
        }
        with httpx.Client() as http:
            response = http.post(
                api + "/api/v1/sync/push",
                content=dumps(body).encode("utf-8"),
                headers={"Authorization": "Bearer synthetic-a", "Content-Type": "application/json"},
            )
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["status"] == "already_applied"
        second = b.materialize(
            bc, drafts[1], recovery=recovery, target_id=str(uuid4()), confirmed=True
        )
        assert second["payload"] == first["payload"] == payload
        assert second["payload"]["timeline_base_revision"] == 0
        immutable = wire_evidence(b)
        original_b = [tuple(row) for row in b.db.execute("SELECT * FROM originals")]

        def lost(_):
            raise ConnectionError("lost Goal recovery response after commit")

        with pytest.raises(ConnectionError):
            bh.push(b, bc, recovery_only=True, after_response=lost)
        b.close()
        b = SyncStore(tmp_path / "goal-b.sqlite")
        result = bh.push(b, bc, recovery_only=True)["results"][0]
        assert result["status"] == "already_applied"
        assert result["recovery_mapping"] == mapping
        assert result["entity_id"] == second["entity_id"]
        assert (
            b.remap_new_references(bc, {"goal_id": source_entity}, recovery["source_epoch"])[
                "goal_id"
            ]
            == first["entity_id"]
        )
        assert wire_evidence(b) == immutable
        assert [tuple(row) for row in b.db.execute("SELECT * FROM originals")] == original_b
        meal = loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
        meal["goal_id"] = source_entity
        draft = b.import_source(bc.scope, "meal", str(uuid4()), "create", dumps(meal))
        remapped = b.remap_new_references(bc, meal, recovery["source_epoch"])
        dependent = b.materialize(bc, draft, reviewed_payload=remapped, confirmed=True)
        assert dependent["payload"]["goal_id"] == first["entity_id"]
        assert (
            loads(
                b.db.execute("SELECT source_json FROM originals WHERE id=?", (draft,)).fetchone()[0]
            )
            == meal
        )
        assert bh.push(b, bc)["results"][0]["status"] == "accepted"
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.goal_versions WHERE owner_id=:o"),
                    {"o": ac.account_id},
                )
                == 1
            )
            assert (
                connection.scalar(
                    text("SELECT revision FROM app.goal_timelines WHERE owner_id=:o"),
                    {"o": ac.account_id},
                )
                == 1
            )
    finally:
        a.close()
        b.close()
        ah.close()
        bh.close()


@pytest.mark.parametrize("problem", ["content", "type", "deleted-target"])
def test_real_snapshot_mapping_rejects_other_content_type_or_deleted_target(
    live_api, tmp_path, problem
):
    api, who, engine = live_api
    a, ac, ah = device(tmp_path / "negative-a.sqlite", api, who)
    b, bc, bh = device(tmp_path / "negative-b.sqlite", api, who)
    source = str(uuid4())
    recovery = {
        "source_epoch": str(uuid4()),
        "source_entity_id": source,
        "source_revision": 1,
        "source_operation_id": None,
        "decision": "recreate_missing",
    }
    kind = "goal" if problem == "content" else "weight"
    payload = loads((ROOT / f"contracts/examples/valid/{kind}.json").read_text(encoding="utf-8"))
    try:
        draft = a.import_source(ac.scope, kind, source, "create", dumps(payload))
        operation = a.materialize(
            ac, draft, recovery=recovery, target_id=str(uuid4()), confirmed=True
        )
        assert ah.push(a, ac, recovery_only=True)["results"][0]["status"] == "accepted"
        if problem == "deleted-target":
            deleted = a.import_source(ac.scope, kind, operation["entity_id"], "delete", "null")
            a.materialize(ac, deleted)
            assert ah.push(a, ac)["results"][0]["status"] == "accepted"
        bh.pull(b, bc, full=True)
        b.close()
        b = SyncStore(tmp_path / "negative-b.sqlite")
        candidate = loads((ROOT / "contracts/examples/valid/goal.json").read_text(encoding="utf-8"))
        if problem == "content":
            candidate["energy_kcal"] = "2501"
        draft = b.import_source(bc.scope, "goal", source, "create", dumps(candidate))
        originals = [tuple(row) for row in b.db.execute("SELECT * FROM originals")]
        with engine.connect() as connection:
            before = connection.scalar(
                text("SELECT count(*) FROM app.sync_receipts WHERE owner_id=:o"),
                {"o": ac.account_id},
            )
        error = "recovery_content_conflict" if problem == "content" else "recovery_target_conflict"
        with pytest.raises(ClientError, match=f"^{error}$"):
            b.materialize(bc, draft, recovery=recovery, target_id=str(uuid4()), confirmed=True)
        assert b.db.execute("SELECT count(*) FROM wire_ops").fetchone()[0] == 0
        assert [tuple(row) for row in b.db.execute("SELECT * FROM originals")] == originals
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.sync_receipts WHERE owner_id=:o"),
                    {"o": ac.account_id},
                )
                == before
            )
    finally:
        a.close()
        b.close()
        ah.close()
        bh.close()
