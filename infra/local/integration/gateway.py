"""One private HTTPS listener; unchanged API and loopback-only Keycloak upstream."""

import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from starlette.responses import Response

from calorie_app.main import create_app

HOP = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
    b"host",
}


def _origin(value):
    if type(value) is not str:
        raise ValueError("A canonical private IPv4 HTTPS origin is required")
    parsed = urlsplit(value)
    host = ipaddress.IPv4Address(parsed.hostname)
    if (
        not any(
            host in ipaddress.ip_network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
        or value != f"https://{host}:{parsed.port}"
    ):
        raise ValueError("A canonical private IPv4 HTTPS origin is required")
    return parsed


def _configuration(config):
    if type(config["host"]) is not str or config["host"] != _origin(config["origin"]).hostname:
        raise ValueError("Configured native host and HTTPS origin differ")


class Gateway:
    def __init__(self, backend, origin, keycloak_port):
        self.backend = backend
        self.origin = _origin(origin)
        self.allowed_peers = frozenset(("127.0.0.1", self.origin.hostname))
        self.keycloak_port = keycloak_port

    def allowed_client(self, client):
        return (
            type(client) in (tuple, list)
            and len(client) == 2
            and type(client[0]) is str
            and client[0] in self.allowed_peers
            and type(client[1]) is int
            and 1 <= client[1] <= 65535
        )

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind == "lifespan":
            await self.backend(scope, receive, send)
            return
        if kind not in ("http", "websocket"):
            raise ValueError("Unsupported ASGI scope")
        if not self.allowed_client(scope.get("client")):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await Response(status_code=403, headers={"Cache-Control": "no-store"})(
                    scope, receive, send
                )
            return
        if kind == "websocket":
            await self.backend(scope, receive, send)
            return
        if not scope["path"].startswith(("/realms/", "/resources/", "/admin/")):
            await self.backend(scope, receive, send)
            return
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > 2 * 1024**2:
                await Response(status_code=413)(scope, receive, send)
                return
            if not event.get("more_body"):
                break
        headers = [
            (k, v)
            for k, v in scope["headers"]
            if k.lower() not in HOP | {b"forwarded"} and not k.lower().startswith(b"x-forwarded-")
        ]
        headers.extend(
            [
                (b"host", self.origin.netloc.encode()),
                (b"x-forwarded-host", self.origin.netloc.encode()),
                (b"x-forwarded-proto", b"https"),
                (b"x-forwarded-port", str(self.origin.port).encode()),
            ]
        )
        path = scope.get("raw_path", scope["path"].encode()).decode("ascii")
        query = scope.get("query_string", b"").decode("ascii")
        target = f"http://127.0.0.1:{self.keycloak_port}{path}" + ("?" + query if query else "")
        try:
            async with httpx.AsyncClient(
                trust_env=False, timeout=30, follow_redirects=False
            ) as client:
                upstream = await client.request(
                    scope["method"], target, headers=headers, content=bytes(body)
                )
            response = Response(upstream.content, status_code=upstream.status_code)
            response.raw_headers = [
                (k, v)
                for k, v in upstream.headers.raw
                if k.lower() not in HOP | {b"content-length", b"content-encoding", b"cache-control"}
            ]
            response.raw_headers.extend(
                [
                    (b"content-length", str(len(upstream.content)).encode()),
                    (b"cache-control", b"no-store"),
                ]
            )
        except httpx.TransportError:
            response = Response(status_code=502, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)


def application():
    state = Path(os.environ["CALORIE_NATIVE_STATE"])
    config = json.loads((state / "native.json").read_text())
    _configuration(config)
    return Gateway(create_app(), config["origin"], config["keycloak_port"])


def serve():
    import uvicorn

    state = Path(os.environ["CALORIE_NATIVE_STATE"])
    config = json.loads((state / "native.json").read_text())
    _configuration(config)
    sockets = []
    try:
        for host in {"127.0.0.1", config["host"]}:
            listener = socket.socket()
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((host, config["port"]))
            sockets.append(listener)
        uvicorn.Server(
            uvicorn.Config(
                application(),
                access_log=False,
                proxy_headers=False,
                ssl_keyfile=str(state / "tls/server.key"),
                ssl_certfile=str(state / "tls/server.pem"),
            )
        ).run(sockets=sockets)
    finally:
        for listener in sockets:
            listener.close()


if __name__ == "__main__":
    serve()
