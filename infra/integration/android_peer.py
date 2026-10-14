"""Bounded TCP relay for an owned AVD on another workstation; TLS stays end-to-end."""

import argparse
import asyncio
import http.client
import ipaddress
import json
import socket
import ssl
from pathlib import Path


def private_address(value):
    address = ipaddress.IPv4Address(value)
    if not any(
        address in ipaddress.ip_network(network)
        for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
    ):
        raise ValueError("Use an exact LAN/VPN IPv4 address, never a public or wildcard bind")
    return str(address)


def endpoint(bundle, via_host, via_port):
    """Read only discovery/readiness through a TCP route, verifying the original identity."""
    config = json.loads((bundle / "config.json").read_text(encoding="utf-8"))
    host, port = config["host"], int(config["port"])
    context = ssl.create_default_context(cafile=str(bundle / "tls/ca.pem"))
    issuer = f"https://{host}:{port}/realms/calorie-dev"
    for path, field, expected in (
        ("/health/ready", "status", "ok"),
        ("/realms/calorie-dev/.well-known/openid-configuration", "issuer", issuer),
    ):
        with socket.create_connection((via_host, via_port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=host) as connection:
                request = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n"
                connection.sendall(request.encode("ascii"))
                response = http.client.HTTPResponse(connection)
                response.begin()
                body = response.read(131073)
                if response.status != 200 or len(body) > 131072:
                    raise ValueError("Bounded HTTPS preflight failed")
                if json.loads(body).get(field) != expected:
                    raise ValueError("Readiness or exact issuer mismatch")
    return {"https": "PASS", "discovery": 200, "readiness": 200, "issuer": issuer}


class Relay:
    def __init__(self, target, allowed, *, idle_timeout=60, maximum=16):
        self.target, self.allowed = target, allowed
        self.idle_timeout, self.maximum = idle_timeout, maximum
        self.active = set()

    async def copy(self, reader, writer):
        while data := await asyncio.wait_for(reader.read(65536), self.idle_timeout):
            writer.write(data)
            await asyncio.wait_for(writer.drain(), self.idle_timeout)
        if writer.can_write_eof():
            writer.write_eof()

    async def accept(self, reader, writer):
        peer = writer.get_extra_info("peername")
        if not peer or peer[0] != self.allowed or len(self.active) >= self.maximum:
            writer.close()
            await writer.wait_closed()
            return
        task = asyncio.current_task()
        self.active.add(task)
        upstream = None
        copies = []
        try:
            remote, upstream = await asyncio.wait_for(asyncio.open_connection(*self.target), 5)
            copies = [
                asyncio.create_task(self.copy(reader, upstream)),
                asyncio.create_task(self.copy(remote, writer)),
            ]
            await asyncio.gather(*copies)
        except (OSError, TimeoutError):
            # Never record request bytes, credentials, URLs or token responses.
            pass
        finally:
            for copy in copies:
                if not copy.done():
                    copy.cancel()
            if copies:
                await asyncio.gather(*copies, return_exceptions=True)
            for connection in (upstream, writer):
                if connection:
                    connection.close()
                    try:
                        await connection.wait_closed()
                    except OSError:
                        pass
            self.active.discard(task)

    async def serve(self, bind, port, lifetime):
        server = await asyncio.start_server(self.accept, bind, port, limit=65536)
        try:
            async with server:
                print(json.dumps({"relay": "LISTENING", "bind": bind, "port": port}), flush=True)
                await asyncio.sleep(lifetime)
        finally:
            server.close()
            await server.wait_closed()
            for task in list(self.active):
                task.cancel()
            await asyncio.gather(*self.active, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("server", "client", "check"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--peer-host", required=True, help="Exact O3 LAN/VPN address")
    parser.add_argument("--peer-port", type=int, default=18444)
    parser.add_argument("--allow-client", help="Exact O1 LAN/VPN address; required for server")
    parser.add_argument("--lifetime", type=int, default=3600)
    args = parser.parse_args()
    private_address(args.peer_host)
    if not 1024 <= args.peer_port <= 65535 or not 60 <= args.lifetime <= 86400:
        parser.error("Expected nonprivileged port and lifetime 60..86400 seconds")
    config = json.loads((args.bundle / "config.json").read_text(encoding="utf-8"))
    origin_port = int(config["port"])
    if not 1024 <= origin_port <= 65535:
        parser.error("Invalid origin port")
    if args.action == "server":
        if not args.allow_client:
            parser.error("Server requires one exact authorized peer")
        allowed = private_address(args.allow_client)
        print(json.dumps(endpoint(args.bundle, "127.0.0.1", origin_port)), flush=True)
        relay, bind, port = (
            Relay(("127.0.0.1", origin_port), allowed),
            args.peer_host,
            args.peer_port,
        )
    else:
        print(json.dumps(endpoint(args.bundle, args.peer_host, args.peer_port)), flush=True)
        if args.action == "check":
            return
        relay = Relay((args.peer_host, args.peer_port), "127.0.0.1")
        bind, port = "127.0.0.1", origin_port
    asyncio.run(relay.serve(bind, port, args.lifetime))


if __name__ == "__main__":
    main()
