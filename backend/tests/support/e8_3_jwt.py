"""Synthetic signed access tokens through the real fixed-trust verifier.

This JWKS HTTP mock is explicitly not a Keycloak integration proof.
"""

import json
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import OIDCVerifier

ISSUER = "https://nemesis-identity.example.test/realm"


class SignedTokens:
    def __init__(self):
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        key.update(kid="e8-component", use="sig", alg="RS256")
        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [key]}))
        )
        self.verifier = OIDCVerifier(
            Settings(
                database_url="postgresql+psycopg://fixture@localhost/component_test",
                environment="test",
                oidc_issuer=ISSUER,
                oidc_jwks_url=ISSUER + "/certs",
                _env_file=None,
            ),
            client=self.client,
        )

    def token(self, subject, roles=("user",), **changes):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "calorie-api",
            "sub": subject,
            "iat": now,
            "exp": now + 240,
            "typ": "Bearer",
            "azp": "calorie-android",
            "resource_access": {"calorie-api": {"roles": list(roles)}},
        }
        claims.update(changes)
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": "e8-component"})
