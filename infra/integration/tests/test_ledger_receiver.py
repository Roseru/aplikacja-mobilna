import dataclasses
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger_receiver as receiver_module
from ledger_receiver import Receiver, create_app

from calorie_app.modules.identity.ledger_contract import (
    SOURCE_DOMAIN,
    ZERO,
    FencePin,
    LedgerInvalid,
    Trust,
    verify_ack,
    verify_cutoff,
)


def envelope(trust, events):
    body = json.dumps({"version": 1, **trust.identity(), "events": events})
    return {
        "body": body,
        "mac": hmac.digest(trust.source_key, SOURCE_DOMAIN + body.encode(), "sha256").hex(),
    }


def event(trust, number=1, previous=ZERO):
    entry = {
        "version": 1,
        "installation_id": trust.installation_id,
        "stream_id": trust.stream_id,
        "anchor_id": trust.anchor_id,
        "event_id": str(uuid4()),
        "sequence": number,
        "issuer": trust.issuer,
        "operation_id": str(uuid4()) if number > 1 else None,
        "account_id": str(uuid4()) if number > 1 else None,
        "subject": "synthetic-subject" if number > 1 else None,
        "expected_generation": 1 if number > 1 else None,
        "deleting_generation": 2 if number > 1 else None,
        "attempt": None,
        "stage": "begin" if number > 1 else "anchor",
        "outcome": "intent" if number > 1 else "cutover_unknown_history",
    }
    content = json.dumps(entry, ensure_ascii=False)
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    return {
        **{
            key: entry[key]
            for key in ("sequence", "event_id", "operation_id", "stage", "outcome", "attempt")
        },
        "content": content,
        "content_hash": content_hash,
        "previous_hash": previous,
        "chain_hash": hashlib.sha256(
            bytes.fromhex(previous) + bytes.fromhex(content_hash)
        ).hexdigest(),
    }


@pytest.fixture
def prepared(tmp_path):
    trust = Trust(
        *(str(uuid4()) for _ in range(4)),
        "https://issuer.invalid/realms/test",
        os.urandom(32),
        os.urandom(32),
    )
    db = tmp_path / "receiver.sqlite"
    receiver = Receiver.initialize(db, trust)
    anchor = event(trust)
    second = event(trust, 2, anchor["chain_hash"])
    return receiver, trust, anchor, second


def test_restart_lost_response_and_exact_replay(prepared):
    receiver, trust, anchor, second = prepared
    payload = envelope(trust, [anchor, second])
    first = receiver.deliver(payload)
    assert verify_ack(trust, first)["sequence"] == 2
    reopened = Receiver(receiver.database, trust)
    assert reopened.deliver(payload) == first
    assert reopened.export() == [payload]
    with sqlite3.connect(receiver.database) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_missing_or_existing_store_never_initializes_silently(prepared, tmp_path):
    receiver, trust, *_ = prepared
    with pytest.raises(LedgerInvalid, match="store_missing"):
        Receiver(tmp_path / "missing", trust)
    with pytest.raises(FileExistsError):
        Receiver.initialize(receiver.database, trust)


@pytest.mark.parametrize(
    "field",
    ["installation_id", "stream_id", "anchor_id", "receiver_id", "issuer", "source_key", "ack_key"],
)
def test_changed_pin_or_keys_refused(prepared, field):
    receiver, trust, *_ = prepared
    replacement = (
        os.urandom(32)
        if field.endswith("key")
        else ("https://different.invalid" if field == "issuer" else str(uuid4()))
    )
    with pytest.raises(LedgerInvalid, match="pin_mismatch"):
        Receiver(receiver.database, dataclasses.replace(trust, **{field: replacement}))


@pytest.mark.parametrize("damage", ["source_mac", "content", "gap", "fork"])
def test_invalid_batch_cannot_advance(prepared, damage):
    receiver, trust, anchor, second = prepared
    if damage == "content":
        second["content"] += " "
    elif damage == "gap":
        second["sequence"] = 3
    elif damage == "fork":
        second["previous_hash"] = "f" * 64
    batch = envelope(trust, [anchor, second])
    if damage == "source_mac":
        batch["mac"] = "0" * 64
    with pytest.raises(LedgerInvalid):
        receiver.deliver(batch)
    assert receiver.export() == []


def test_conflicting_replay_refused(prepared):
    receiver, trust, anchor, _ = prepared
    receiver.deliver(envelope(trust, [anchor]))
    with pytest.raises(LedgerInvalid, match="replay_conflict"):
        receiver.deliver(envelope(trust, [event(trust)]))
    assert len(receiver.export()) == 1


@pytest.mark.parametrize(
    "damage", ["event", "batch", "missing_event", "missing_batch", "pin", "control"]
)
def test_restart_authenticates_persisted_bytes_and_complete_mapping(prepared, damage):
    receiver, trust, anchor, second = prepared
    receiver.deliver(envelope(trust, [anchor, second]))
    with sqlite3.connect(receiver.database) as db:
        statements = {
            "event": "UPDATE events SET value='{}' WHERE sequence=2",
            "batch": "UPDATE batches SET value='{}'",
            "missing_event": "DELETE FROM events WHERE sequence=2",
            "missing_batch": "DELETE FROM batches",
            "pin": "UPDATE pin SET value='{}'",
            "control": "DELETE FROM control",
        }
        db.execute(statements[damage])
    with pytest.raises((LedgerInvalid, KeyError)):
        Receiver(receiver.database, trust)


def test_concurrent_retries_preserve_one_prefix(prepared):
    receiver, trust, anchor, second = prepared
    payload = envelope(trust, [anchor, second])
    instances = [Receiver(receiver.database, trust) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        acks = list(pool.map(lambda instance: instance.deliver(payload), instances))
    assert all(ack == acks[0] for ack in acks)
    assert len(receiver.export()) == 1


def test_commit_failure_returns_no_ack_and_rolls_back(prepared, monkeypatch):
    receiver, trust, anchor, _ = prepared
    original = sqlite3.connect

    class FailedCommit(sqlite3.Connection):
        def __exit__(self, *args):
            self.rollback()
            raise sqlite3.OperationalError("synthetic disk failure")

    monkeypatch.setattr(
        receiver_module.sqlite3,
        "connect",
        lambda *args, **kw: original(*args, **kw, factory=FailedCommit),
    )
    with pytest.raises(sqlite3.OperationalError):
        receiver.deliver(envelope(trust, [anchor]))
    monkeypatch.setattr(receiver_module.sqlite3, "connect", original)
    assert receiver.export() == []


def test_killed_process_after_commit_can_retry_without_duplication(prepared, tmp_path):
    receiver, trust, anchor, second = prepared
    settings = tmp_path / "synthetic.json"
    settings.write_text(
        json.dumps(
            {
                "database": str(receiver.database),
                "trust": dataclasses.asdict(trust)
                | {"source_key": trust.source_key.hex(), "ack_key": trust.ack_key.hex()},
                "envelope": envelope(trust, [anchor, second]),
            }
        )
    )
    source = """
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[2])
import ledger_receiver as m
from calorie_app.modules.identity.ledger_contract import Trust
d=json.loads(Path(sys.argv[1]).read_text()); t=d['trust']
for k in ('source_key','ack_key'): t[k]=bytes.fromhex(t[k])
r=m.Receiver(d['database'],Trust(**t))
m.make_ack=lambda *args: os._exit(17)
r.deliver(d['envelope'])
"""
    result = subprocess.run(
        [sys.executable, "-c", source, str(settings), str(Path(receiver_module.__file__).parent)],
        capture_output=True,
    )
    assert result.returncode == 17, result.stderr
    reopened = Receiver(receiver.database, trust)
    assert reopened.deliver(envelope(trust, [anchor, second]))["sequence"] == 2
    assert len(reopened.export()) == 1


def test_frozen_cutoff_survives_restart_and_blocks_writes(prepared):
    receiver, trust, anchor, second = prepared
    receiver.deliver(envelope(trust, [anchor]))
    pin = FencePin(
        **trust.identity(),
        fence_id=str(uuid4()),
        fence_sha256=hashlib.sha256(b"synthetic stopped-source evidence").hexdigest(),
        scope="contract-test",
    )
    cutoff = receiver.freeze(pin)
    assert verify_cutoff(trust, cutoff, pin) == cutoff
    reopened = Receiver(receiver.database, trust)
    assert reopened.freeze(pin) == cutoff
    with pytest.raises(LedgerInvalid, match="receiver_frozen"):
        reopened.deliver(envelope(trust, [second]))
    with pytest.raises(LedgerInvalid):
        reopened.freeze(dataclasses.replace(pin, fence_id=str(uuid4())))


def test_http_auth_validation_and_storage_error(prepared, monkeypatch):
    receiver, trust, anchor, _ = prepared
    token = "t" * 48
    client = TestClient(create_app(receiver, token))
    batch = envelope(trust, [anchor])
    assert client.post("/v1/batches", json=batch).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    assert client.get("/openapi.json", headers=headers).status_code == 404
    assert client.post("/v1/batches", content=b"x", headers=headers).status_code == 415
    assert client.post("/v1/batches", json=batch, headers=headers).status_code == 200
    assert (
        client.post(
            "/v1/batches",
            content='{"body":"a","body":"b","mac":"x"}',
            headers=headers | {"Content-Type": "application/json"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/batches",
            json=batch,
            headers=headers | {"Content-Length": str(receiver_module.MAX_HTTP_BYTES + 1)},
        ).status_code
        == 413
    )
    monkeypatch.setattr(
        receiver,
        "deliver",
        lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("private error")),
    )
    result = client.post("/v1/batches", json=batch, headers=headers)
    assert result.status_code == 503 and "private error" not in result.text


def test_real_tls_o2_transport_delivery_and_restart(prepared, tmp_path):
    import ipaddress
    import socket
    import ssl
    import threading
    import time
    from datetime import UTC, datetime, timedelta

    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from calorie_app.modules.identity.ledger_transport import HTTPSLedgerTransport

    receiver, trust, anchor, second = prepared
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic ledger TLS")])
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
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "tls.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    token = "test-token-" + "x" * 48
    payload = envelope(trust, [anchor, second])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(
            create_app(receiver, token),
            log_level="critical",
            access_log=False,
            ssl_certfile=str(cert_path),
            ssl_keyfile=str(key_path),
        )
        server = uvicorn.Server(config)
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
                bearer=token,
                ssl_context=ssl.create_default_context(cafile=str(cert_path)),
            )
            ack = transport.deliver(payload)
            assert verify_ack(trust, ack)["sequence"] == 2
            assert Receiver(receiver.database, trust).deliver(payload) == ack
            assert transport.deliver(payload) == ack
        finally:
            if transport:
                transport.close()
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
