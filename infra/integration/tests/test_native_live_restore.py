"""Operator maintenance barrier around the existing Native peer guard."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from infra.local.integration.gateway import Gateway
from infra.local.integration.live_restore import Maintenance, cleanup_owned


@pytest.mark.parametrize(
    "path", ["/api/v1/me", "/realms/calorie-dev/protocol/openid-connect/token"]
)
def test_closed_user_routes_never_reach_handler(path):
    class Guard:
        def allowed_client(self, client):
            return client == ("127.0.0.1", 1234)

        async def __call__(self, *_):
            pytest.fail("Closed user route reached handler")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=Maintenance(Guard(), True), client=("127.0.0.1", 1234)
            ),
            base_url="https://test",
        ) as client:
            response = await client.post(path)
            assert (
                response.status_code == 503
                and response.headers["cache-control"] == "no-store"
            )

    asyncio.run(run())


def test_foreign_operator_peer_guard_precedes_provider_and_backend(monkeypatch):
    async def backend(*_):
        pytest.fail("Foreign peer reached backend")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: pytest.fail("Foreign peer reached proxy"),
    )

    async def run():
        events = []
        app = Maintenance(Gateway(backend, "https://192.168.55.1:24443", 29999), True)
        scope = {
            "type": "http",
            "path": "/realms/master/protocol/openid-connect/token",
            "method": "POST",
            "headers": [],
            "client": ("127.0.0.2", 1234),
        }

        async def receive():
            pytest.fail("Foreign request body was consumed")

        async def send(event):
            events.append(event)

        await app(scope, receive, send)
        assert events[0]["status"] == 403

    asyncio.run(run())


@pytest.mark.parametrize(
    "path,raw",
    [
        (
            "/realms/master/../calorie-dev/protocol/openid-connect/token",
            b"/realms/master/../calorie-dev/protocol/openid-connect/token",
        ),
        (
            "/realms/master/../calorie-dev/protocol/openid-connect/token",
            b"/realms/master/%2e%2e/calorie-dev/protocol/openid-connect/token",
        ),
        (
            "/realms/master/protocol/openid-connect/token",
            b"/realms/master%2fprotocol/openid-connect/token",
        ),
        (
            "/admin/realms/calorie-dev/logout-all",
            b"/admin/realms/calorie-dev/./logout-all",
        ),
    ],
)
def test_maintenance_aliases_never_reach_proxy(path, raw):
    class Guard:
        def allowed_client(self, _client):
            return True

        async def __call__(self, *_):
            pytest.fail("Alias reached upstream during issuance fence")

    async def run():
        events = []

        async def receive():
            pytest.fail("Rejected alias body consumed")

        async def send(event):
            events.append(event)

        await Maintenance(Guard(), True)(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "raw_path": raw,
                "client": ("127.0.0.1", 1234),
            },
            receive,
            send,
        )
        assert events[0]["status"] == 503

    asyncio.run(run())


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/realms/master/protocol/openid-connect/token"),
        ("POST", "/admin/realms/calorie-dev/logout-all"),
        ("GET", "/realms/calorie-dev/protocol/openid-connect/certs"),
        (
            "GET",
            "/admin/realms/calorie-dev/users/00000000-0000-0000-0000-000000000001/sessions",
        ),
    ],
)
def test_maintenance_exact_operator_routes_only(method, path):
    scope = {"method": method, "path": path, "raw_path": path.encode()}
    assert Maintenance.operator_route(scope)
    assert not Maintenance.operator_route(
        scope | {"query_string": b"redirect=elsewhere"}
    )
    assert not Maintenance.operator_route(scope | {"method": "DELETE"})


def test_fresh_native_startup_failure_stops_own_pg_marker(tmp_path):
    (tmp_path / "postgres.process.json").write_text("owned marker fixture")
    calls = []
    stack = SimpleNamespace(
        state=tmp_path, down=lambda: calls.append("qualified_native_down")
    )
    receipt = {"result": "FAIL"}
    cleanup_owned(stack, None, None, receipt)
    assert calls == ["qualified_native_down"]
    assert receipt["startup_failure_native_down"] is True
    assert receipt["result"] == "FAIL"
