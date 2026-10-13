"""Capability upgrade preserves the legacy protocol, ACKs and frozen snapshots."""

import pytest

from calorie_app.modules.sync.schemas import PullResponse
from tests.integration.test_e4_push import operation
from tests.integration.test_e7_runtime import client
from tests.integration.test_e7_runtime import e7 as e7_fixture
from tests.integration.test_e9_energy import create, decision, post, read, run, seed

e7 = e7_fixture
pytestmark = pytest.mark.integration
OPT_IN = {"X-Sync-Capability": "energy_estimates_v1"}


def pull(rt, query=None, headers=None):
    with client(rt) as http:
        return http.get("/api/v1/sync/pull", params=query or {}, headers=headers or {})


def test_legacy_skips_energy_but_advances_checkpoint(e7):
    seed(e7)
    legacy = pull(e7).json()
    PullResponse.model_validate(legacy)
    assert all(v["entity_type"] != "energy_estimate" for v in legacy["entities"])
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    assert post(e7, "analyses/accept", decision(e7, ready)).status_code == 200
    result = pull(
        e7, {"sync_epoch": e7["boots"][0]["sync_epoch"], "checkpoint": legacy["checkpoint"]}
    )
    assert result.status_code == 200, result.text
    next_page = result.json()
    PullResponse.model_validate(next_page)
    assert next_page["entities"] == [] and next_page["checkpoint"] != legacy["checkpoint"]
    repeated = pull(
        e7, {"sync_epoch": e7["boots"][0]["sync_epoch"], "checkpoint": next_page["checkpoint"]}
    )
    assert repeated.json()["entities"] == []


def test_upgrade_requires_snapshot_and_existing_outbox_push_stays_valid(e7):
    seed(e7)
    legacy = pull(e7).json()
    drift = pull(
        e7, {"sync_epoch": e7["boots"][0]["sync_epoch"], "checkpoint": legacy["checkpoint"]}, OPT_IN
    )
    assert drift.status_code == 422 and drift.json()["code"] == "invalid_sync_token"
    fresh = pull(e7, headers=OPT_IN)
    assert fresh.status_code == 200, fresh.text
    page = fresh.json()
    assert page["mode"] == "snapshot"
    assert sum(v["entity_type"] == "energy_estimate" for v in page["entities"]) == 1
    # These operation bytes were prepared under the legacy contract before
    # capability upgrade; only the envelope receives its new scoped checkpoint.
    queued = operation(e7["boots"][0], "weight")
    with client(e7) as http:
        pushed = http.post(
            "/api/v1/sync/push",
            headers=OPT_IN,
            json={
                "protocol_version": 1,
                "sync_epoch": e7["boots"][0]["sync_epoch"],
                "checkpoint": page["checkpoint"],
                "operations": [queued],
            },
        )
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["results"][0]["status"] == "accepted"
    cross = pull(e7, {"sync_epoch": e7["boots"][0]["sync_epoch"], "checkpoint": page["checkpoint"]})
    assert cross.status_code == 422


def test_capability_cannot_mix_snapshot_continuations(e7):
    seed(e7)
    page = pull(e7, {"limit": 1}, OPT_IN).json()
    assert page["page_token"] is not None
    query = {
        "limit": 1,
        "sync_epoch": e7["boots"][0]["sync_epoch"],
        "snapshot_token": page["snapshot_token"],
        "page_token": page["page_token"],
    }
    assert pull(e7, query).status_code == 422
    assert pull(e7, query, OPT_IN).status_code == 200


def test_incremental_opt_in_emits_new_e_without_goal_mutation(e7):
    seed(e7)
    before = pull(e7, headers=OPT_IN).json()
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    accepted = post(e7, "analyses/accept", decision(e7, ready))
    assert accepted.status_code == 200, accepted.text
    page = pull(
        e7, {"sync_epoch": e7["boots"][0]["sync_epoch"], "checkpoint": before["checkpoint"]}, OPT_IN
    )
    assert page.status_code == 200, page.text
    assert [v["entity_type"] for v in page.json()["entities"]] == ["energy_estimate"]
    assert page.json()["entities"][0] == accepted.json()
