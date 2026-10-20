"""One-shot private HTTPS transfer to O3; no Google requests or service activation."""

import argparse
import hashlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import time
import zipfile
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from backup import private_directory
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import SecretStr
from run import ROOT

from calorie_app.modules.ai.configuration import configuration

ENVIRONMENT = "calorie-dev-e7-e9"
PROJECT = "181003336626"
MODEL = "gemini-3.5-flash-lite"
LIMIT = 32768
PATH = "/gemini-dev.zip"


def private_path(path):
    path = path.resolve()
    if ROOT.resolve() in (path, *path.parents) or any(
        part.lower().startswith("onedrive") for part in path.parts
    ):
        raise ValueError("Use private storage outside the checkout and OneDrive")
    return path


def private_ip(value):
    address = ipaddress.IPv4Address(value)
    if not any(
        address in ipaddress.ip_network(n)
        for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ):
        raise ValueError("Expected one private LAN address")
    return str(address)


def validate(manifest, key):
    if len(manifest) > 16384 or not re.fullmatch(rb"[A-Za-z0-9_-]{20,256}", key):
        raise ValueError("Invalid private inputs")
    # The real backend parser validates duplicate fields, booleans, dates and limits.
    from calorie_app.modules.ai.result import parse_bounded_json

    raw = parse_bounded_json(manifest, max_bytes=16384)
    required = (PROJECT, ENVIRONMENT, MODEL)
    if tuple(raw.get(k) for k in ("project_id", "environment_id", "model")) != required:
        raise ValueError("Unexpected shared pool")
    if tuple(raw.get(k) for k in ("rpm", "tpm", "rpd")) != (15, 250000, 500):
        raise ValueError("Limits differ from the dated O1 handoff")
    return raw


def validate_files(directory):
    if (directory / "confirmation.json").stat().st_size > 16384 or (
        directory / "gemini-key.txt"
    ).stat().st_size > 258:
        raise ValueError("Private files exceed bounds")
    manifest = (directory / "confirmation.json").read_bytes()
    key = (directory / "gemini-key.txt").read_bytes().strip()
    raw = validate(manifest, key)
    # Pure configuration acceptance: no ambient .env, database, HTTP or worker.
    settings = SimpleNamespace(
        environment="development",
        ai_provider="gemini",
        ai_project_id=PROJECT,
        ai_environment_id=ENVIRONMENT,
        ai_model=MODEL,
        ai_live_confirmation=directory / "confirmation.json",
        gemini_api_key=SecretStr(key.decode()),
    )
    if configuration(settings).reason is not None:
        raise ValueError("Backend live confirmation is incomplete")
    return raw


def prepare(directory, host, manifest, key):
    directory = private_path(directory)
    private_directory(directory)
    try:
        source_manifest = private_path(manifest).read_bytes()
        source_key = private_path(key).read_bytes().strip()
        validate(source_manifest, source_key)
        (directory / "confirmation.json").write_bytes(source_manifest)
        (directory / "gemini-key.txt").write_bytes(source_key)
        validate_files(directory)
        with zipfile.ZipFile(directory / "payload.zip", "x") as archive:
            archive.write(directory / "confirmation.json", "confirmation.json")
            archive.write(directory / "gemini-key.txt", "gemini-key.txt")
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(signing_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=24))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(host))]),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(signing_key, hashes.SHA256())
        )
        (directory / "server-key.pem").write_bytes(
            signing_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        public = certificate.public_bytes(serialization.Encoding.PEM)
        (directory / "public-ca.pem").write_bytes(public)
        return hashlib.sha256(public).hexdigest()
    except Exception:
        # Failed preparation never becomes a usable transfer; leave evidence private.
        (directory / "payload.zip").unlink(missing_ok=True)
        raise


class Transfer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, address, peer, payload, context):
        if len(payload) > LIMIT:
            raise ValueError("Payload exceeds limit")
        self.peer, self.payload, self.context, self.delivered = peer, payload, context, False
        super().__init__(address, Handler)
        self.timeout = 0.5

    def get_request(self):
        connection, peer = super().get_request()
        connection.settimeout(3)
        try:
            if peer[0] != self.peer:
                raise OSError("Unexpected peer")
            return self.context.wrap_socket(connection, server_side=True), peer
        except Exception:
            connection.close()
            raise

    def handle_error(self, *_args):
        pass  # No HTTP request, filename or exception is logged.


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if hasattr(self.server, "destination"):
            self.send_error(404)
            return
        if self.path != PATH or self.server.delivered:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(self.server.payload)))
        self.end_headers()
        self.wfile.write(self.server.payload)
        self.wfile.flush()
        self.server.delivered = True

    def do_POST(self):
        if self.path != PATH or self.server.delivered or not hasattr(self.server, "destination"):
            self.send_error(404)
            return
        try:
            if self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("Chunked upload is unsupported")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= LIMIT:
                raise ValueError("Invalid upload length")
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError("Incomplete upload")
            unpack(body, self.server.destination)
        except Exception:
            self.send_error(400)
            return
        self.server.delivered = True
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()


def receive(destination, host, peer, port, lifetime, certificate, key):
    destination = private_path(destination)
    if destination.exists():
        raise ValueError("Preserve existing intake")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key)
    deadline = time.monotonic() + lifetime
    with Transfer((host, port), peer, b"", context) as server:
        server.destination = destination
        print('{"handoff":"LISTENING"}', flush=True)
        while not server.delivered and time.monotonic() < deadline:
            server.handle_request()
        if not server.delivered:
            raise TimeoutError("Intake expired")
    return {"handoff": "received_and_validated", "deployed": False, "google_requests": 0}


class RoutedHTTPS(http.client.HTTPSConnection):
    def __init__(self, identity, peer, port, context):
        super().__init__(identity, port, context=context, timeout=10)
        self.peer = peer

    def connect(self):
        connection = socket.create_connection((self.peer, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except Exception:
            connection.close()
            raise


def send(directory, peer, identity, port, ca):
    directory = private_path(directory)
    validate_files(directory)
    body = (directory / "payload.zip").read_bytes()
    if len(body) > LIMIT:
        raise ValueError("Payload exceeds limit")
    connection = RoutedHTTPS(identity, peer, port, ssl.create_default_context(cafile=str(ca)))
    try:
        connection.request("POST", PATH, body, {"Content-Type": "application/zip"})
        response = connection.getresponse()
        if response.status != 200 or response.read(1) != b"":
            raise ValueError("Receiver did not accept the handoff")
    finally:
        connection.close()
    return {"handoff": "receiver_confirmed", "deployed": False, "google_requests": 0}


def serve(directory, host, peer, port, lifetime):
    directory = private_path(directory)
    validate_files(directory)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(directory / "public-ca.pem", directory / "server-key.pem")
    deadline = time.monotonic() + lifetime
    with Transfer((host, port), peer, (directory / "payload.zip").read_bytes(), context) as server:
        print('{"handoff":"LISTENING"}', flush=True)
        while not server.delivered and time.monotonic() < deadline:
            server.handle_request()
        if not server.delivered:
            raise TimeoutError("Transfer expired")
    return {"handoff": "sent_once", "receiver_acceptance": "not_confirmed"}


def fetch(host, port, ca, expected_hash, destination):
    if hashlib.sha256(ca.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Public certificate fingerprint differs")
    context = ssl.create_default_context(cafile=str(ca))
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=10)
    try:
        connection.request("GET", PATH)
        response = connection.getresponse()
        body = response.read(LIMIT + 1)
        if response.status != 200 or len(body) > LIMIT:
            raise ValueError("Private delivery failed")
        if response.getheader("Content-Length") != str(len(body)):
            raise ValueError("Incomplete private delivery")
    finally:
        connection.close()
    unpack(body, destination)
    return {"handoff": "received_and_validated", "deployed": False, "google_requests": 0}


def unpack(body, destination):
    # Explicit names and bounded uncompressed lengths; never extract arbitrary paths.
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if sorted(names) != ["confirmation.json", "gemini-key.txt"] or any(
            i.file_size > 16384 for i in archive.infolist()
        ):
            raise ValueError("Unexpected private archive")
        manifest, key = archive.read("confirmation.json"), archive.read("gemini-key.txt")
    validate(manifest, key)
    destination = private_path(destination)
    private_directory(destination)
    (destination / "confirmation.json").write_bytes(manifest)
    (destination / "gemini-key.txt").write_bytes(key)
    validate_files(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    make = sub.add_parser("prepare")
    make.add_argument("--directory", type=Path, required=True)
    make.add_argument("--host", type=private_ip, required=True)
    make.add_argument("--manifest", type=Path, required=True)
    make.add_argument("--key", type=Path, required=True)
    send = sub.add_parser("serve")
    send.add_argument("--directory", type=Path, required=True)
    send.add_argument("--host", type=private_ip, required=True)
    send.add_argument("--peer", type=private_ip, required=True)
    send.add_argument("--port", type=int, default=18446)
    send.add_argument("--lifetime", type=int, default=600)
    get = sub.add_parser("fetch")
    get.add_argument("--host", type=private_ip, required=True)
    get.add_argument("--port", type=int, default=18446)
    get.add_argument("--ca", type=Path, required=True)
    get.add_argument("--ca-sha256", required=True)
    get.add_argument("--destination", type=Path, required=True)
    accept = sub.add_parser("receive")
    accept.add_argument("--destination", type=Path, required=True)
    accept.add_argument("--host", type=private_ip, required=True)
    accept.add_argument("--peer", type=private_ip, required=True)
    accept.add_argument("--port", type=int, default=18446)
    accept.add_argument("--lifetime", type=int, default=1200)
    accept.add_argument("--certificate", type=Path, required=True)
    accept.add_argument("--tls-key", type=Path, required=True)
    upload = sub.add_parser("send")
    upload.add_argument("--directory", type=Path, required=True)
    upload.add_argument("--host", type=private_ip, required=True)
    upload.add_argument("--identity", type=private_ip, required=True)
    upload.add_argument("--port", type=int, default=18446)
    upload.add_argument("--ca", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = {
                "public_ca_sha256": prepare(args.directory, args.host, args.manifest, args.key)
            }
        else:
            if not 1024 <= args.port <= 65535:
                raise ValueError("Invalid port")
            if args.action in {"serve", "receive"}:
                if not 1 <= args.lifetime <= 3600:
                    raise ValueError("Invalid lifetime")
                if args.action == "serve":
                    result = serve(args.directory, args.host, args.peer, args.port, args.lifetime)
                else:
                    result = receive(
                        args.destination,
                        args.host,
                        args.peer,
                        args.port,
                        args.lifetime,
                        args.certificate,
                        args.tls_key,
                    )
            elif args.action == "send":
                result = send(args.directory, args.host, args.identity, args.port, args.ca)
            else:
                result = fetch(args.host, args.port, args.ca, args.ca_sha256, args.destination)
        print(json.dumps(result))
    except Exception:
        print('{"handoff":"failed"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
