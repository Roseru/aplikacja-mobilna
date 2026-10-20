"""Bounded outbox delivery. Receiver authentication is verified again inside SQL."""

import time
from typing import Protocol

import httpx
from sqlalchemy import text

from calorie_app.modules.identity.ledger_contract import MAX_BATCH_BYTES


class LedgerTransport(Protocol):
    def deliver(self, envelope: dict) -> dict: ...


class HTTPSLedgerTransport:
    def __init__(self, url, *, bearer, ssl_context):
        if not url.startswith("https://") or not bearer:
            raise ValueError("configured authenticated HTTPS transport required")
        self.url = url
        self.client = httpx.Client(
            verify=ssl_context,
            timeout=10,
            trust_env=False,
            follow_redirects=False,
            headers={"Authorization": "Bearer " + bearer},
        )

    def deliver(self, envelope):
        with self.client.stream("POST", self.url, json=envelope) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_BATCH_BYTES:
                    raise ValueError("ledger ACK response too large")
        import json

        return json.loads(data)

    def close(self):
        self.client.close()


def export_once(engine, transport: LedgerTransport, *, max_batches=8, batch_size=64):
    if not 1 <= max_batches <= 16 or not 1 <= batch_size <= 128:
        raise ValueError("bounded delivery required")
    delivered = 0
    for _ in range(max_batches):
        with engine.begin() as connection:
            start = connection.scalar(text("SELECT app.ledger_export_position()"))
            envelope = connection.scalar(
                text("SELECT app.ledger_batch(:start,:limit)"),
                {"start": start, "limit": batch_size},
            )
        # Empty batch carries no coverage. No network inside a DB transaction.
        import json

        if not json.loads(envelope["body"])["events"]:
            break
        for attempt in range(3):
            try:
                ack = transport.deliver(envelope)
                break
            except (TimeoutError, ConnectionError, httpx.TransportError):
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
            except httpx.HTTPStatusError as error:
                if error.response.status_code < 500 or attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
        required = {
            "domain",
            "installation_id",
            "stream_id",
            "anchor_id",
            "receiver_id",
            "sequence",
            "chain_hash",
            "mac",
        }
        if (
            not isinstance(ack, dict)
            or set(ack) != required
            or ack["domain"] != "deletion-ledger-ack-v1"
        ):
            raise ValueError("invalid ledger ACK")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT app.ledger_ack(:installation_id,:stream_id,:anchor_id,"
                    ":receiver_id,:sequence,:chain_hash,:mac)"
                ),
                {k: v for k, v in ack.items() if k != "domain"},
            )
        delivered += 1
    return delivered
