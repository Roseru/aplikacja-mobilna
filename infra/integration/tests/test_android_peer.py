"""Real TLS over two relays, exact identity, access control and bounded lifetime."""

import asyncio
import json
import ssl

import pytest

from infra.integration.android_peer import Relay, endpoint, private_address
from infra.integration.run import certificates


@pytest.mark.parametrize("value", ["0.0.0.0", "8.8.8.8", "127.0.0.1", "169.254.1.2", "host;id"])
def test_rejects_wildcard_public_and_unresolved_peer(value):
    with pytest.raises(ValueError):
        private_address(value)


def test_accepts_explicit_vpn_peer():
    assert private_address("100.64.1.7") == "100.64.1.7"


def test_two_hops_keep_tls_identity_and_reject_foreign_ca(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.json").write_text(json.dumps({"host": "192.168.3.162", "port": 18443}))
    certificates(bundle / "tls", "192.168.3.162")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(bundle / "tls/server.pem", bundle / "tls/server.key")
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    (wrong / "config.json").write_bytes((bundle / "config.json").read_bytes())
    certificates(wrong / "tls", "192.168.3.162")
    paths = []

    async def http(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            path = request.split(b" ")[1].decode()
            paths.append(path)
            payload = (
                {"status": "ok"}
                if path == "/health/ready"
                else {"issuer": "https://192.168.3.162:18443/realms/calorie-dev"}
            )
            body = json.dumps(payload).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def scenario():
        tls = await asyncio.start_server(http, "127.0.0.1", 0, ssl=context)
        upstream = tls.sockets[0].getsockname()[1]
        o3 = Relay(("127.0.0.1", upstream), "127.0.0.1")
        server = await asyncio.start_server(o3.accept, "127.0.0.1", 0)
        o1 = Relay(("127.0.0.1", server.sockets[0].getsockname()[1]), "127.0.0.1")
        client = await asyncio.start_server(o1.accept, "127.0.0.1", 0)
        port = client.sockets[0].getsockname()[1]
        try:
            result = await asyncio.to_thread(endpoint, bundle, "127.0.0.1", port)
            assert result["https"] == "PASS"
            assert result["issuer"] == "https://192.168.3.162:18443/realms/calorie-dev"
            with pytest.raises(ssl.SSLCertVerificationError):
                await asyncio.to_thread(endpoint, wrong, "127.0.0.1", port)
            assert paths == [
                "/health/ready",
                "/realms/calorie-dev/.well-known/openid-configuration",
            ]
        finally:
            for listener in (client, server, tls):
                listener.close()
                await listener.wait_closed()
            for relay in (o1, o3):
                tasks = list(relay.active)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


def test_other_peer_refused_before_connecting_upstream():
    async def scenario():
        relay = Relay(("127.0.0.1", 1), "127.0.0.2")
        server = await asyncio.start_server(relay.accept, "127.0.0.1", 0)
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", server.sockets[0].getsockname()[1]
            )
            assert await asyncio.wait_for(reader.read(1), 2) == b""
            assert not relay.active
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_saturated_relay_refuses_new_connection():
    async def scenario():
        relay = Relay(("127.0.0.1", 1), "127.0.0.1", maximum=0)
        server = await asyncio.start_server(relay.accept, "127.0.0.1", 0)
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", server.sockets[0].getsockname()[1]
            )
            assert await asyncio.wait_for(reader.read(1), 2) == b""
            assert not relay.active
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
