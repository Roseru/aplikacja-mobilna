"""Real loopback TCP through create_app; signed JWKS is synthetic, no TLS/KC claim."""

import json
import os
import socket
from datetime import timedelta
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import httpx
import pytest
import uvicorn
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr
from sqlalchemy import text

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import OIDCVerifier
from calorie_app.main import create_app
from tests.integration.test_e8_4_projections import day_fact
from tests.support.e8_3_jwt import ISSUER
from tests.support.e8_4_postgres import (
    SECRET,
    activate,
    clock,
    complete_day,
    headers,
    projection_rows,
    runtime,
)
from tests.support.e8_4_postgres import e8_4_services as e8_4_services

pytestmark = pytest.mark.integration


def test_real_tcp_accept_commit_lost_ack_seed_replay_and_statistics_no_store():
    with runtime() as rt:
        activate(rt)
        day = rt["now"].date() + timedelta(days=1)
        complete_day(rt, "a", day, "100")
        public = json.loads(RSAAlgorithm.to_jwk(rt["signed"].private.public_key()))
        public.update(kid="e8-component", use="sig", alg="RS256")
        settings = Settings(
            database_url=rt["private"].api_url,
            environment="test",
            catalog_page_token_secret=SecretStr(SECRET),
            oidc_issuer=ISSUER,
            oidc_jwks_url=ISSUER + "/certs",
            _env_file=None,
        )
        app = create_app(settings, engine=rt["api"])
        jwks = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"keys": [public]})
            )
        )
        app.state.oidc_verifier = OIDCVerifier(settings, client=jwks)
        started = Event()

        class BoundServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    started.set()

        port = int(os.environ.get("E8_4_HTTP_PROBE_PORT", "18184"))
        listener = socket.socket()
        listener.bind(("127.0.0.1", port))
        listener.listen(32)
        server = BoundServer(
            uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
        )
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            assert started.wait(12), "owned actual HTTP server did not bind"
            origin = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=12, trust_env=False) as client:
                issued = client.post(
                    origin + "/api/v1/me/nemesis/share-code", headers=headers(rt, "b")
                )
                assert issued.status_code == 200, issued.text
                terms = {
                    "rule_version": "regularity_v1",
                    "duration_days": 7,
                    "time_zone": "UTC",
                    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
                }
                created = client.post(
                    origin + "/api/v1/nemesis",
                    headers=headers(rt),
                    json={"destination_code": issued.json()["destination_code"], "terms": terms},
                )
                assert created.status_code == 201, created.text
                identifier = created.json()["id"]
                key = uuid4()
                h = headers(rt, "b", key=key, revision=created.json()["revision"])
                path = f"/api/v1/nemesis/{identifier}/accept"
                body = json.dumps({"terms": terms}).encode("utf-8")
                request = (
                    f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    + "".join(name + ": " + value + "\r\n" for name, value in h.items())
                    + f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                    + "Connection: close\r\n\r\n"
                ).encode("ascii") + body
                lost = socket.create_connection(("127.0.0.1", port), timeout=8)
                try:
                    lost.sendall(request)
                    deadline = monotonic() + 12
                    while True:
                        with rt["admin"].connect() as connection:
                            committed = connection.scalar(
                                text(
                                    "SELECT EXISTS(SELECT 1 FROM app.nemesis_receipts "
                                    "WHERE operation='accept' AND key=:key)"
                                ),
                                {"key": key},
                            )
                        if committed:
                            break
                        assert monotonic() < deadline, "actual accept COMMIT barrier not observed"
                        Event().wait(0.01)
                finally:
                    lost.close()  # Deliberately never recv the successfully committed ACK.
                before = projection_rows(rt, identifier)
                replay = client.post(origin + path, headers=h, json={"terms": terms})
                assert replay.status_code == 200 and replay.headers["cache-control"] == "no-store"
                assert projection_rows(rt, identifier) == before and len(before) == 14
                route = origin + f"/api/v1/nemesis/{identifier}/statistics"
                pending = client.get(route, headers=headers(rt))
                assert pending.status_code == 200 and pending.json()["status"] == "pending"
                clock(rt, day_fact(rt, identifier, day)["matures_at"])
                result = client.get(route, headers=headers(rt))
                assert (
                    result.status_code == 200 and result.json()["self"]["regularity"]["points"] == 1
                )
                assert result.headers["cache-control"] == "no-store"
                for h, expected in (({}, 401), (headers(rt, "c"), 404)):
                    refused = client.get(route, headers=h)
                    assert (
                        refused.status_code == expected
                        and refused.headers["cache-control"] == "no-store"
                    )
        finally:
            server.should_exit = True
            thread.join(timeout=12)
            listener.close()
            assert not thread.is_alive(), "owned HTTP server failed graceful shutdown"
