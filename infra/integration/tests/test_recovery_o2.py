"""Ledger refusal cases: these validate a fixture, never production authority."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup import digest  # noqa: E402
from recovery_o2 import verify_fixture_ledger  # noqa: E402


def fixture(tmp_path):
    path = tmp_path / "external.json"
    target = {"account_id": "synthetic"}
    path.write_text(
        json.dumps(
            {
                "source": "owned-live-deletion-observation-v1",
                "target": target,
                "complete_through": "2026-10-17T12:00:00+00:00",
                "completed": True,
            }
        )
    )
    return path, target


def test_exact_observed_fixture_is_accepted(tmp_path):
    path, target = fixture(tmp_path)
    assert (
        verify_fixture_ledger(
            path, digest(path), expected=target, cutoff="2026-10-17T12:00:00+00:00"
        )["completed"]
        is True
    )


@pytest.mark.parametrize(
    "change", ["missing", "tamper", "identity", "stale", "incomplete", "origin"]
)
def test_missing_conflicting_stale_ledger_keeps_recovery_closed(tmp_path, change):
    path, target = fixture(tmp_path)
    pinned = digest(path)
    cutoff = "2026-10-17T12:00:00+00:00"
    if change == "missing":
        path.unlink()
    elif change == "identity":
        target = {"account_id": "other"}
    elif change == "stale":
        cutoff = "2026-10-17T12:00:01+00:00"
    else:
        entry = json.loads(path.read_text())
        if change == "origin":
            entry["source"] = "untrusted"
        else:
            entry["completed"] = False
        path.write_text(json.dumps(entry))
        if change != "tamper":
            pinned = digest(path)
    with pytest.raises(RuntimeError):
        verify_fixture_ledger(path, pinned, expected=target, cutoff=cutoff)


def test_existing_state_is_refused_without_any_write(tmp_path):
    import subprocess
    import sys

    state = tmp_path / "existing"
    state.mkdir()
    original = state / "owned-by-someone-else.txt"
    original.write_text("preserve")
    script = Path(__file__).resolve().parents[1] / "recovery_o2.py"
    result = subprocess.run(
        [sys.executable, str(script), "--state", str(state)], capture_output=True, timeout=15
    )
    assert result.returncode == 1
    assert list(state.iterdir()) == [original]
    assert original.read_text() == "preserve"


@pytest.mark.parametrize("status", [200, 401, 502])
def test_maintenance_open_or_wrong_route_is_immediate_failure(status):
    from types import SimpleNamespace

    import httpx
    from recovery_o2 import wait_maintenance

    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(status)

    probe = SimpleNamespace(
        stack=SimpleNamespace(origin="https://owned.example"),
        issuer="https://owned.example/realms/calorie-dev",
        client=lambda: httpx.Client(transport=httpx.MockTransport(reply)),
    )
    with pytest.raises(RuntimeError, match="expected 503"):
        wait_maintenance(probe)
    assert len(calls) == 1


def test_maintenance_waits_only_for_transport_then_requires_both_closed(monkeypatch):
    from types import SimpleNamespace

    import httpx
    import recovery_o2

    calls = []

    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("owned listener not ready", request=request)
        return httpx.Response(503)

    probe = SimpleNamespace(
        stack=SimpleNamespace(origin="https://owned.example"),
        issuer="https://owned.example/realms/calorie-dev",
        client=lambda: httpx.Client(transport=httpx.MockTransport(reply)),
    )
    monkeypatch.setattr(recovery_o2.time, "sleep", lambda _: None)
    recovery_o2.wait_maintenance(probe)
    assert len(calls) == 3
    assert calls[-1].method == "POST" and calls[-1].url.path.endswith("/token")


def recovery_case():
    from copy import deepcopy

    from recovery_o2 import meal

    boot = {"sync_epoch": "new"}
    baseline = meal(boot, "baseline")
    recovery = meal(boot, "lost")
    recovery["recovery"] = {"source_epoch": "old", "source_entity_id": "source"}
    second = recovery | {"operation_id": "second-op", "entity_id": "second-target"}
    mapping = {
        "source_epoch": "old",
        "source_entity_id": "source",
        "target_entity_id": recovery["entity_id"],
        "target_revision": 1,
    }
    first = {
        "operation_id": recovery["operation_id"],
        "entity_id": recovery["entity_id"],
        "status": "accepted",
        "recovery_mapping": deepcopy(mapping),
    }
    replay = {
        "operation_id": second["operation_id"],
        "entity_id": second["entity_id"],
        "status": "already_applied",
        "recovery_mapping": deepcopy(mapping),
    }
    entities = [
        {
            "entity_type": "meal",
            "entity_id": op["entity_id"],
            "revision": 1,
            "deleted": False,
            "payload": deepcopy(op["payload"]),
        }
        for op in (baseline, recovery)
    ]
    stored = {
        "meals": [
            {"id": op["entity_id"], "owner": "A", "revision": 1, "deleted": False}
            for op in (baseline, recovery)
        ],
        "mappings": [mapping | {"owner": "A", "entity_type": "meal"}],
    }
    return baseline, recovery, second, first, replay, entities, stored


def test_recovery_oracle_accepts_one_owned_meal_and_requested_second_response_id():
    from recovery_o2 import verify_recovered_state, verify_recovery_result

    base, recovery, second, first, replay, entities, stored = recovery_case()
    verify_recovery_result(first, recovery, recovery["entity_id"], "accepted")
    verify_recovery_result(replay, second, recovery["entity_id"], "already_applied")
    verify_recovered_state(recovery, second, base, "A", entities, stored)


@pytest.mark.parametrize(
    "fault",
    ["null", "source_epoch", "source_entity_id", "target_entity_id", "target_revision", "status"],
)
def test_recovery_response_oracle_rejects_null_wrong_source_target_or_second_status(fault):
    from recovery_o2 import verify_recovery_result

    _, recovery, second, first, replay, _, _ = recovery_case()
    if fault == "null":
        first["recovery_mapping"] = replay["recovery_mapping"] = None
    elif fault == "status":
        replay["status"] = "accepted"
    else:
        replay["recovery_mapping"][fault] = "wrong"
    with pytest.raises(RuntimeError):
        verify_recovery_result(first, recovery, recovery["entity_id"], "accepted")
        verify_recovery_result(replay, second, recovery["entity_id"], "already_applied")


@pytest.mark.parametrize(
    "fault", ["duplicate", "mapping", "owner", "content", "item", "nutrition", "missing"]
)
def test_recovery_storage_oracle_rejects_duplicate_foreign_or_corrupt_meal(fault):
    from copy import deepcopy

    from recovery_o2 import verify_recovered_state

    base, recovery, second, _, _, entities, stored = recovery_case()
    if fault == "duplicate":
        stored["meals"].append(stored["meals"][-1] | {"id": second["entity_id"]})
    elif fault == "mapping":
        stored["mappings"].append(deepcopy(stored["mappings"][0]))
    elif fault == "owner":
        stored["meals"][-1]["owner"] = "B"
    elif fault == "content":
        entities[-1]["payload"]["title"] = "corrupt"
    elif fault == "item":
        entities[-1]["payload"]["items"] = []
    elif fault == "nutrition":
        entities[-1]["payload"]["items"][0]["nutrition_per_100"]["energy_kcal"] = "0"
    else:
        stored["meals"].pop()
    with pytest.raises(RuntimeError):
        verify_recovered_state(recovery, second, base, "A", entities, stored)
