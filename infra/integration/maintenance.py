"""Scheduled local backups and recovery of an existing, explicitly owned installation."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup import capture, rehearse, verify_archive
from monitor import console_options, sample, write

SERVICES = (
    "postgres",
    "api",
    "retention",
    "keycloak",
    "motivation",
    "nemesis-lifecycle",
    "nemesis-finalizer",
    "gateway",
)
WRITERS = tuple(name for name in SERVICES if name != "postgres")
OWNER = "calorie-o3-scheduled-backup-v1"


class StartupFailure(RuntimeError):
    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__("Existing installation startup exhausted retries")


def now():
    return datetime.now(UTC).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


@contextmanager
def lock(directory):
    """OS releases this lock even if the scheduler or operating system kills us."""
    path = directory / "operation.lock"
    if path.is_symlink():
        raise ValueError("Unexpected lock symlink")
    with path.open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise BlockingIOError("Installation maintenance is already running") from error
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Installation:
    def __init__(self, settings):
        self.settings = settings
        self.state = Path(settings["state"]).resolve(strict=True)
        self.project = read(self.state / "config.json")["project"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.project):
            raise ValueError("Invalid installation")

    def docker(self, *arguments):
        result = subprocess.run(
            [self.settings["docker"], *arguments],
            capture_output=True,
            text=True,
            timeout=60,
            **console_options(),
        )
        if result.returncode:
            raise RuntimeError("Existing installation operation failed")
        return result.stdout

    def inspect(self, identifier, service):
        info = json.loads(self.docker("inspect", identifier))[0]
        labels = info["Config"]["Labels"]
        if (
            labels.get("com.docker.compose.project") != self.project
            or labels.get("com.docker.compose.service") != service
        ):
            raise ValueError("Container is not the requested installation service")
        return info

    def snapshot(self, *, require_running=True):
        result = {}
        for name in SERVICES:
            info = self.inspect(self.project + "-" + name + "-1", name)
            if info["State"].get("Paused"):
                raise ValueError("Paused services require operator intervention")
            if require_running and not info["State"]["Running"]:
                raise ValueError("Backup requires the complete active installation")
            result[name] = info["Id"]
        return result

    def resume(self, original):
        if set(original) != set(SERVICES):
            raise ValueError("Incomplete recovery journal")
        # Verify every identity before starting anything. Never recreate or build.
        for service, identifier in original.items():
            if not re.fullmatch(r"[0-9a-f]{64}", identifier):
                raise ValueError("Invalid saved container identity")
            self.inspect(identifier, service)
        self.docker("start", original["postgres"])
        self.docker("start", *(original[name] for name in WRITERS if name != "gateway"))
        self.docker("start", original["gateway"])

    def ready(self, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            measurement = sample(self.state, self.settings)
            required = (
                "api",
                "keycloak",
                "postgres",
                "retention",
                "motivation",
                "lifecycle",
                "tls",
            )
            if (
                all(measurement["checks"][key]["state"] == "ok" for key in required)
                and measurement["checks"]["finalizer"]["state"] == "expected_disabled"
            ):
                return measurement
            time.sleep(3)
        raise RuntimeError("Existing installation did not become ready")


def recover(installation, directory):
    journal_path = directory / "transaction.json"
    if not journal_path.exists():
        return False
    journal = read(journal_path)
    if not journal.get("resume_pending"):
        return False
    if journal.get("project") != installation.project:
        raise ValueError("Recovery journal belongs to a different installation")
    installation.resume(journal["containers"])
    installation.ready()
    journal.update(resume_pending=False, resumed_at=now())
    write(journal_path, journal)
    return True


def schedule_slot(moment=None):
    local = (moment or datetime.now().astimezone()).replace(tzinfo=None)
    # Calendar slots match the Task Scheduler triggers, including DST changes.
    shifted = local - timedelta(hours=3)
    return shifted.date().isoformat() + (":03" if shifted.hour < 12 else ":15")


def backup_due(receipt, interval_hours=12):
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(receipt["verified_at"])).total_seconds()
        if receipt["result"] != "PASS" or not 0 <= age < 86400:
            return True
        if "schedule_slot" in receipt:
            return receipt["schedule_slot"] != schedule_slot()
        return age >= interval_hours * 3600  # Older receipts migrate on the next due run.
    except (KeyError, ValueError, TypeError):
        return True


def last_success(receipt):
    if receipt.get("result") == "PASS":
        return {
            key: receipt[key]
            for key in (
                "result",
                "verified_at",
                "archive_integrity",
                "restore_rehearsal",
                "services_resumed",
            )
        }
    return receipt.get("last_good")


def prune(root, keep):
    """Only direct owned successful automatic copies; manual/failed copies stay untouched."""
    if type(keep) is not int or keep < 2:
        raise ValueError("Keep at least two verified backups")
    root = root.resolve(strict=True)
    eligible = []
    for path in root.iterdir():
        if not re.fullmatch(r"auto-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", path.name):
            continue
        if path.is_symlink() or path.is_junction() or not path.is_dir():
            continue
        try:
            if read(path / "automatic.json") != {"owner": OWNER, "result": "PASS"}:
                continue
            verify_archive(path)
            if any(p.is_symlink() or p.is_junction() for p in path.rglob("*")):
                continue
        except (OSError, ValueError, KeyError):
            continue
        eligible.append(path)
    removed = 0
    for path in sorted(eligible, key=lambda p: p.name, reverse=True)[keep:]:
        resolved = path.resolve(strict=True)
        if resolved.parent != root or resolved == root or path.is_junction():
            raise ValueError("Retention target escaped backup root")
        shutil.rmtree(resolved)
        removed += 1
    return removed


def perform_backup(settings, directory, *, due_only=False, installation=None):
    installation = installation or Installation(settings)
    recover(installation, directory)
    receipt_path = directory / "backup-receipt.json"
    if due_only and receipt_path.exists() and not backup_due(read(receipt_path)):
        return {"result": "NOT_DUE"}
    previous = last_success(read(receipt_path)) if receipt_path.exists() else None
    requested = Path(settings["backups"])
    if requested.is_symlink() or requested.is_junction():
        raise ValueError("Backup root must not be redirected")
    root = requested.resolve(strict=True)
    if read(root / "owner.json") != {"owner": OWNER, "project": installation.project}:
        raise ValueError("Explicit private automatic-backup root required")
    disk = shutil.disk_usage(root)
    if disk.free < 2 * 1024**3 or disk.free / disk.total < 0.1:
        raise RuntimeError("Insufficient free space for safe backup")
    original = installation.snapshot()
    name = datetime.now(UTC).strftime("auto-%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    destination = root / name
    journal = {
        "project": installation.project,
        "containers": original,
        "resume_pending": True,
        "started_at": now(),
        "schedule_slot": schedule_slot(),
    }
    write(directory / "transaction.json", journal)
    write(
        receipt_path,
        {"result": "RUNNING", "started_at": journal["started_at"], "last_good": previous},
    )
    try:
        try:
            capture(installation.state, destination)
        finally:
            recover(installation, directory)
        rehearsal = rehearse(destination)
        if rehearsal["result"] != "PASS":
            raise ValueError("Restore rehearsal did not pass")
        verify_archive(destination)
        write(destination / "automatic.json", {"owner": OWNER, "result": "PASS"})
        removed = prune(root, settings.get("keep", 14))
        receipt = {
            "result": "PASS",
            "verified_at": now(),
            "schedule_slot": journal["schedule_slot"],
            "backup": str(destination),
            "archive_integrity": True,
            "restore_rehearsal": True,
            "restore_seconds": rehearsal["offline_rehearsal_seconds"],
            "services_resumed": True,
            "removed": removed,
            "offsite_verified": False,
        }
        write(receipt_path, receipt)
        return receipt
    except BaseException:
        write(
            receipt_path,
            {
                "result": "FAIL",
                "failed_at": now(),
                "resume_pending": read(directory / "transaction.json")["resume_pending"],
                "last_good": previous,
            },
        )
        raise


def _startup_once(settings, directory, installation):
    try:
        installation.docker("info", "--format", "{{.ServerVersion}}")
    except RuntimeError:
        if os.name != "nt":
            raise
        desktop = Path(settings["docker_desktop"]).resolve(strict=True)
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
        subprocess.Popen(
            [str(desktop)],
            startupinfo=startup_info,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                installation.docker("info", "--format", "{{.ServerVersion}}")
                break
            except RuntimeError:
                time.sleep(3)
        else:
            raise RuntimeError("Docker Desktop did not become ready")
    recover(installation, directory)
    original = installation.snapshot(require_running=False)
    installation.resume(original)
    installation.ready()
    return {"existing_services_only": True}


def startup(settings, directory, installation=None):
    installation = installation or Installation(settings)
    for attempt in range(1, 4):
        try:
            result = _startup_once(settings, directory, installation)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            write(
                directory / "startup-receipt.json",
                {
                    "result": "FAIL" if attempt == 3 else "RETRYING",
                    "failed_at": now(),
                    "startup_attempts": attempt,
                },
            )
            if attempt == 3:
                raise StartupFailure(attempt) from error
            time.sleep(60)
        else:
            receipt = {
                "result": "PASS",
                "verified_at": now(),
                "startup_attempts": attempt,
                **result,
            }
            write(directory / "startup-receipt.json", receipt)
            return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "recover", "startup"))
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--due", action="store_true")
    args = parser.parse_args()
    settings = read(args.settings)
    directory = args.settings.resolve(strict=True).parent
    os.environ["PATH"] = str(Path(settings["docker"]).parent) + os.pathsep + os.environ["PATH"]
    try:
        with lock(directory):
            if args.action == "backup":
                result = perform_backup(settings, directory, due_only=args.due)
            elif args.action == "startup":
                result = startup(settings, directory)
            else:
                result = {"recovered": recover(Installation(settings), directory)}
        print(json.dumps({k: v for k, v in result.items() if k != "backup"}))
        return 0
    except BlockingIOError:
        return 0  # Another backup/startup/recovery owns the installation.
    except Exception as error:
        (directory / "operation-private.log").write_text(traceback.format_exc(), encoding="utf-8")
        if args.action == "backup":
            path = directory / "backup-receipt.json"
            try:
                previous = last_success(read(path))
            except (OSError, ValueError, KeyError, TypeError):
                previous = None
            write(path, {"result": "FAIL", "failed_at": now(), "last_good": previous})
        elif args.action == "startup":
            receipt = {"result": "FAIL", "failed_at": now()}
            if isinstance(error, StartupFailure):
                receipt["startup_attempts"] = error.attempts
            write(directory / "startup-receipt.json", receipt)
        return 1  # Exceptions may contain private paths/credentials; never print them.


if __name__ == "__main__":
    raise SystemExit(main())
