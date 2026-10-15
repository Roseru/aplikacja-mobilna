import hashlib
import json
import ssl
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secret_handoff as handoff  # noqa: E402


@pytest.fixture
def inputs(tmp_path):
    manifest = tmp_path / "source.json"
    key = tmp_path / "source-key.txt"
    raw = dict(
        provider="gemini",
        project_id=handoff.PROJECT,
        environment_id=handoff.ENVIRONMENT,
        model=handoff.MODEL,
        confirmed_at=datetime.now(UTC).isoformat(),
        free_only=True,
        billing_disabled=True,
        development_only=True,
        model_verified=True,
        rpm=15,
        tpm=250000,
        rpd=500,
        quota_windows={},
    )
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    key.write_text("synthetic-test-secret-123456789", encoding="utf-8")
    return manifest, key, raw


@pytest.mark.parametrize("field", ["billing_disabled", "development_only", "model_verified"])
def test_unconfirmed_inputs_never_produce_transfer(inputs, tmp_path, field):
    manifest, key, raw = inputs
    raw[field] = False
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    destination = tmp_path / "transfer"
    with pytest.raises(ValueError, match="incomplete"):
        handoff.prepare(destination, "127.0.0.1", manifest, key)
    assert not (destination / "payload.zip").exists()


def test_verified_https_roundtrip_is_one_shot_and_does_not_activate(inputs, tmp_path):
    manifest, key, raw = inputs
    source = tmp_path / "transfer"
    pin = handoff.prepare(source, "127.0.0.1", manifest, key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(source / "public-ca.pem", source / "server-key.pem")
    with handoff.Transfer(
        ("127.0.0.1", 0), "127.0.0.1", (source / "payload.zip").read_bytes(), context
    ) as server:
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        destination = tmp_path / "received"
        result = handoff.fetch(
            "127.0.0.1", server.server_port, source / "public-ca.pem", pin, destination
        )
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert server.delivered
    assert result == dict(handoff="received_and_validated", deployed=False, google_requests=0)
    assert (destination / "gemini-key.txt").read_bytes() == key.read_bytes()
    assert handoff.validate_files(destination) == raw
    with pytest.raises(FileExistsError):
        handoff.private_directory(destination)


def test_incorrect_certificate_pin_rejected_before_network(inputs, tmp_path):
    manifest, key, _ = inputs
    source = tmp_path / "transfer"
    handoff.prepare(source, "127.0.0.1", manifest, key)
    with pytest.raises(ValueError, match="fingerprint"):
        handoff.fetch("127.0.0.1", 1, source / "public-ca.pem", "0" * 64, tmp_path / "received")
    assert not (tmp_path / "received").exists()
    assert hashlib.sha256((source / "public-ca.pem").read_bytes()).hexdigest() != "0" * 64


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "169.254.1.2", "8.8.8.8"])
def test_external_wildcard_and_link_local_addresses_refused(host):
    with pytest.raises(ValueError):
        handoff.private_ip(host)


def test_wrong_pool_and_duplicate_fields_refused(inputs):
    manifest, key, raw = inputs
    raw["environment_id"] = "new-pool-that-would-reset-the-ledger"
    with pytest.raises(ValueError):
        handoff.validate(json.dumps(raw).encode(), key.read_bytes())
    with pytest.raises(ValueError):
        handoff.validate(b'{"provider":"gemini","provider":"mock"}', key.read_bytes())


def test_exact_peer_https_post_accepts_one_private_payload(inputs, tmp_path):
    manifest, key, _ = inputs
    source = tmp_path / "transfer"
    handoff.prepare(source, "127.0.0.1", manifest, key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(source / "public-ca.pem", source / "server-key.pem")
    with handoff.Transfer(("127.0.0.1", 0), "127.0.0.1", b"", context) as server:
        server.destination = tmp_path / "intake"
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        result = handoff.send(
            source, "127.0.0.1", "127.0.0.1", server.server_port, source / "public-ca.pem"
        )
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert server.delivered
    assert result["handoff"] == "receiver_confirmed"
    assert (server.destination / "gemini-key.txt").read_bytes() == key.read_bytes()


def test_wrong_peer_rejected_before_private_delivery(inputs, tmp_path):
    manifest, key, _ = inputs
    source = tmp_path / "transfer"
    handoff.prepare(source, "127.0.0.1", manifest, key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(source / "public-ca.pem", source / "server-key.pem")
    with handoff.Transfer(("127.0.0.1", 0), "192.168.137.29", b"", context) as server:
        server.destination = tmp_path / "intake"
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        with pytest.raises(OSError):
            handoff.send(
                source, "127.0.0.1", "127.0.0.1", server.server_port, source / "public-ca.pem"
            )
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert not server.delivered
        assert not server.destination.exists()
