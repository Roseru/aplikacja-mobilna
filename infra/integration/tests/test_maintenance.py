import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maintenance  # noqa: E402
from backup import ARCHIVES, digest  # noqa: E402
from monitor import operation_reading  # noqa: E402


class Installation:
    project = "owned-fixture"
    state = Path("unused")

    def __init__(self):
        self.calls = []
        self.original = {name: str(index) * 64 for index, name in enumerate(maintenance.SERVICES)}

    def snapshot(self, **_):
        return self.original

    def resume(self, original):
        assert original == self.original
        self.calls.append("resumed")

    def ready(self):
        self.calls.append("ready")


@pytest.fixture
def environment(tmp_path):
    directory = tmp_path / "operations"
    root = tmp_path / "copies"
    directory.mkdir()
    root.mkdir()
    installation = Installation()
    (root / "owner.json").write_text(
        json.dumps({"owner": maintenance.OWNER, "project": installation.project})
    )
    return {"backups": str(root), "keep": 2}, directory, installation


def archive(path):
    path.mkdir()
    files = {}
    for name in ARCHIVES:
        target = path / name
        target.write_bytes(b"fixture")
        files[name] = {"size": 7, "sha256": digest(target)}
    manifest = {
        "format": 1,
        "writers_stopped": True,
        "source_epoch": "09bbd26b-13a2-412a-8445-1ee7b5ae514c",
        "captured_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    (path / "manifest.json").write_text(json.dumps(manifest))


def test_capture_failure_resumes_original_services_and_does_not_certify_backup(
    environment, monkeypatch
):
    settings, directory, installation = environment

    def fail(*_):
        raise RuntimeError("private canary is not included in receipt")

    monkeypatch.setattr(maintenance, "capture", fail)
    with pytest.raises(RuntimeError):
        maintenance.perform_backup(settings, directory, installation=installation)
    assert installation.calls == ["resumed", "ready"]
    receipt = (directory / "backup-receipt.json").read_text()
    assert json.loads(receipt)["result"] == "FAIL"
    assert "canary" not in receipt
    assert not maintenance.read(directory / "transaction.json")["resume_pending"]


def test_failed_resume_leaves_recoverable_journal(environment, monkeypatch):
    settings, directory, installation = environment
    monkeypatch.setattr(maintenance, "capture", lambda *_: None)
    original_resume = installation.resume
    installation.resume = lambda *_: (_ for _ in ()).throw(RuntimeError("stopped"))
    with pytest.raises(RuntimeError):
        maintenance.perform_backup(settings, directory, installation=installation)
    assert maintenance.read(directory / "transaction.json")["resume_pending"]
    installation.resume = original_resume
    assert maintenance.recover(installation, directory)
    assert not maintenance.recover(installation, directory)


def test_restore_failure_never_certifies_copy_and_services_are_already_resumed(
    environment, monkeypatch
):
    settings, directory, installation = environment
    monkeypatch.setattr(maintenance, "capture", lambda _state, dest: archive(dest))

    def fail(_):
        assert installation.calls == ["resumed", "ready"]
        raise RuntimeError("invalid restore")

    monkeypatch.setattr(maintenance, "rehearse", fail)
    with pytest.raises(RuntimeError):
        maintenance.perform_backup(settings, directory, installation=installation)
    assert maintenance.read(directory / "backup-receipt.json")["result"] == "FAIL"
    assert not list(Path(settings["backups"]).glob("*/automatic.json"))


def test_success_requires_archive_restore_and_resume(environment, monkeypatch):
    settings, directory, installation = environment
    monkeypatch.setattr(maintenance, "capture", lambda _state, dest: archive(dest))
    monkeypatch.setattr(
        maintenance, "rehearse", lambda _: {"result": "PASS", "offline_rehearsal_seconds": 1.25}
    )
    receipt = maintenance.perform_backup(settings, directory, installation=installation)
    assert receipt["result"] == "PASS"
    assert receipt["offsite_verified"] is False
    assert operation_reading(directory / "backup-receipt.json", backup=True) == {"state": "ok"}
    assert maintenance.perform_backup(
        settings, directory, due_only=True, installation=installation
    ) == {"result": "NOT_DUE"}
    assert installation.calls == ["resumed", "ready"]


def test_retention_only_removes_owned_verified_copies(tmp_path):
    manual = tmp_path / "manual-backup"
    manual.mkdir()
    incomplete = tmp_path / "auto-20261001T030000Z-1234abcd"
    incomplete.mkdir()
    for day in range(2, 6):
        path = tmp_path / f"auto-2026100{day}T030000Z-1234abcd"
        archive(path)
        (path / "automatic.json").write_text(
            json.dumps({"owner": maintenance.OWNER, "result": "PASS"})
        )
    assert maintenance.prune(tmp_path, 2) == 2
    assert manual.exists() and incomplete.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "auto-20261001T030000Z-1234abcd",
        "auto-20261004T030000Z-1234abcd",
        "auto-20261005T030000Z-1234abcd",
        "manual-backup",
    ]


def test_wrong_project_cannot_recover_services(environment):
    _, directory, installation = environment
    maintenance.write(
        directory / "transaction.json", {"resume_pending": True, "project": "another"}
    )
    with pytest.raises(ValueError, match="different installation"):
        maintenance.recover(installation, directory)
    assert installation.calls == []


@pytest.mark.parametrize(
    "hours,result,expected",
    [(1, "PASS", False), (12, "PASS", True), (-1, "PASS", True), (1, "FAIL", True)],
)
def test_backup_due_does_not_trust_future_or_failed_receipts(hours, result, expected):
    receipt = {
        "result": result,
        "verified_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat(),
    }
    assert maintenance.backup_due(receipt) is expected


def test_monitor_rejects_stale_partial_and_missing_local_receipts(tmp_path):
    path = tmp_path / "receipt.json"
    assert operation_reading(path, backup=True)["state"] == "failed"
    receipt = {
        "result": "PASS",
        "verified_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        "archive_integrity": True,
        "restore_rehearsal": True,
        "services_resumed": True,
    }
    path.write_text(json.dumps(receipt))
    assert operation_reading(path, backup=True)["state"] == "failed"
    receipt["verified_at"] = datetime.now(UTC).isoformat()
    receipt["restore_rehearsal"] = False
    path.write_text(json.dumps(receipt))
    assert operation_reading(path, backup=True)["state"] == "failed"


def test_lock_excludes_other_process_and_recovers_after_forced_exit(tmp_path):
    # Real OS file lock, rather than a mocked success path.
    code = (
        "import os,sys,time; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
        "from maintenance import lock; "
        "ctx=lock(Path(sys.argv[2])); ctx.__enter__(); "
        "print(os.getpid(),flush=True); time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(Path(maintenance.__file__).parent), str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    owner_pid = int(process.stdout.readline().strip())
    try:
        with pytest.raises(BlockingIOError), maintenance.lock(tmp_path):
            pytest.fail("Second owner acquired lock")
    finally:
        # Windows venv executables may be redirector parents. Kill the lock owner.
        os.kill(owner_pid, signal.SIGTERM)
        process.wait(timeout=5)
        process.stdout.close()
    with maintenance.lock(tmp_path):
        pass
