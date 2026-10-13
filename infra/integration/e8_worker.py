"""Run one installed E8 CLI in bounded minute cycles, with private aggregate health."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

TASKS = {
    "motivation": (
        "calorie_app.motivation_worker",
        "--once",
        "--batch",
        "100",
        "--date-batch",
        "256",
    ),
    "lifecycle": ("calorie_app.modules.nemesis.maintenance", "--batch", "100"),
    "finalizer": ("calorie_app.modules.nemesis.finalization", "--batch", "100"),
}
INTERVAL = 60


def utc():
    return datetime.now(UTC).isoformat()


def aggregate(task, payload):
    """Explicit schema; never persist raw output, IDs, exceptions, DSN or private rows."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid result")
    fields = {
        "motivation": ("owners_handled", "dates_processed"),
        "lifecycle": ("transitioned", "responses_pruned", "admissions_pruned"),
        "finalizer": ("processed", "finalized", "backlog"),
    }[task]
    result = {}
    for field in fields:
        value = payload[field]
        if type(value) is not int or value < 0:
            raise ValueError("Invalid aggregate")
        result[field] = value
    if task == "motivation":
        if payload.get("status") != "ok":
            raise ValueError("Unavailable worker")
        backlog = payload["backlog"]
        result["backlog"] = {}
        for key in ("pending_backfill", "pending_materialization"):
            value = backlog[key]
            if type(value) is not int or value < 0:
                raise ValueError("Invalid backlog")
            result["backlog"][key] = value
        oldest = backlog["oldest_matures_at"]
        if oldest is not None:
            oldest = datetime.fromisoformat(oldest).isoformat()
        result["backlog"]["oldest_matures_at"] = oldest
    if task == "finalizer":
        if type(payload.get("ready")) is not bool:
            raise ValueError("Invalid readiness")
        result["ready"] = payload["ready"]
    return result


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def publish(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def healthy(status, *, at=None, timeout=55):
    try:
        age = (
            (at or datetime.now(UTC)) - datetime.fromisoformat(status["last_success"])
        ).total_seconds()
        return (
            status["state"] in {"ok", "pending", "running"} and 0 <= age <= INTERVAL + timeout + 15
        )
    except (KeyError, ValueError, TypeError):
        return False


def run_once(task, state, stop, *, timeout=55):
    path = state / "status.json"
    previous = read(path)
    started = time.monotonic()
    result = {
        "task": task,
        "state": "running",
        "last_attempt": utc(),
        "last_success": previous.get("last_success"),
    }
    publish(path, result)
    child = None
    output = ""
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-m", *TASKS[task]],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            # New process only inherits its service's single minimal LOGIN.
            env=os.environ.copy(),
        )
        while True:
            if stop.is_set() or time.monotonic() - started >= timeout:
                child.terminate()
                try:
                    child.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.communicate()
                result["state"] = "stopped" if stop.is_set() else "timeout"
                break
            try:
                output, _ = child.communicate(timeout=0.2)
                metrics = aggregate(task, json.loads(output))
                if child.returncode == 2 and task == "finalizer" and metrics["ready"] is False:
                    result["state"] = "disabled"
                elif child.returncode != 0 or (task == "finalizer" and not metrics["ready"]):
                    result["state"] = "failed"
                else:
                    pending = (
                        any(
                            metrics["backlog"][k]
                            for k in ("pending_backfill", "pending_materialization")
                        )
                        if task == "motivation"
                        else metrics["backlog"] > 0
                        if task == "finalizer"
                        else any(v >= 100 for v in metrics.values())
                    )
                    result["state"] = "pending" if pending else "ok"
                    result["last_success"] = utc()
                result["metrics"] = metrics
                break
            except subprocess.TimeoutExpired:
                continue
    except Exception:
        result["state"] = "failed"
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["finished_at"] = utc()
    publish(path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("action", choices=("serve", "once", "status", "health"))
    parser.add_argument("--state", type=Path, default=Path("/worker"))
    args = parser.parse_args()
    try:
        timeout = int(os.environ.get("E8_PASS_TIMEOUT_SECONDS", "55"))
        if not 5 <= timeout <= 300:
            raise ValueError("Invalid timeout")
        if args.action in {"status", "health"}:
            status = read(args.state / "status.json")
            if args.action == "status":
                print(json.dumps(status, sort_keys=True))
            return 0 if healthy(status, timeout=timeout) else 1
        args.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        stop = Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        while not stop.is_set():
            started = time.monotonic()
            result = run_once(args.task, args.state, stop, timeout=timeout)
            print(json.dumps(result, sort_keys=True), flush=True)
            if args.action == "once":
                return (
                    0
                    if result["state"] in {"ok", "pending"}
                    else 2
                    if result["state"] == "disabled"
                    else 1
                )
            stop.wait(max(0, INTERVAL - (time.monotonic() - started)))
        return 0
    except Exception:
        print('{"state":"failed","code":"e8_runner_unavailable"}', flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
