import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor  # noqa: E402
from monitor import CHECKS, GitHub, deliver, worker_ok  # noqa: E402


@pytest.mark.skipif(os.name != "nt", reason="Windows console allocation regression")
def test_probe_child_has_no_console():
    result = monitor.command(
        [
            sys.executable,
            "-I",
            "-c",
            "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())",
        ]
    )
    assert result.strip() == "0"


def test_credential_child_uses_same_console_policy(monkeypatch, tmp_path):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "password=synthetic-test-token\n"})()

    monkeypatch.setattr(monitor.subprocess, "run", run)
    github = GitHub(tmp_path)
    assert github.token == "synthetic-test-token"
    arguments, options = calls[0]
    assert arguments == ["git", "credential", "fill"]
    assert options["env"]["GCM_INTERACTIVE"] == "Never"
    if os.name == "nt":
        assert options["creationflags"] == monitor.subprocess.CREATE_NO_WINDOW
    else:
        assert "creationflags" not in options


def measurement(api="ok"):
    checks = {key: {"state": "ok"} for key in CHECKS}
    checks["api"]["state"] = api
    checks["ai"]["state"] = "not_deployed"
    checks["backup"]["state"] = "not_configured"
    return {"checks": checks}


@pytest.mark.parametrize(
    "capture_age,verified,expected",
    [(3600, True, "ok"), (90000, True, "failed"), (-300, True, "failed"), (3600, False, "failed")],
)
def test_offsite_capture_age_cannot_be_reset_by_rechecking_old_archive(
    tmp_path, capture_age, verified, expected
):
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps(
            {
                "verified_at": datetime.now(UTC).isoformat(),
                "archive_captured_at": (
                    datetime.now(UTC) - timedelta(seconds=capture_age)
                ).isoformat(),
                "offsite_verified": verified,
            }
        )
    )
    assert monitor.offsite_reading(path) == {"state": expected}


def test_legacy_offsite_receipt_and_missing_receipt(tmp_path):
    path = tmp_path / "receipt.json"
    assert monitor.offsite_reading(path) == {"state": "failed"}
    path.write_text(
        json.dumps({"verified_at": datetime.now(UTC).isoformat(), "offsite_verified": True})
    )
    assert monitor.offsite_reading(path) == {"state": "ok"}


class Sender:
    def __init__(self):
        self.calls = []

    def incident(self, *args):
        self.calls.append(args)
        return 42


def test_debounce_deduplicate_and_recover():
    sender, ledger = Sender(), {}
    deliver(measurement("failed"), ledger, sender)
    assert not sender.calls
    deliver(measurement(), ledger, sender)
    deliver(measurement("failed"), ledger, sender)
    assert not sender.calls
    deliver(measurement("failed"), ledger, sender)
    deliver(measurement("failed"), ledger, sender)
    assert sender.calls == [("api", None, True, False)]
    deliver(measurement(), ledger, sender)
    assert sender.calls[-1] == ("api", 42, False, False)
    deliver(measurement(), ledger, sender)
    assert len(sender.calls) == 2


def test_notification_failure_is_retried():
    sender, ledger = Sender(), {}
    deliver(measurement("failed"), ledger, sender)

    def fail(*_):
        raise RuntimeError("credential-private-canary")

    sender.incident = fail
    with pytest.raises(RuntimeError):
        deliver(measurement("failed"), ledger, sender)
    assert ledger["api"]["active"] is False
    sender.incident = Sender().incident
    deliver(measurement("failed"), ledger, sender)
    assert ledger["api"]["active"] is True


def test_running_backup_does_not_clear_an_existing_incident():
    sender, ledger = Sender(), {}
    value = measurement()
    value["checks"]["local_backup"]["state"] = "failed"
    deliver(value, ledger, sender)
    deliver(value, ledger, sender)
    assert ledger["local_backup"]["active"] is True
    count = len(sender.calls)
    value["checks"]["local_backup"]["state"] = "running"
    deliver(value, ledger, sender)
    assert len(sender.calls) == count and ledger["local_backup"]["active"] is True


@pytest.mark.parametrize("seconds,expected", [(0, True), (181, False), (-60, False)])
def test_disabled_finalizer_still_requires_fresh_attempt(seconds, expected):
    status = {
        "state": "disabled",
        "metrics": {"ready": False},
        "last_attempt": (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(),
    }
    assert worker_ok(status, disabled=True) is expected
    status["state"] = "failed"
    assert not worker_ok(status, disabled=True)


def test_uncertain_post_reconciles_without_duplicate_and_redacts():
    github = GitHub.__new__(GitHub)
    calls = []

    def request(path, method="GET", data=None):
        calls.append((path, method, data))
        if path.startswith("issues?"):
            return [
                {
                    "number": 42,
                    "title": "[O3 monitoring test] api",
                    "body": "<!-- o3-monitor:test:api -->",
                    "state": "open",
                }
            ]
        if method == "PATCH":
            return data
        return {"number": 42, "state": "open", "body": "<!-- o3-monitor:test:api -->"}

    github.request = request
    assert github.incident("api", None, True, True) == 42
    assert not any(method == "POST" for _, method, _ in calls)
    assert "Authorization" not in json.dumps(calls)


def test_unconfirmed_recovery_does_not_clear_incident():
    github = GitHub.__new__(GitHub)
    github.request = lambda *_: {"state": "open", "body": "<!-- o3-monitor:live:api -->"}
    with pytest.raises(RuntimeError, match="unconfirmed"):
        github.incident("api", 42, False)


def test_https_probe_closes_connection_after_bad_response(monkeypatch, tmp_path):
    class Connection:
        closed = False

        def __init__(self, *_args, **_kwargs):
            self.sock = self

        def connect(self):
            pass

        def getpeercert(self):
            return {"notAfter": "Jan 1 00:00:00 2030 GMT"}

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return type("Response", (), {"status": 503, "read": lambda *_: b"private"})()

        def close(self):
            Connection.closed = True

    monkeypatch.setattr(monitor, "LocalHTTPS", Connection)
    monkeypatch.setattr(monitor.ssl, "create_default_context", lambda **_: None)
    with pytest.raises(ValueError, match="readiness unavailable"):
        monitor.https(
            {"origin": "https://example.invalid:18443", "host": "example.invalid"},
            tmp_path,
            "/health/ready",
        )
    assert Connection.closed
