"""Owned PG17 -> real TLS receiver -> authenticated SQL ACK, without a real provider."""

import ipaddress
import json
import secrets
import socket
import sqlite3
import ssl
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from calorie_app.modules.identity import deletion
from calorie_app.modules.identity.ledger_contract import verify_ack
from calorie_app.modules.identity.ledger_transport import HTTPSLedgerTransport, export_once
from tests.support.deletion_regression import harness

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra/integration"))
from ledger_receiver import Receiver, create_app

pytestmark = pytest.mark.integration


@contextmanager
def receiver_connection(receiver, folder):
    cert_path, key_path = folder / "tls.pem", folder / "tls.key"
    token_path = folder / "bearer.txt"
    if not cert_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic receiver")])
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        token_path.write_text(secrets.token_urlsafe(32), encoding="ascii")
        key_path.chmod(0o600)
        token_path.chmod(0o600)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(receiver, token_path.read_text(encoding="ascii")),
                ssl_certfile=str(cert_path),
                ssl_keyfile=str(key_path),
                log_level="critical",
                access_log=False,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        transport = None
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            transport = HTTPSLedgerTransport(
                f"https://127.0.0.1:{port}/v1/batches",
                bearer=token_path.read_text(encoding="ascii"),
                ssl_context=ssl.create_default_context(cafile=str(cert_path)),
            )
            yield transport
        finally:
            if transport:
                transport.close()
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


def test_owned_pg_https_lost_ack_restart_and_enforced_effect(database, tmp_path):
    engine, _, _ = database
    source = harness(engine)
    owner, operation, subject = uuid4(), uuid4(), str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,:issuer,:subject)"),
            {"id": owner, "issuer": source.trust.issuer, "subject": subject},
        )
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
        deletion.begin(connection, owner, operation, 1)

    class Provider:
        def __init__(self):
            self.calls = []

        def delete_and_confirm(self, issuer, target):
            self.calls.append((issuer, target))

    provider = Provider()
    sink_path = tmp_path / "receiver.sqlite"
    receiver = Receiver.initialize(sink_path, source.trust)
    with receiver_connection(receiver, tmp_path) as transport:

        class LostACK:
            def deliver(self, envelope):
                transport.deliver(envelope)
                raise TimeoutError("synthetic ACK lost after real durable HTTPS delivery")

        with pytest.raises(TimeoutError):
            export_once(source.exporter, LostACK())
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT ack_sequence FROM app.deletion_ledger_source")) == 0
            )
        with sqlite3.connect(sink_path) as db:
            assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        with pytest.raises(DBAPIError, match="ACK required"):
            deletion.resume(engine, operation, provider)
        assert provider.calls == []

    # A separate TLS server and freshly validated receiver reuse the persisted
    # source/stream/keys/certificate after the first server has fully stopped.
    reopened = Receiver(sink_path, source.trust)
    with receiver_connection(reopened, tmp_path) as transport:
        assert export_once(source.exporter, transport) == 1
        result = deletion.resume(
            engine,
            operation,
            provider,
            delivery=lambda: export_once(source.exporter, transport),
        )
        assert result["ledger_complete"] is True
        assert provider.calls == [(source.trust.issuer, subject)]
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.user_accounts WHERE id=:id"), {"id": owner}
                )
                == 0
            )
            acknowledged = connection.scalar(
                text("SELECT ack_sequence FROM app.deletion_ledger_source")
            )
            final_batch = connection.scalar(text("SELECT app.ledger_batch(1,128)"))
        ack = transport.deliver(final_batch)
        assert verify_ack(source.trust, ack)["sequence"] == acknowledged
        assert acknowledged == 7
        events = json.loads(final_batch["body"])["events"]
        assert [(item["stage"], item["outcome"]) for item in events] == [
            ("anchor", "cutover_unknown_history"),
            ("begin", "intent"),
            ("provider", "intent"),
            ("provider", "confirmed"),
            ("confirm", "confirmed"),
            ("purge", "intent"),
            ("purge", "confirmed"),
        ]
        assert all(item["operation_id"] == str(operation) for item in events[1:])
    assert Receiver(sink_path, source.trust).export()
