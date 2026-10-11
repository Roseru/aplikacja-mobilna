"""Malformed second operations must fail before any DML in real HTTP/PG."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import inspect
from test_e4_client_http import live_api as _live_api_fixture

live_api = _live_api_fixture
ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def payload(kind):
    name = kind.replace("_", "-")
    value = json.loads((ROOT / f"contracts/examples/valid/{name}.json").read_text(encoding="utf-8"))
    if kind == "meal":
        value["goal_id"] = value["ration"] = None
        for item in value["items"]:
            item["product"] = None
    if kind == "goal":
        value["timeline_base_revision"] = 0
    return value


def snapshot(engine):
    # Includes all private entities, receipts, counters, changes and technical
    # copies; compare stored values, not merely the response or row counts.
    with engine.connect() as connection:
        return {
            table: list(
                connection.exec_driver_sql(
                    f'SELECT to_jsonb(t)::text FROM app."{table}" t ORDER BY to_jsonb(t)::text'
                ).scalars()
            )
            for table in sorted(inspect(connection).get_table_names(schema="app"))
        }


@pytest.fixture
def wire_context(live_api):
    api, _, engine = live_api
    http = httpx.Client(base_url=api, headers={"Authorization": "Bearer synthetic-a"}, timeout=10)
    bootstrap = http.post("/api/v1/me/bootstrap", headers={"Idempotency-Key": str(uuid4())})
    assert bootstrap.status_code == 200
    page = http.get("/api/v1/sync/pull")
    assert page.status_code == 200
    yield http, engine, bootstrap.json()["sync_epoch"], page.json()["checkpoint"]
    http.close()


def op(epoch, kind, value):
    return {
        "operation_id": str(uuid4()),
        "entity_type": kind,
        "entity_id": str(uuid4()),
        "action": "upsert",
        "base_revision": None,
        "sync_epoch": epoch,
        "payload": value,
    }


def case(name):
    kind = "weight"
    value = payload(kind)
    if name.startswith("weight:"):
        value["weight_kg"] = name.split(":", 1)[1]
    elif name.startswith("meal:"):
        kind, value = "meal", payload("meal")
        value["title"] = name.split(":", 1)[1]
    elif name.startswith("profile:"):
        kind, value = "profile", payload("profile")
        value["pseudonym"] = name.split(":", 1)[1]
    elif name.startswith("goal-decimal:"):
        kind, value = "goal", payload("goal")
        value["energy_kcal"] = name.split(":", 1)[1]
    elif name.startswith("macro:"):
        kind, value = "meal", payload("meal")
        value["items"][0]["nutrition_per_100"]["energy_kcal"] = name.split(":", 1)[1]
    else:
        if name.startswith("goal-time:"):
            kind, value = "goal", payload("goal")
        upper = name.endswith("upper")
        instant = "9999-12-31T23:00:00Z" if upper else "0001-01-01T00:00:00Z"
        value["time_zone"] = "Pacific/Kiritimati" if upper else "Etc/GMT+12"
        if kind == "goal":
            value["decided_at"] = instant
            value["effective_from"] = instant[:10]
        else:
            value["occurred_at"] = instant
            value["local_date"] = instant[:10]
    return kind, value


BAD = [
    "weight:0\n",
    "weight:82.5\n",
    "weight:82.5\r\n",
    "weight: 82.5",
    "weight:82.5 ",
    "weight:+1",
    "weight:-0",
    "weight:1.0",
    "weight:1e1",
    "weight:0",
    "weight:١",
    "meal:bad\ud800",
    "meal:bad\udfff",
    "meal:bad\x00",
    "profile:bad\x00",
    "profile:bad\ud800",
    "goal-decimal:0\n",
    "goal-decimal:2500\n",
    "macro:0\n",
    "time:upper",
    "time:lower",
    "goal-time:upper",
    "goal-time:lower",
]


@pytest.mark.parametrize("name", BAD, ids=[f"case-{i}" for i in range(len(BAD))])
def test_invalid_second_operation_is_422_and_whole_database_unchanged(wire_context, name):
    http, engine, epoch, checkpoint = wire_context
    kind, value = case(name)
    operations = [op(epoch, "weight", payload("weight")), op(epoch, kind, value)]
    body = {
        "protocol_version": 1,
        "sync_epoch": epoch,
        "checkpoint": checkpoint,
        "operations": operations,
    }
    before = snapshot(engine)
    # ASCII escaping is intentional: malformed Unicode arrives as valid UTF-8
    # JSON escape syntax; it must still be rejected before hashing/DB execution.
    raw = json.dumps(body, ensure_ascii=True).encode("utf-8")
    response = http.post(
        "/api/v1/sync/push", content=raw, headers={"Content-Type": "application/json"}
    )
    after = snapshot(engine)
    assert (response.status_code, response.json()["code"], after == before) == (
        422,
        "invalid_request",
        True,
    ), {
        "status": response.status_code,
        "code": response.json()["code"],
        "changed_tables": [table for table in before if before[table] != after[table]],
    }


@pytest.mark.parametrize("text", ["Zażółć gęślą jaźń 😀", "Line 1\nLine 2", "\U00010000"])
def test_valid_unicode_and_known_zero_remain_accepted(wire_context, text):
    http, _, epoch, checkpoint = wire_context
    value = payload("meal")
    value["title"] = text
    value["items"][0]["nutrition_per_100"]["energy_kcal"] = "0"
    value["items"][0]["nutrition_per_100"]["protein_g"] = None
    response = http.post(
        "/api/v1/sync/push",
        json={
            "protocol_version": 1,
            "sync_epoch": epoch,
            "checkpoint": checkpoint,
            "operations": [op(epoch, "meal", value)],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "accepted"
