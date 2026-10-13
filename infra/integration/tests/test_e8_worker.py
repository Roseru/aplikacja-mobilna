import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Timer

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e8_worker import aggregate, healthy, run_once  # noqa: E402
from run_e8 import prepare  # noqa: E402


def child_program(monkeypatch, code):
    original = subprocess.Popen

    def launch(command, **kwargs):
        assert command[1:3] == ["-I", "-m"]
        return original([sys.executable, "-I", "-c", code], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch)


def test_ready_with_backlog_is_healthy_and_does_not_claim_empty(monkeypatch, tmp_path):
    child_program(
        monkeypatch,
        'print(\'{"processed":100,"finalized":100,"backlog":3,"ready":true,"owner":"private-secret"}\')',
    )
    result = run_once("finalizer", tmp_path, Event())
    assert result["state"] == "pending" and result["metrics"]["backlog"] == 3
    assert healthy(result)
    assert "private-secret" not in (tmp_path / "status.json").read_text()


def test_disabled_is_not_success_and_preserves_historical_timestamp(monkeypatch, tmp_path):
    previous = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    (tmp_path / "status.json").write_text(json.dumps({"last_success": previous}))
    child_program(
        monkeypatch,
        'import sys; print(\'{"processed":0,"finalized":0,"backlog":0,"ready":false}\'); '
        "sys.exit(2)",
    )
    result = run_once("finalizer", tmp_path, Event())
    assert result["state"] == "disabled" and result["last_success"] == previous
    assert not healthy(result)


@pytest.mark.parametrize(
    "output", ["secret postgresql://credential", '{"processed":true}', '{"owner":"private-secret"}']
)
def test_malformed_or_private_child_output_never_leaks(monkeypatch, tmp_path, output):
    child_program(monkeypatch, f"print({output!r})")
    result = run_once("finalizer", tmp_path, Event())
    assert result["state"] == "failed" and not healthy(result)
    assert output not in (tmp_path / "status.json").read_text()


def test_timeout_terminates_live_process_without_success(monkeypatch, tmp_path):
    child_program(monkeypatch, "import time; time.sleep(30)")
    result = run_once("lifecycle", tmp_path, Event(), timeout=0.3)
    assert result["state"] == "timeout" and result["elapsed_seconds"] < 5
    assert result["last_success"] is None and not healthy(result)


def test_spawn_failure_is_persisted_as_failed_not_running(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise OSError("private credentials in operating system diagnostic")

    monkeypatch.setattr(subprocess, "Popen", unavailable)
    result = run_once("lifecycle", tmp_path, Event())
    assert result["state"] == "failed" and not healthy(result)
    assert "credentials" not in (tmp_path / "status.json").read_text()


def test_stop_terminates_live_process(monkeypatch, tmp_path):
    stop = Event()
    child_program(monkeypatch, "import time; time.sleep(30)")
    timer = Timer(0.3, stop.set)
    timer.start()
    try:
        result = run_once("motivation", tmp_path, stop)
        assert result["state"] == "stopped" and not healthy(result)
    finally:
        timer.join()


def test_old_running_status_cannot_hide_stale_success():
    at = datetime.now(UTC)
    status = {"state": "running", "last_success": (at - timedelta(seconds=131)).isoformat()}
    assert not healthy(status, at=at)
    assert not healthy(status | {"last_success": (at + timedelta(seconds=1)).isoformat()}, at=at)


def test_provision_state_preserves_existing_passwords_and_never_mixes_logins(tmp_path):
    original = "POSTGRES_PASSWORD=" + "b3" * 32 + "\nAPP_API_PASSWORD=untouched\n"
    (tmp_path / "postgres.env").write_text(original)
    prepare(tmp_path)
    snapshot = {p.name: p.read_bytes() for p in tmp_path.glob("*.env")}
    prepare(tmp_path)
    assert snapshot == {p.name: p.read_bytes() for p in tmp_path.glob("*.env")}
    for task in ("motivation", "lifecycle", "finalizer"):
        assert (tmp_path / f"e8-{task}.env").read_text().count("DATABASE_URL=") == 1
        assert "PGPASSWORD" not in (tmp_path / f"e8-{task}.env").read_text()
    assert (tmp_path / "postgres.env").read_text() == original
    (tmp_path / "e8-lifecycle.env").write_text("DATABASE_URL=unexpected-private\n")
    with pytest.raises(ValueError, match="Preserve"):
        prepare(tmp_path)
    assert (tmp_path / "e8-lifecycle.env").read_text() == "DATABASE_URL=unexpected-private\n"


def test_motivation_metrics_keep_null_maturity_and_exact_pending_counts():
    result = aggregate(
        "motivation",
        {
            "status": "ok",
            "owners_handled": 2,
            "dates_processed": 10,
            "backlog": {
                "pending_backfill": 5,
                "pending_materialization": 3,
                "oldest_matures_at": None,
            },
            "raw": "private",
        },
    )
    assert result["backlog"] == {
        "pending_backfill": 5,
        "pending_materialization": 3,
        "oldest_matures_at": None,
    }
    assert "raw" not in result
