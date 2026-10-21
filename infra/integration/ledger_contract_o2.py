"""Owned contract-only bridge for the existing Compose recovery rehearsal.

No production receiver, scheduler or account is created. Keys and synthetic
identities stay in the fresh rehearsal's private directory outside Git.
"""

import json
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid4

from psycopg import sql

from calorie_app.modules.identity.ledger_contract import (
    FencePin,
    Trust,
    digest,
    make_cutoff,
)


def literal(value):
    return sql.Literal(value).as_string()


class OwnedContractLedger:
    def __init__(self, stack, issuer, execute_sql):
        self.stack, self.sql = stack, execute_sql
        keyfile = stack.state / "ledger-contract-keys.json"
        if not keyfile.exists():
            source_key, ack_key = secrets.token_bytes(32), secrets.token_bytes(32)
            receiver = uuid4()
            self.sql(
                stack,
                "calorie_app",
                "SET log_statement='none'; SET log_min_error_statement='panic'; "
                "SET log_parameter_max_length=0; SET log_parameter_max_length_on_error=0; "
                f"SELECT app.ledger_configure({literal(issuer)},'{receiver}',"
                f"decode('{source_key.hex()}','hex'),decode('{ack_key.hex()}','hex'));",
            )
            pin = json.loads(
                self.sql(
                    stack,
                    "calorie_app",
                    "SELECT json_build_object("
                    "'installation_id',installation_id,'stream_id',stream_id,"
                    "'anchor_id',anchor_id) "
                    "FROM app.deletion_ledger_source;",
                )
            )
            raw = pin | {
                "receiver_id": str(receiver),
                "issuer": issuer,
                "source_key": source_key.hex(),
                "ack_key": ack_key.hex(),
            }
            from backup import private_write

            private_write(keyfile, json.dumps(raw))
        self.raw = json.loads(keyfile.read_text(encoding="utf-8"))
        self.trust = Trust(
            **(self.raw | {k: bytes.fromhex(self.raw[k]) for k in ("source_key", "ack_key")})
        )
        # The controlled receiver is explicitly a test artifact, never an installed service.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
        from tests.support.ledger_sink import ContractSink

        self.sink = ContractSink(stack.state / "ledger-contract-sink.sqlite", self.trust)

    def close(self):
        self.sink.close()

    def deliver(self):
        for _ in range(16):
            start = int(
                self.sql(
                    self.stack,
                    "calorie_app",
                    "SET ROLE calorie_app_deletion_exporter; SELECT app.ledger_export_position();",
                )
            )
            envelope = json.loads(
                self.sql(
                    self.stack,
                    "calorie_app",
                    f"SET ROLE calorie_app_deletion_exporter; SELECT app.ledger_batch({start},64);",
                )
            )
            if not json.loads(envelope["body"])["events"]:
                return
            ack = self.sink.deliver(envelope)
            self.ack(ack)
        raise RuntimeError("Bounded contract delivery exhausted")

    def ack(self, ack):
        ids = [
            str(UUID(ack[k])) for k in ("installation_id", "stream_id", "anchor_id", "receiver_id")
        ]
        self.sql(
            self.stack,
            "calorie_app",
            "SET ROLE calorie_app_deletion_exporter; SELECT app.ledger_ack("
            + ",".join(literal(v) for v in ids)
            + f",{int(ack['sequence'])},{literal(ack['chain_hash'])},{literal(ack['mac'])});",
        )

    def checkpoint(self):
        self.deliver()
        envelopes, start = [], 1
        while True:
            envelope = json.loads(
                self.sql(
                    self.stack,
                    "calorie_app",
                    "SET ROLE calorie_app_deletion_exporter; "
                    f"SELECT app.ledger_batch({start},128);",
                )
            )
            events = json.loads(envelope["body"])["events"]
            if not events:
                break
            envelopes.append(envelope)
            start = events[-1]["sequence"] + 1
        if not envelopes:
            raise RuntimeError("Missing contract anchor")
        ack = self.sink.deliver(envelopes[-1])
        return {"envelopes": envelopes, "ack": ack}

    def cutoff_checkpoint(self):
        checkpoint = self.checkpoint()
        # Independent in-memory observer of this synchronous, owned rehearsal.
        # Never reconstructed from the received envelope or a production backup.
        fence_pin = FencePin(
            **self.trust.identity(),
            fence_id=str(uuid4()),
            fence_sha256=digest(
                b"owned Compose rehearsal: synchronous deletion finished; no other producers"
            ),
            scope="contract-test",
        )
        checkpoint["cutoff"] = make_cutoff(self.trust, checkpoint["ack"], fence_pin)
        return checkpoint, fence_pin

    def reconcile(self, backup_point, cutoff, *, fence_pin):
        script = """import json,os,sys
from sqlalchemy import create_engine
from calorie_app.modules.identity.ledger_contract import FencePin, Trust, digest, make_cutoff
from calorie_app.modules.identity.ledger_restore import reconcile_restore
p=json.load(sys.stdin)
t=p['trust'];t.update({k:bytes.fromhex(t[k]) for k in ('source_key','ack_key')})
e=create_engine(os.environ['DATABASE_URL'],hide_parameters=True)
try:
 r=reconcile_restore(e,Trust(**t),p['envelopes'],backup_point=p['backup_point'],cutoff=p['cutoff'],fence_pin=FencePin(**p['fence_pin']))
 print(json.dumps({'blocked':len(r['targets']),'reopen_authorized':r['reopen_authorized']}))
finally:e.dispose()
"""
        payload = {
            "trust": self.raw,
            "envelopes": cutoff["envelopes"],
            "backup_point": backup_point["ack"],
            "cutoff": cutoff["cutoff"],
            "fence_pin": fence_pin.fields(),
        }
        output = self.stack.compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "migrate",
            ".venv/bin/python",
            "-c",
            script,
            input_text=json.dumps(payload),
        )
        result = json.loads(output)
        if result["reopen_authorized"] or result["blocked"] < 1:
            raise RuntimeError("Restore target was not durably blocked")
        return result
