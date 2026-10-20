"""Durable isolated contract receiver. No production service or scheduler."""

import json
import sqlite3
from pathlib import Path

from calorie_app.modules.identity.ledger_contract import (
    ZERO,
    authenticated_batch,
    make_ack,
    require,
    verify_event,
)


class ContractSink:
    """The two keys/identity are pinned by the caller, never accepted from a batch.

    SQLite models the independent test receiver only; source tests always use PG17.
    A fresh instance reopens and validates the persisted stream before serving ACK.
    """

    def __init__(self, path: Path, trust):
        self.path, self.trust = path, trust
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY, content TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS envelopes(id INTEGER PRIMARY KEY, "
            "body TEXT NOT NULL UNIQUE)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS pin(id INTEGER PRIMARY KEY "
            "CHECK(id=1), identity TEXT NOT NULL)"
        )
        identity = json.dumps(trust.identity() | {"issuer": trust.issuer}, sort_keys=True)
        self.connection.execute("INSERT OR IGNORE INTO pin VALUES(1,?)", (identity,))
        require(
            self.connection.execute("SELECT identity FROM pin").fetchone()[0] == identity,
            "sink_pin_mismatch",
        )
        self.connection.commit()
        authenticated = {}
        for (body,) in self.connection.execute("SELECT body FROM envelopes ORDER BY id"):
            for event in authenticated_batch(trust, json.loads(body)):
                number = event["sequence"]
                require(
                    number not in authenticated or authenticated[number] == event,
                    "sink_persisted_fork",
                )
                authenticated[number] = event
        sequence, previous = 1, ZERO
        for (content,) in self.connection.execute("SELECT content FROM events ORDER BY sequence"):
            event = json.loads(content)
            require(authenticated.get(sequence) == event, "sink_persisted_source_missing")
            verify_event(trust, event, sequence, previous)
            sequence, previous = sequence + 1, event["chain_hash"]

    def close(self):
        self.connection.close()

    def deliver(self, envelope):
        events = authenticated_batch(self.trust, envelope)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            last = self.connection.execute(
                "SELECT sequence, content FROM events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence, previous = (
                (last[0] + 1, json.loads(last[1])["chain_hash"]) if last else (1, ZERO)
            )
            for event in events:
                number = event.get("sequence")
                encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
                if type(number) is int and number < sequence:
                    existing = self.connection.execute(
                        "SELECT content FROM events WHERE sequence=?", (number,)
                    ).fetchone()
                    require(existing is not None and existing[0] == encoded, "sink_replay_conflict")
                    continue
                verify_event(self.trust, event, sequence, previous)
                self.connection.execute("INSERT INTO events VALUES(?,?)", (sequence, encoded))
                sequence, previous = sequence + 1, event["chain_hash"]
            self.connection.execute(
                "INSERT OR IGNORE INTO envelopes(body) VALUES(?)", (json.dumps(envelope),)
            )
        # ACK is generated only after the independent durable commit.
        return make_ack(self.trust, sequence - 1, previous)

    def envelopes(self):
        return [
            json.loads(row[0])
            for row in self.connection.execute("SELECT body FROM envelopes ORDER BY id")
        ]
