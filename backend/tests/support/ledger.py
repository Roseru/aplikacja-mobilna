"""Explicit test-only setup and delivery for historical graph regressions."""

import secrets
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from calorie_app.modules.identity.ledger_contract import FencePin, Trust, digest
from calorie_app.modules.identity.ledger_transport import export_once
from tests.support.ledger_sink import ContractSink


class LedgerHarness:
    def __init__(self, engine, folder: Path, issuer="https://ledger.test/realms/owned"):
        self.engine = engine
        self.source_key, self.ack_key = secrets.token_bytes(32), secrets.token_bytes(32)
        self.receiver = uuid4()
        with engine.begin() as connection:
            existing = (
                connection.execute(text("SELECT * FROM app.deletion_ledger_source"))
                .mappings()
                .one()
            )
            if existing["source_key"] is None:
                connection.execute(
                    text("SELECT app.ledger_configure(:issuer,:receiver,:source,:ack)"),
                    {
                        "issuer": issuer,
                        "receiver": self.receiver,
                        "source": self.source_key,
                        "ack": self.ack_key,
                    },
                )
            existing = (
                connection.execute(text("SELECT * FROM app.deletion_ledger_source"))
                .mappings()
                .one()
            )
        self.trust = Trust(
            *(
                str(existing[k])
                for k in ("installation_id", "stream_id", "anchor_id", "receiver_id")
            ),
            existing["issuer"],
            bytes(existing["source_key"]),
            bytes(existing["ack_key"]),
        )
        self.sink = ContractSink(folder / "sink.sqlite", self.trust)
        self.exporter = create_engine(engine.url, hide_parameters=True)
        from sqlalchemy import event

        @event.listens_for(self.exporter, "connect")
        def role(connection, record):
            with connection.cursor() as cursor:
                cursor.execute("SET ROLE calorie_app_deletion_exporter")
            connection.commit()

    def deliver(self):
        return export_once(self.exporter, self.sink)

    def close(self):
        self.sink.close()
        self.exporter.dispose()


def contract_fence_pin(trust):
    """Owned test observer only; no claim about production process fencing."""
    return FencePin(
        **trust.identity(),
        fence_id=str(uuid4()),
        fence_sha256=digest(b"owned isolated test: all synchronous writes finished"),
        scope="contract-test",
    )
