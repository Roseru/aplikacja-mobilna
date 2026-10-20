"""Exercise the operator's actual SQL against committed PG17 sync operations."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from calorie_app.health import EXPECTED_REVISION
from tests.integration import test_e4_push as push

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra/integration"))
from e4_observer import compare, observation_sql, prepare_plan

pytestmark = pytest.mark.integration
IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def synced(database):
    return push.synced.__wrapped__(database)


def plan_for(synced, op):
    context = {
        "trial_id": str(uuid4()),
        "owner_id": str(synced[3]),
        "expected_schema": EXPECTED_REVISION,
        "expected_api_image": IMAGE,
    }
    return prepare_plan(context, json.dumps(push.request(synced[4], synced[5], [op])).encode())


def observe(engine, plan, phase):
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        with connection.connection.driver_connection.cursor() as cursor:
            cursor.execute(observation_sql(plan, phase), prepare=False)
            result = None
            while True:
                if cursor.description:
                    result = cursor.fetchone()[0]
                if not cursor.nextset():
                    break
    result.update(api_image=IMAGE, postgres_container="owned-test-postgres")
    return result


@pytest.mark.parametrize("existing_day", [False, True])
def test_committed_create_and_replay_observations(synced, existing_day):
    op = push.operation(synced[4], "meal")
    # Meaningful null/zero and NUMERIC(12,6)/UTC normalization on real storage.
    op["payload"]["items"][0]["nutrition_per_100"].update(protein_g=None, fat_g="0")
    if existing_day:
        day = push.operation(
            synced[4],
            "diary_day",
            payload={
                "local_date": op["payload"]["local_date"],
                "time_zone": op["payload"]["time_zone"],
                "declared_complete": False,
            },
        )
        assert push.send(synced, [day])[0]["status"] == "accepted"
    plan = plan_for(synced, op)
    c0 = observe(synced[0], plan, "C0")
    assert c0["read_only"] == "on" and c0["meal"] is None
    assert push.send(synced, [op])[0]["status"] == "accepted"
    c1 = observe(synced[0], plan, "C1")
    replay = push.send(synced, [op])[0]
    assert replay["status"] == "already_applied" and replay["revision"] == 1
    c2 = observe(synced[0], plan, "C2")
    assert c1["position"] - (c0["position"] or 0) == (1 if existing_day else 2)
    result = compare(plan, [c0, c1, c2])
    assert result["server_observations"] == "PASS"
    assert result["overall_apk_api_trial"] == "REQUIRES_SEPARATE_O1_HTTP_ROOM_RESTART_EVIDENCE"
    # A retained original revision, request hash and independent context are mandatory.
    for field, value in (("revision", 2), ("request_hash", "0" * 64)):
        wrong = deepcopy(c1)
        wrong["receipt"][field] = value
        with pytest.raises(ValueError, match="expected committed"):
            compare(plan, [c0, wrong, c2])
    wrong = deepcopy(c2)
    wrong["account"]["generation"] += 1
    with pytest.raises(ValueError, match="context"):
        compare(plan, [c0, c1, wrong])


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("meal_items", "name", "unexpected replay mutation"),
        ("sync_receipts", "revision", 2),
    ],
)
def test_replay_row_mutation_is_detected_even_when_counts_match(synced, table, column, value):
    op = push.operation(synced[4], "meal")
    plan = plan_for(synced, op)
    c0 = observe(synced[0], plan, "C0")
    push.send(synced, [op])
    c1 = observe(synced[0], plan, "C1")
    push.send(synced, [op])
    with synced[0].begin() as connection:
        connection.execute(
            text(f"UPDATE app.{table} SET {column}=:value WHERE owner_id=:owner"),
            {"value": value, "owner": synced[3]},
        )
    c2 = observe(synced[0], plan, "C2")
    assert {t: v["count"] for t, v in c1["tables"].items()} == {
        t: v["count"] for t, v in c2["tables"].items()
    }
    with pytest.raises(ValueError, match="Replay changed"):
        compare(plan, [c0, c1, c2])


@pytest.mark.parametrize(
    "column,expression",
    [
        ("protein_g", "0"),
        ("quantity_amount", "quantity_amount + 1"),
        ("nutrition_origin", "'ai_estimate'"),
    ],
)
def test_wrong_committed_content_is_rejected_before_identical_replay(synced, column, expression):
    op = push.operation(synced[4], "meal")
    op["payload"]["items"][0]["nutrition_per_100"]["protein_g"] = None
    plan = plan_for(synced, op)
    c0 = observe(synced[0], plan, "C0")
    assert c0["position"] is None
    assert push.send(synced, [op])[0]["status"] == "accepted"
    # Isolated test DB only. Keep receipt/hash and all row counts untouched.
    with synced[0].begin() as connection:
        connection.execute(
            text(f"UPDATE app.meal_items SET {column}={expression} WHERE owner_id=:owner"),
            {"owner": synced[3]},
        )
    c1 = observe(synced[0], plan, "C1")
    assert push.send(synced, [op])[0]["status"] == "already_applied"
    c2 = observe(synced[0], plan, "C2")
    assert c1["tables"] == c2["tables"] and c1["receipt"] == c2["receipt"]
    assert c1["receipt"]["request_hash"] == plan["operation_sha256"]
    with pytest.raises(ValueError, match="C1 Meal content"):
        compare(plan, [c0, c1, c2])
