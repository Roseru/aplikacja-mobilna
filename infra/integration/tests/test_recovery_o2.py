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
