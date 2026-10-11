"""Bounded operational scheduling of O2 retention; no new deletion rules."""

import argparse
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from calorie_app.core.config import Settings
from calorie_app.health import EXPECTED_REVISION
from calorie_app.modules.sync.retention import prune

LOCK_ID = 706303013  # One session lock per database, shared by all copies of this runner.


def now():
    return datetime.now(UTC).isoformat()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def number(name, default, minimum, maximum):
    value = int(os.environ.get(name, default))
    if not minimum <= value <= maximum:
        raise ValueError("Invalid worker limit")
    return value


class Worker:
    def __init__(self, state, settings=None, *, batch=1000, owners=1000, seconds=120):
        if not 1 <= batch <= 1000 or not 1 <= owners <= 10000 or not 1 <= seconds <= 300:
            raise ValueError("Invalid bounded pass limits")
        self.state = Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.batch, self.owners, self.seconds = batch, owners, seconds
        settings = settings or Settings()
        # A fresh physical connection per pass: session locks never return to a pool.
        self.engine = create_engine(
            settings.database_url.get_secret_value(),
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={
                "connect_timeout": 2,
                "options": "-c statement_timeout=2000 -c lock_timeout=1000",
            },
        )

    def run(self, stop=None):
        stop = stop or Event()
        started = time.monotonic()
        previous = read_json(self.state / "status.json")
        progress = read_json(self.state / "progress.json")
        sweep_pending = bool(progress.get("sweep_pending", False))
        cursor = progress.get("cursor")
        cursor = UUID(cursor) if cursor else UUID(int=0)
        result = {
            "state": "running",
            "last_attempt": now(),
            "last_success": previous.get("last_success"),
            "last_full_sweep": previous.get("last_full_sweep"),
            "owners": 0,
            "skipped": 0,
            "errors": 0,
            "removed": {},
            "pending": False,
        }
        acquired = False
        try:
            with self.engine.connect() as connection:
                role = connection.scalar(text("SELECT current_user"))
                revision = connection.scalar(text("SELECT version_num FROM app.alembic_version"))
                if role != "calorie_app_worker" or revision != EXPECTED_REVISION:
                    raise ValueError("Worker role or schema mismatch")
                acquired = connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}
                )
                connection.commit()
                if not acquired:
                    return {"state": "busy"}  # Never overwrite the lock owner's status.
                write_json(self.state / "status.json", result)
                while not stop.is_set() and time.monotonic() - started < self.seconds:
                    remaining = self.owners - result["owners"]
                    if remaining <= 0:
                        more = connection.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM app.user_accounts "
                                "WHERE state='active' AND id>:cursor)"
                            ),
                            {"cursor": cursor},
                        )
                        connection.commit()
                        if more:
                            result["pending"] = True
                        else:
                            cursor = UUID(int=0)
                            result["pending"] = sweep_pending
                            result["last_full_sweep"] = now()
                        break
                    page = list(
                        connection.scalars(
                            text(
                                "SELECT id FROM app.user_accounts WHERE state='active' "
                                "AND id>:cursor ORDER BY id LIMIT :limit"
                            ),
                            {"cursor": cursor, "limit": min(100, remaining)},
                        )
                    )
                    connection.commit()
                    if not page:
                        cursor = UUID(int=0)
                        result["pending"] = sweep_pending
                        result["last_full_sweep"] = now()
                        break
                    for owner in page:
                        if stop.is_set() or time.monotonic() - started >= self.seconds:
                            result["pending"] = True
                            break
                        try:
                            # Same physical connection as the session lock; no reconnect mid-pass.
                            with Session(connection) as session, session.begin():
                                active = session.scalar(
                                    text(
                                        "SELECT id FROM app.user_accounts "
                                        "WHERE id=:owner AND state='active' FOR UPDATE"
                                    ),
                                    {"owner": owner},
                                )
                                if active is None:
                                    result["skipped"] += 1
                                    counts = {}
                                else:
                                    counts = prune(session, owner, self.batch)
                            for key, value in counts.items():
                                result["removed"][key] = result["removed"].get(key, 0) + value
                            result["pending"] |= any(v >= self.batch for v in counts.values())
                            sweep_pending |= any(v >= self.batch for v in counts.values())
                        except DBAPIError as error:
                            if error.connection_invalidated:
                                raise  # Lost session lock: abort, never reconnect while pruning.
                            result["errors"] += 1
                            result["pending"] = True
                            sweep_pending = True
                        cursor = owner  # Fairness: one bounded batch per owner per sweep.
                        result["owners"] += 1
                    if result["pending"] and (
                        stop.is_set() or time.monotonic() - started >= self.seconds
                    ):
                        break
                else:
                    result["pending"] = True
                write_json(
                    self.state / "progress.json",
                    {
                        "cursor": str(cursor),
                        "sweep_pending": sweep_pending if cursor.int else False,
                    },
                )
                # Publish completion while still owning the physical session lock.
                return self.finish(result, started, stop)
        except Exception:
            result["state"] = "failed"
            result["errors"] += 1
            result["pending"] = True
        finally:
            self.engine.dispose()
        return self.finish(result, started, stop)

    def finish(self, result, started, stop):
        result["state"] = "failed" if result["errors"] else "pending" if result["pending"] else "ok"
        if stop.is_set():
            result["state"] = "stopped"
        elif not result["errors"]:
            result["last_success"] = now()  # Successful bounded pass, not a zero-backlog claim.
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["finished_at"] = now()
        write_json(self.state / "status.json", result)
        return result


def healthy(status, maximum_age, *, at=None):
    try:
        age = (
            (at or datetime.now(UTC)) - datetime.fromisoformat(status["last_success"])
        ).total_seconds()
        return status["state"] in {"ok", "pending", "running"} and 0 <= age <= maximum_age
    except (KeyError, ValueError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("serve", "once", "health", "status"))
    parser.add_argument("--state", type=Path, default=Path("/worker"))
    args = parser.parse_args()
    try:
        interval = number("RETENTION_INTERVAL_SECONDS", 3600, 5, 86400)
        retry = number("RETENTION_RETRY_SECONDS", 60, 1, 3600)
        maximum_age = interval + 2 * number("RETENTION_PASS_SECONDS", 120, 1, 300) + retry
        if args.action in {"status", "health"}:
            status = read_json(args.state / "status.json")
            if args.action == "status":
                print(json.dumps(status, sort_keys=True))
            return 0 if healthy(status, maximum_age) else 1
        stop = Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        worker = Worker(
            args.state,
            batch=number("RETENTION_BATCH", 1000, 1, 1000),
            owners=number("RETENTION_MAX_OWNERS", 1000, 1, 10000),
            seconds=number("RETENTION_PASS_SECONDS", 120, 1, 300),
        )
        while not stop.is_set():
            result = worker.run(stop)
            print(json.dumps(result, sort_keys=True), flush=True)
            if args.action == "once":
                return 0 if result["state"] in {"ok", "pending"} else 1
            stop.wait(interval if result["state"] == "ok" else retry)
        return 0
    except Exception:
        print('{"state":"failed","error":"worker configuration or state unavailable"}', flush=True)
        return 1  # Never print raw exceptions/DSN/UUID/payloads.


if __name__ == "__main__":
    sys.exit(main())
