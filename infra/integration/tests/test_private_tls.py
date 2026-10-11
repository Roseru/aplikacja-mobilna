"""Real JWKS TLS trust, including rejection of unknown CAs and hostname mismatch."""

import asyncio
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, OIDCVerifier
from infra.integration.run import (
    certificates,
    host_address,
    initialize,
    renew_certificate,
    safe_compose_error,
)


@pytest.fixture
def tls_provider(tmp_path):
    certificates(tmp_path / "tls", "127.0.0.1")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="integration", alg="RS256", use="sig")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"keys": [public]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "tls/server.pem", tmp_path / "tls/server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://identity.example/realms/calorie-dev",
            "aud": "calorie-api",
            "sub": "integration-account",
            "typ": "Bearer",
            "iat": now,
            "exp": now + 300,
            "resource_access": {"calorie-api": {"roles": ["user"]}},
        },
        key,
        algorithm="RS256",
        headers={"kid": "integration"},
    )
    try:
        yield server.server_port, tmp_path / "tls/ca.pem", token
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("case", ["trusted", "unknown-ca", "wrong-host"])
def test_real_oidc_jwks_requires_explicit_trusted_ca_and_matching_hostname(
    tls_provider, monkeypatch, case
):
    port, ca, token = tls_provider
    # Even a trusted env CA must not override the verifier's explicit operator settings.
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    hostname = "localhost" if case == "wrong-host" else "127.0.0.1"
    settings = Settings(
        database_url="postgresql+psycopg://unused@localhost/calorie_test",
        oidc_issuer="https://identity.example/realms/calorie-dev",
        oidc_jwks_url=f"https://{hostname}:{port}/certs",
        oidc_ca_bundle=None if case == "unknown-ca" else ca,
    )

    async def check():
        verifier = OIDCVerifier(settings)
        try:
            if case == "trusted":
                principal = await verifier.verify(token)
                assert principal.subject == "integration-account"
                assert principal.roles == frozenset({"user"})
            else:
                with pytest.raises(AuthFailure) as failure:
                    await verifier.verify(token)
                assert failure.value.status == 503
        finally:
            await verifier.close()

    asyncio.run(check())


def test_reinitialization_cannot_rotate_secrets_or_overwrite_state(tmp_path):
    state = tmp_path / "state"
    initialize(state)
    paths = (state / "api.env", state / "credentials.json", state / "tls/ca.pem")
    before = [path.read_bytes() for path in paths]
    with pytest.raises(ValueError, match="never overwrites"):
        initialize(state)
    assert [path.read_bytes() for path in paths] == before


def test_leaf_renewal_preserves_ca_issuer_and_secrets(tmp_path):
    state = tmp_path / "state"
    initialize(state)
    files = [state / name for name in ("config.json", "api.env", "tls/ca.pem", "tls/ca.key")]
    before = [path.read_bytes() for path in files]
    old_leaf = (state / "tls/server.pem").read_bytes()
    renew_certificate(state / "tls", "127.0.0.1")
    assert [path.read_bytes() for path in files] == before
    assert (state / "tls/server.pem").read_bytes() != old_leaf


def test_ci_diagnostic_masks_credentials_dsn_and_jwt(tmp_path):
    state = tmp_path / "state"
    initialize(state)
    pairs = dict(line.split("=", 1) for line in (state / "api.env").read_text().splitlines())
    credential = json.loads((state / "credentials.json").read_text())["admin"]["password"]
    jwt_text = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhIn0.signature"
    text = "\n".join(
        [
            pairs["DATABASE_URL"],
            pairs["CATALOG_PAGE_TOKEN_SECRET"],
            credential,
            jwt_text,
            "image pull failed: 429",
        ]
    )
    sanitized = safe_compose_error(state, text)
    for secret in (pairs["DATABASE_URL"], pairs["CATALOG_PAGE_TOKEN_SECRET"], credential, jwt_text):
        assert secret not in sanitized
    assert "image pull failed: 429" in sanitized


@pytest.mark.parametrize("host", ["0.0.0.0", "8.8.8.8", "example.com", "::1"])
def test_local_stack_rejects_public_or_wildcard_bind(host):
    with pytest.raises(ValueError):
        host_address(host)
