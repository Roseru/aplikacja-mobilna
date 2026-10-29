"""Peer admission only; no real backend, sockets, Keycloak or Android services."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

from infra.local.integration import gateway

ORIGIN = "https://172.16.0.2:28443"
SPOOFED = [
    (b"host", b"172.16.0.2:28443"),
    (b"forwarded", b"for=127.0.0.1;host=172.16.0.2:28443;proto=https"),
    (b"x-forwarded-for", b"127.0.0.1"),
    (b"x-real-ip", b"172.16.0.2"),
]
MISSING = object()
BAD_CLIENTS = [
    MISSING,
    None,
    (),
    ("127.0.0.1",),
    ("127.0.0.1", 1234, "extra"),
    "127.0.0.1",
    {"host": "127.0.0.1", "port": 1234},
    (None, 1234),
    (b"127.0.0.1", 1234),
    (123, 1234),
    ("127.0.0.1", None),
    ("127.0.0.1", "1234"),
    ("127.0.0.1", True),
    ("127.0.0.1", 0),
    ("127.0.0.1", -1),
    ("127.0.0.1", 65536),
    *[
        (host, 1234)
        for host in (
            "172.16.0.3",
            "192.168.1.2",
            "203.0.113.5",
            "127.0.0.2",
            "localhost",
            "127.1",
            "2130706433",
            "0x7f000001",
            "127.000.0.1",
            " 127.0.0.1",
            "127.0.0.1 ",
            "172.16.0.2%eth0",
            "::1",
            "::ffff:127.0.0.1",
            "::ffff:172.16.0.2",
        )
    ],
]


def scope(kind, client=MISSING, *, path="/api/v1/me", headers=()):
    value = {
        "type": kind,
        "asgi": {"version": "3.0"},
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": list(headers),
    }
    if client is not MISSING:
        value["client"] = client
    return value


def forbidden(*args, **kwargs):
    pytest.fail("Denied peer reached receive/backend/httpx")


async def forbidden_async(*args, **kwargs):
    forbidden()


def invoke(app, value, receive=forbidden_async):
    sent = []

    async def send(event):
        sent.append(event)

    asyncio.run(app(value, receive, send))
    return sent


@pytest.mark.parametrize("client", BAD_CLIENTS)
@pytest.mark.parametrize(
    "path", ["/api/v1/me", "/realms/calorie-dev/protocol/openid-connect/token"]
)
def test_http_denies_foreign_missing_and_malformed_before_any_work(monkeypatch, client, path):
    monkeypatch.setattr(gateway.httpx, "AsyncClient", forbidden)
    app = gateway.Gateway(forbidden_async, ORIGIN, 28080)
    sent = invoke(app, scope("http", client, path=path, headers=SPOOFED))
    assert len(sent) == 2
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 403
    assert (b"cache-control", b"no-store") in sent[0]["headers"]
    assert sent[1]["type"] == "http.response.body" and sent[1]["body"] == b""


@pytest.mark.parametrize("client", BAD_CLIENTS)
def test_websocket_cannot_bypass_peer_guard(monkeypatch, client):
    monkeypatch.setattr(gateway.httpx, "AsyncClient", forbidden)
    app = gateway.Gateway(forbidden_async, ORIGIN, 28080)
    assert invoke(app, scope("websocket", client, headers=SPOOFED)) == [
        {"type": "websocket.close", "code": 1008}
    ]


def test_http_admission_precedes_even_path_and_headers(monkeypatch):
    monkeypatch.setattr(gateway.httpx, "AsyncClient", forbidden)
    app = gateway.Gateway(forbidden_async, ORIGIN, 28080)
    sent = invoke(app, {"type": "http"})
    assert sent[0]["status"] == 403


@pytest.mark.parametrize("kind", ["http", "websocket"])
@pytest.mark.parametrize("client", [("127.0.0.1", 1234), ("172.16.0.2", 65535), ["127.0.0.1", 1]])
def test_exact_allowed_peer_delegates_without_trusting_headers(monkeypatch, kind, client):
    monkeypatch.setattr(gateway.httpx, "AsyncClient", forbidden)
    calls = []
    value = scope(
        kind, client, headers=[(b"host", b"foreign.example"), (b"x-forwarded-for", b"203.0.113.5")]
    )

    async def backend(actual, receive, send):
        assert actual is value and receive is forbidden_async
        calls.append(actual["client"])

    assert invoke(gateway.Gateway(backend, ORIGIN, 28080), value) == []
    assert calls == [client]


@pytest.mark.parametrize("path", ["/realms/calorie-dev/test", "/resources/test", "/admin/test"])
@pytest.mark.parametrize("host", ["127.0.0.1", "172.16.0.2"])
def test_allowed_peer_keeps_real_proxy_routing_and_header_sanitization(monkeypatch, host, path):
    original = httpx.AsyncClient
    calls = []

    def upstream(request):
        calls.append(request)
        assert str(request.url) == "http://127.0.0.1:28080" + path
        assert request.content == b"synthetic-body"
        assert request.headers["host"] == "172.16.0.2:28443"
        assert request.headers["x-forwarded-proto"] == "https"
        assert "forwarded" not in request.headers and "x-forwarded-for" not in request.headers
        return httpx.Response(200, content=b"synthetic-response")

    def proxy_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", proxy_client)
    receives = []

    async def receive():
        receives.append(True)
        return {"type": "http.request", "body": b"synthetic-body", "more_body": False}

    app = gateway.Gateway(forbidden_async, ORIGIN, 28080)
    sent = invoke(app, scope("http", (host, 1234), path=path, headers=SPOOFED), receive)
    assert len(calls) == len(receives) == 1 and sent[0]["status"] == 200
    assert sent[1]["body"] == b"synthetic-response"


def test_lifespan_is_the_only_peer_free_delegation(monkeypatch):
    monkeypatch.setattr(gateway.httpx, "AsyncClient", forbidden)
    calls = []

    async def backend(value, receive, send):
        calls.append(value)

    value = {"type": "lifespan"}
    assert invoke(gateway.Gateway(backend, ORIGIN, 28080), value) == []
    assert calls == [value]


@pytest.mark.parametrize(
    "kind", [MISSING, None, "", "unknown", "http.response", "lifespan.startup", True]
)
def test_unknown_scope_fails_closed_even_with_allowed_peer(monkeypatch, kind):
    monkeypatch.setattr(gateway.httpx, "AsyncClient", forbidden)
    value = {"client": ("127.0.0.1", 1234)}
    if kind is not MISSING:
        value["type"] = kind
    with pytest.raises(ValueError, match="Unsupported ASGI scope"):
        invoke(gateway.Gateway(forbidden_async, ORIGIN, 28080), value)


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:28443",
        "https://0.0.0.0:28443",
        "https://203.0.113.5:28443",
        "https://127.0.0.1:28443",
        "https://[::1]:28443",
        "https://172.016.0.2:28443",
        "https://172.16.0.2",
        "https://172.16.0.2:80",
        "http://172.16.0.2:28443",
        "https://172.16.0.2:28443/",
        "https://user@172.16.0.2:28443",
        None,
    ],
)
def test_nonliteral_or_noncanonical_configured_origin_refused(origin):
    with pytest.raises(ValueError):
        gateway.Gateway(forbidden_async, origin, 28080)


def config_file(tmp_path, monkeypatch, *, host="172.16.0.2", origin=ORIGIN):
    value = {"host": host, "origin": origin, "keycloak_port": 28080, "port": 28443}
    (tmp_path / "native.json").write_text(json.dumps(value))
    monkeypatch.setenv("CALORIE_NATIVE_STATE", str(tmp_path))


@pytest.mark.parametrize("host", [None, "172.16.0.3", "localhost", "172.016.0.2"])
def test_factory_refuses_config_host_origin_drift_before_backend(tmp_path, monkeypatch, host):
    config_file(tmp_path, monkeypatch, host=host)
    monkeypatch.setattr(gateway, "create_app", forbidden)
    monkeypatch.setattr(gateway.socket, "socket", forbidden)
    for function in (gateway.application, gateway.serve):
        with pytest.raises(ValueError):
            function()


def test_allowlist_uses_selected_configured_host_not_a_hardcoded_address(tmp_path, monkeypatch):
    config_file(tmp_path, monkeypatch, host="10.23.45.67", origin="https://10.23.45.67:28443")
    monkeypatch.setattr(gateway, "create_app", lambda: forbidden_async)
    app = gateway.application()
    assert app.allowed_peers == {"127.0.0.1", "10.23.45.67"}
    assert app.allowed_client(("10.23.45.67", 1234))
    assert not app.allowed_client(("172.16.0.2", 1234))


def test_server_preserves_proxy_headers_false_without_opening_real_sockets(tmp_path, monkeypatch):
    config_file(tmp_path, monkeypatch)
    monkeypatch.setattr(gateway, "create_app", lambda: forbidden_async)
    bound = []
    options = []
    closed = []

    class Socket:
        def setsockopt(self, *args):
            pass

        def bind(self, address):
            bound.append(address)

        def close(self):
            closed.append(True)

    def uvicorn_config(app, **kwargs):
        assert isinstance(app, gateway.Gateway)
        options.append(kwargs)
        return object()

    def run(*, sockets):
        assert len(sockets) == 2

    monkeypatch.setattr(gateway.socket, "socket", Socket)
    monkeypatch.setattr(uvicorn, "Config", uvicorn_config)
    monkeypatch.setattr(uvicorn, "Server", lambda config: SimpleNamespace(run=run))
    gateway.serve()
    assert set(bound) == {("127.0.0.1", 28443), ("172.16.0.2", 28443)}
    assert len(closed) == 2 and options[0]["proxy_headers"] is False
    assert options[0]["access_log"] is False
