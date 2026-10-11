"""Private TCP test server; no factory or fake projection is exported in the wheel."""

import json
import sys
from pathlib import Path

import httpx
import uvicorn
from sqlalchemy import create_engine

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import OIDCVerifier
from tests.support.e8_3_app import component_app
from tests.support.e8_3_jwt import ISSUER


class BoundServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            print("ready", flush=True)


def main():
    private = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    engine = create_engine(private["api_url"], hide_parameters=True)
    jwks = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=private["jwks"]))
    )
    verifier = OIDCVerifier(
        Settings(
            database_url=private["api_url"],
            environment="test",
            oidc_issuer=ISSUER,
            oidc_jwks_url=ISSUER + "/certs",
            _env_file=None,
        ),
        client=jwks,
    )
    app = component_app(engine, verifier, projection_initializer=lambda session, response: None)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=int(sys.argv[2]), access_log=False, log_level="warning"
    )
    listener = config.bind_socket()
    try:
        BoundServer(config).run(sockets=[listener])
    finally:
        listener.close()
        engine.dispose()


if __name__ == "__main__":
    main()
