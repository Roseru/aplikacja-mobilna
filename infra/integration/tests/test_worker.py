import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import prepare_worker  # noqa: E402
from worker import healthy, number, read_json, write_json  # noqa: E402


def test_health_rejects_failed_stopped_missing_future_and_stale_success():
    at = datetime.now(UTC)
    status = {"state": "ok", "last_success": (at - timedelta(seconds=5)).isoformat()}
    assert healthy(status, 10, at=at)
    assert healthy(status | {"state": "pending"}, 10, at=at)
    assert not healthy(status, 4, at=at)
    for state in ("failed", "stopped", "busy"):
        assert not healthy(status | {"state": state}, 10, at=at)
    for value in (None, "bad", (at + timedelta(seconds=1)).isoformat()):
        assert not healthy(status | {"last_success": value}, 10, at=at)
    assert not healthy({}, 10, at=at)


def test_private_worker_upgrade_preserves_all_existing_secrets(tmp_path):
    original = "APP_WORKER_PASSWORD=" + "a3" * 32 + "\nPOSTGRES_PASSWORD=unchanged\n"
    (tmp_path / "postgres.env").write_text(original)
    prepare_worker(tmp_path)
    initial = (tmp_path / "worker.env").read_bytes()
    assert b"calorie_app_worker" in initial and b"POSTGRES_PASSWORD" not in initial
    assert (tmp_path / "postgres.env").read_text() == original
    prepare_worker(tmp_path)
    assert (tmp_path / "worker.env").read_bytes() == initial
    write_json(tmp_path / "status.json", {"state": "failed"})
    assert read_json(tmp_path / "status.json") == {"state": "failed"}
    assert not (tmp_path / "status.tmp").exists()


def test_invalid_schedule_and_existing_password_are_rejected(monkeypatch, tmp_path):
    for value in ("0", "1001", "secret-should-never-be-printed"):
        monkeypatch.setenv("RETENTION_BATCH", value)
        with pytest.raises(ValueError):
            number("RETENTION_BATCH", 1000, 1, 1000)
    (tmp_path / "postgres.env").write_text("APP_WORKER_PASSWORD=unexpected\n")
    with pytest.raises(ValueError):
        prepare_worker(tmp_path)
    assert not (tmp_path / "worker.env").exists()
