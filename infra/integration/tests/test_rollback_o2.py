"""Neutral failure receipts; all rehearsal dependencies are synthetic, without Docker."""

import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rollback_o2  # noqa: E402
from rollback_o2 import CommandAction, command, rehearse_predecessor  # noqa: E402

SECRET = "synthetic-JWT-DSN-account-SQL-private-path"


@pytest.fixture
def synthetic_predecessor(monkeypatch):
    """Reach the real capture/rehearse loop and receipt writer with no external effects."""
    compose_calls = []
    stack = SimpleNamespace(compose=lambda *args: compose_calls.append(args))
    historical = SimpleNamespace(initialize=lambda *a, **k: None, Stack=lambda _: stack)
    monkeypatch.setattr(rollback_o2, "private_directory", lambda path: path.mkdir())
    monkeypatch.setattr(rollback_o2.importlib.util, "spec_from_file_location", lambda *a: None)
    monkeypatch.setattr(rollback_o2.importlib.util, "module_from_spec", lambda _: historical)
    historical.loader = SimpleNamespace(exec_module=lambda _: None)
    monkeypatch.setattr(
        rollback_o2.importlib.util,
        "spec_from_file_location",
        lambda *a: SimpleNamespace(loader=historical.loader),
    )
    monkeypatch.setattr(
        rollback_o2.tarfile,
        "open",
        lambda _: nullcontext(SimpleNamespace(extractall=lambda *a, **k: None)),
    )
    monkeypatch.setattr(
        rollback_o2,
        "inspect",
        lambda image, template: (
            rollback_o2.PREDECESSOR if "Label" in template else "sha256:synthetic"
        ),
    )
    monkeypatch.setattr(rollback_o2, "quiet_sql", lambda *a: rollback_o2.REVISION)
    monkeypatch.setattr(rollback_o2, "verify_meals", lambda *a: None)

    def api(method, path, **kwargs):
        body = {
            "/api/v1/me/bootstrap": {"account_id": "synthetic", "sync_epoch": "old"},
            "/api/v1/sync/pull": {"checkpoint": "synthetic"},
            "/api/v1/sync/push": {"results": [{"status": "accepted"}]},
        }[path]
        return SimpleNamespace(status_code=200, json=lambda: body)

    probe = SimpleNamespace(ready=lambda: None, login=lambda _: {"access_token": SECRET}, api=api)
    monkeypatch.setattr(rollback_o2, "Probe", lambda _: probe)
    monkeypatch.setattr(
        rollback_o2,
        "verify_archive",
        lambda _: pytest.fail("Failure must stop before archive verification"),
    )
    monkeypatch.setenv("O3_SYNTHETIC_SECRET", SECRET)
    return compose_calls


@pytest.mark.parametrize("action", ["capture", "rehearse"])
@pytest.mark.parametrize("failure_kind", ["exit", "signal", "timeout"])
def test_public_receipt_distinguishes_action_and_failure_without_private_data(
    tmp_path, monkeypatch, capsys, synthetic_predecessor, action, failure_kind
):
    backup_actions = []
    failures = []

    def child(arguments, **kwargs):
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 600
        assert kwargs["stdout"] is kwargs["stderr"]
        kwargs["stdout"].write(SECRET.encode())
        if len(arguments) > 2 and arguments[1].endswith("backup.py"):
            called_action = arguments[2]
            backup_actions.append(called_action)
            assert kwargs["env"]["O3_SYNTHETIC_SECRET"] == SECRET
            if called_action == action:
                # Exception text/output/argv deliberately carry synthetic private data.
                private_argv = arguments + [SECRET]
                if failure_kind == "timeout":
                    error = subprocess.TimeoutExpired(
                        private_argv, 600, output=SECRET, stderr=SECRET
                    )
                else:
                    error = subprocess.CalledProcessError(
                        23 if failure_kind == "exit" else -9,
                        private_argv,
                        output=SECRET,
                        stderr=SECRET,
                    )
                failures.append(error)
                raise error
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(rollback_o2.subprocess, "run", child)
    root = tmp_path / SECRET
    with pytest.raises((subprocess.CalledProcessError, subprocess.TimeoutExpired)) as raised:
        rehearse_predecessor(root, "0" * 40, "sha256:current")
    assert raised.value is failures[0]
    assert SECRET in str(raised.value)
    assert backup_actions == (["capture"] if action == "capture" else ["capture", "rehearse"])
    assert synthetic_predecessor[-1] == ("down",)
    assert synthetic_predecessor.count(("down",)) == 1
    receipt_text = (tmp_path / "rollback.json").read_text()
    receipt = json.loads(receipt_text)
    assert receipt["result"] == "FAIL"
    assert receipt["stage"] == "historical_capture_and_globals_rehearsal"
    assert receipt["error_kind"] == type(raised.value).__name__
    assert receipt["command_failure"] == {
        "action": action,
        "returncode": {"exit": 23, "signal": -9, "timeout": None}[failure_kind],
        "timed_out": failure_kind == "timeout",
    }
    assert "paired_globals_rehearsal" not in receipt
    assert SECRET not in receipt_text
    assert str(tmp_path) not in receipt_text
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("returncode", [0, 23])
def test_real_child_output_stays_in_private_append_log(tmp_path, capsys, returncode):
    log = tmp_path / "experiment-private.log"
    log.write_bytes(b"previous\n")
    arguments = [
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1]); print(sys.argv[1], file=sys.stderr); "
        "sys.exit(int(sys.argv[2]))",
        SECRET,
        str(returncode),
    ]
    if returncode:
        with pytest.raises(subprocess.CalledProcessError) as raised:
            command(tmp_path, arguments, action=CommandAction.CAPTURE)
        assert raised.value.returncode == returncode
    else:
        command(tmp_path, arguments, action=CommandAction.CAPTURE)
    assert log.read_bytes().startswith(b"previous\n")
    assert log.read_text().count(SECRET) == 2
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("label", ["capture", SECRET, None, 1])
def test_unknown_or_untyped_labels_are_refused_before_any_io(tmp_path, monkeypatch, label):
    monkeypatch.setattr(
        rollback_o2.subprocess, "run", lambda *a, **k: pytest.fail("No child allowed")
    )
    with pytest.raises(TypeError, match="^Invalid rollback command action$"):
        command(tmp_path, [SECRET], action=label)
    assert list(tmp_path.iterdir()) == []


def test_cleanup_failure_does_not_overwrite_original_diagnostic(
    tmp_path, monkeypatch, synthetic_predecessor
):
    original = subprocess.CalledProcessError(31, [SECRET])

    def child(arguments, **kwargs):
        if len(arguments) > 2 and arguments[1].endswith("backup.py"):
            raise original
        return subprocess.CompletedProcess(arguments, 0)

    def compose(*args):
        if args == ("down",):
            raise RuntimeError("synthetic cleanup failure")

    # Keep build/up synthetic, then fail the cleanup as well as capture.
    monkeypatch.setattr(rollback_o2.subprocess, "run", child)
    monkeypatch.setattr(
        rollback_o2.importlib.util,
        "module_from_spec",
        lambda _: SimpleNamespace(
            initialize=lambda *a, **k: None, Stack=lambda _: SimpleNamespace(compose=compose)
        ),
    )
    with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
        rehearse_predecessor(tmp_path / "state", "0" * 40, "sha256:current")
    receipt = json.loads((tmp_path / "rollback.json").read_text())
    assert receipt["result"] == "FAIL" and receipt["cleanup_failed"] is True
    assert receipt["error_kind"] == "CalledProcessError"
    assert receipt["command_failure"] == {"action": "capture", "returncode": 31, "timed_out": False}


def test_later_assertion_does_not_inherit_a_successful_command_label(
    tmp_path, monkeypatch, synthetic_predecessor
):
    monkeypatch.setattr(
        rollback_o2.subprocess,
        "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 0),
    )

    def verify(_):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(rollback_o2, "verify_archive", verify)
    with pytest.raises(RuntimeError, match=SECRET):
        rehearse_predecessor(tmp_path / "state", "0" * 40, "sha256:current")
    receipt_text = (tmp_path / "rollback.json").read_text()
    receipt = json.loads(receipt_text)
    assert receipt["result"] == "FAIL" and receipt["error_kind"] == "RuntimeError"
    assert receipt["stage"] == "historical_capture_and_globals_rehearsal"
    assert "command_failure" not in receipt
    assert SECRET not in receipt_text
