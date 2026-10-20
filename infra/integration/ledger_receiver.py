"""Authenticated durable deletion ledger receiver; deployment needs an independent host."""

import argparse
import asyncio
import hashlib
import hmac
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from calorie_app.modules.identity.ledger_contract import (
    MAX_BATCH_BYTES,
    ZERO,
    FencePin,
    LedgerInvalid,
    Trust,
    authenticated_batch,
    make_ack,
    make_cutoff,
    require,
    verify_event,
)

MAX_HTTP_BYTES = 8 * MAX_BATCH_BYTES + 4096


def unique_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_field")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def verified_batch(trust, envelope):
    events = authenticated_batch(trust, envelope)
    unique_json(envelope["body"])
    first = events[0].get("sequence") if isinstance(events[0], dict) else None
    require(type(first) is int and 1 <= first < 2**63, "invalid_batch_order")
    require(
        first + len(events) - 1 < 2**63
        and all(
            isinstance(event, dict)
            and type(event.get("sequence")) is int
            and event["sequence"] == first + index
            for index, event in enumerate(events)
        ),
        "invalid_batch_order",
    )
    return events


class Receiver:
    """One pinned stream. ACK follows the FULL-synchronous commit, including on replay.

    No pruning or automatic initialization of a missing established database. A new
    store requires explicit init. Rollback of the entire receiver host is outside
    this store's failure model and needs independent off-host checkpoints.
    """

    def __init__(self, database, trust):
        self.database, self.trust = Path(database), trust
        require(self.database.is_file() and not self.database.is_symlink(), "store_missing")
        self.guard = threading.Lock()
        with self.connection() as db:
            db.execute("BEGIN")
            self.validate(db)

    @classmethod
    def initialize(cls, database, trust):
        database = Path(database)
        require(database.parent.is_dir(), "private_parent_required")
        # Exclusive creation prevents silently adopting or replacing an old receiver.
        with database.open("xb"):
            pass
        database.chmod(0o600)
        receiver = object.__new__(cls)
        receiver.database, receiver.trust = database, trust
        receiver.guard = threading.Lock()
        with receiver.connection() as db:
            db.executescript(
                "CREATE TABLE pin(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);"
                "CREATE TABLE events(sequence INTEGER PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE batches(id INTEGER PRIMARY KEY, value TEXT NOT NULL UNIQUE);"
                "CREATE TABLE control(id INTEGER PRIMARY KEY CHECK(id=1), cutoff TEXT);"
            )
            db.execute("INSERT INTO pin VALUES(1,?)", (receiver.pin(),))
            db.execute("INSERT INTO control VALUES(1,NULL)")
        return cls(database, trust)

    def pin(self):
        return encoded(
            self.trust.identity()
            | {
                "format": 1,
                "issuer": self.trust.issuer,
                "source_key_sha256": hashlib.sha256(self.trust.source_key).hexdigest(),
                "ack_key_sha256": hashlib.sha256(self.trust.ack_key).hexdigest(),
            }
        )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            require(db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",), "wal_required")
            db.execute("PRAGMA synchronous=FULL")
            require(db.execute("PRAGMA synchronous").fetchone() == (2,), "full_sync_required")
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    def validate(self, db):
        require(db.execute("PRAGMA quick_check").fetchone() == ("ok",), "store_corrupt")
        require(
            db.execute("SELECT value FROM pin WHERE id=1").fetchone() == (self.pin(),),
            "pin_mismatch",
        )
        sequence, previous = 1, ZERO
        for number, value in db.execute("SELECT sequence,value FROM events ORDER BY sequence"):
            event = unique_json(value)
            require(number == sequence, "persisted_gap")
            verify_event(self.trust, event, sequence, previous)
            sequence, previous = sequence + 1, event["chain_hash"]
        # Check complete authenticated coverage in ingestion order with bounded
        # memory. Keep one <=128-event envelope, never the entire growing stream.
        covered = 0
        for (value,) in db.execute("SELECT value FROM batches ORDER BY id"):
            events = verified_batch(self.trust, unique_json(value))
            require(events[0]["sequence"] <= covered + 1, "persisted_source_gap")
            for event in events:
                require(
                    db.execute(
                        "SELECT value FROM events WHERE sequence=?", (event["sequence"],)
                    ).fetchone()
                    == (encoded(event),),
                    "persisted_source_mismatch",
                )
            covered = max(covered, events[-1]["sequence"])
        require(covered == sequence - 1, "persisted_events_missing")
        row = db.execute("SELECT cutoff FROM control WHERE id=1").fetchone()
        require(row is not None, "control_missing")
        if row[0]:
            from calorie_app.modules.identity.ledger_contract import verify_cutoff

            cutoff = unique_json(row[0])
            pin = FencePin(**{key: cutoff[key] for key in FencePin.__dataclass_fields__})
            verify_cutoff(self.trust, cutoff, pin)
            require(
                cutoff["sequence"] == sequence - 1 and cutoff["chain_hash"] == previous,
                "frozen_head_changed",
            )

    def deliver(self, envelope):
        events = verified_batch(self.trust, envelope)
        with self.guard, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require(
                db.execute("SELECT cutoff FROM control WHERE id=1").fetchone() == (None,),
                "receiver_frozen",
            )
            last = db.execute(
                "SELECT sequence,value FROM events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence, previous = (
                (last[0] + 1, unique_json(last[1])["chain_hash"]) if last else (1, ZERO)
            )
            for event in events:
                number = event.get("sequence")
                value = encoded(event)
                if type(number) is int and number < sequence:
                    require(
                        db.execute(
                            "SELECT value FROM events WHERE sequence=?", (number,)
                        ).fetchone()
                        == (value,),
                        "replay_conflict",
                    )
                    continue
                verify_event(self.trust, event, sequence, previous)
                db.execute("INSERT INTO events VALUES(?,?)", (sequence, value))
                sequence, previous = sequence + 1, event["chain_hash"]
            db.execute("INSERT OR IGNORE INTO batches(value) VALUES(?)", (encoded(envelope),))
        # An exception before or during commit must never produce an ACK.
        return make_ack(self.trust, sequence - 1, previous)

    def freeze(self, fence_pin):
        """Offline trusted controller entry, after actual source/issuer fencing.

        Freezing this receiver serializes with pending delivery; it does not itself
        stop the source. This method never infers fencing from a hash or sequence.
        """
        with self.guard, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.validate(db)
            row = db.execute("SELECT cutoff FROM control WHERE id=1").fetchone()
            last = db.execute(
                "SELECT sequence,value FROM events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            require(last is not None, "anchor_missing")
            cutoff = make_cutoff(
                self.trust,
                make_ack(self.trust, last[0], unique_json(last[1])["chain_hash"]),
                fence_pin,
            )
            require(row[0] is None or row[0] == encoded(cutoff), "different_fence_refused")
            db.execute("UPDATE control SET cutoff=? WHERE id=1", (encoded(cutoff),))
        return cutoff

    def export(self):
        with self.guard, self.connection() as db:
            db.execute("BEGIN")
            self.validate(db)
            return [
                unique_json(row[0]) for row in db.execute("SELECT value FROM batches ORDER BY id")
            ]


def create_app(receiver, bearer):
    require(
        isinstance(bearer, str) and 32 <= len(bearer) <= 256 and bearer.isascii(),
        "strong_bearer_required",
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/batches")
    async def deliver(request: Request):
        header = request.headers.get("authorization", "")
        if not header.isascii() or not hmac.compare_digest(header, "Bearer " + bearer):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if request.headers.get("content-type", "").split(";")[
            0
        ].strip().lower() != "application/json" or request.headers.get("content-encoding"):
            return JSONResponse({"error": "unsupported_encoding"}, status_code=415)
        try:
            length = request.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > MAX_HTTP_BYTES):
                return JSONResponse({"error": "request_too_large"}, status_code=413)
            data = bytearray()
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    data.extend(chunk)
                    if len(data) > MAX_HTTP_BYTES:
                        return JSONResponse({"error": "request_too_large"}, status_code=413)
            envelope = unique_json(bytes(data))
            from starlette.concurrency import run_in_threadpool

            ack = await run_in_threadpool(receiver.deliver, envelope)
            return JSONResponse(ack, headers={"Cache-Control": "no-store"})
        except TimeoutError:
            return JSONResponse({"error": "request_timeout"}, status_code=408)
        except (
            LedgerInvalid,
            ValueError,
            KeyError,
            TypeError,
            UnicodeError,
            OverflowError,
            RecursionError,
        ):
            return JSONResponse({"error": "invalid_ledger_delivery"}, status_code=409)
        except (sqlite3.Error, OSError):
            return JSONResponse({"error": "storage_unavailable"}, status_code=503)

    return app


def configuration(path):
    settings = unique_json(path.read_bytes())
    trust = Trust(
        **settings["identity"],
        source_key=Path(settings["source_key_file"]).read_bytes(),
        ack_key=Path(settings["ack_key_file"]).read_bytes(),
    )
    return settings, trust


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "serve", "export", "freeze"))
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fence-pin", type=Path)
    args = parser.parse_args()
    try:
        settings, trust = configuration(args.settings)
        if args.action == "init":
            Receiver.initialize(settings["database"], trust)
        else:
            receiver = Receiver(settings["database"], trust)
            if args.action == "serve":
                import uvicorn

                token = Path(settings["bearer_file"]).read_text(encoding="ascii").strip()
                uvicorn.run(
                    create_app(receiver, token),
                    host=settings.get("bind", "127.0.0.1"),
                    port=settings.get("port", 18445),
                    ssl_certfile=settings["tls_cert"],
                    ssl_keyfile=settings["tls_key"],
                    access_log=False,
                    log_level="warning",
                    limit_concurrency=16,
                    timeout_keep_alive=5,
                )
            else:
                require(args.output is not None, "new_output_required")
                if args.action == "freeze":
                    require(args.fence_pin is not None, "independent_fence_pin_required")
                    result = receiver.freeze(FencePin(**unique_json(args.fence_pin.read_bytes())))
                else:
                    result = receiver.export()
                with args.output.open("x", encoding="utf-8") as stream:
                    stream.write(encoded(result))
                args.output.chmod(0o600)
        print('{"result":"PASS","off_host_verified":false,"reopen_authorized":false}')
        return 0
    except Exception:
        print('{"result":"FAIL","reopen_authorized":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
