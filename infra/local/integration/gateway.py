"""One private HTTPS listener; unchanged API and loopback-only Keycloak upstream."""

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


class Gateway:
    def __init__(self, backend, origin, keycloak_port):
        self.backend = backend
        self.origin = urlsplit(origin)
        self.keycloak_port = keycloak_port

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
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
    return Gateway(create_app(), config["origin"], config["keycloak_port"])


def serve():
    import uvicorn

    state = Path(os.environ["CALORIE_NATIVE_STATE"])
    config = json.loads((state / "native.json").read_text())
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
