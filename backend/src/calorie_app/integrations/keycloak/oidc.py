"""Fixed-trust Keycloak access-token verifier; no database access or token logging."""

import asyncio
import json
import math
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from calorie_app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Principal:
    issuer: str
    subject: str
    roles: frozenset[str]


class AuthFailure(Exception):
    """Only stable, non-sensitive information crosses the integration boundary."""

    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        self.retry_after = 5 if status == 503 else None
        super().__init__(code)


def _invalid() -> AuthFailure:
    return AuthFailure(401, "unauthorized")


def _unavailable() -> AuthFailure:
    return AuthFailure(503, "identity_provider_unavailable")


class OIDCVerifier:
    MAX_BYTES = 65536
    MAX_KEYS = 32
    MAX_TOKEN_BYTES = 16384
    SKEW = 60

    def __init__(self, settings: Settings, *, client=None, monotonic=None, wall_clock=None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            timeout=settings.oidc_jwks_timeout_seconds,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
        self._owns_client = client is None
        self._monotonic = monotonic or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._keys = {}
        self._expires = 0.0
        self._last_attempt = float("-inf")
        self._last_failed = False
        self._lock = asyncio.Lock()

    async def close(self):
        if self._owns_client:
            await self._client.aclose()

    async def verify(self, token: str) -> Principal:
        if not isinstance(token, str) or not token.isascii() or len(token) > self.MAX_TOKEN_BYTES:
            raise _invalid()
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 256
                or any(name in header for name in ("jku", "x5u", "crit"))
            ):
                raise _invalid()
        except (jwt.PyJWTError, RecursionError):
            raise _invalid() from None
        key = await self._get_key(kid)
        try:
            # Time validation below rejects coercions (bool/string/NaN/Infinity)
            # and uses a single clock instant for all skew boundaries.
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.settings.oidc_issuer,
                audience="calorie-api",
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            self._validate_claims(claims)
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError, RecursionError):
            raise _invalid() from None
        resources = claims.get("resource_access", {})
        if not isinstance(resources, dict):
            raise _invalid()
        api = resources.get("calorie-api", {})
        if not isinstance(api, dict):
            raise _invalid()
        roles = api.get("roles", [])
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise _invalid()
        return Principal(claims["iss"], claims["sub"], frozenset(roles))

    def _validate_claims(self, claims):
        if claims.get("typ") != "Bearer":
            raise ValueError("access token required")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise ValueError("invalid subject")
        for name in ("exp", "iat", "nbf"):
            if name == "nbf" and name not in claims:
                continue
            value = claims[name]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("invalid numeric date")
        now = self._wall_clock()
        if (
            not 0 < claims["exp"] - claims["iat"] <= 300
            or claims["exp"] <= now - self.SKEW
            or claims["iat"] > now + self.SKEW
            or ("nbf" in claims and claims["nbf"] > now + self.SKEW)
        ):
            raise ValueError("invalid lifetime")

    async def _get_key(self, kid):
        if not self.settings.oidc_issuer:
            raise _unavailable()
        now = self._monotonic()
        if now < self._expires and kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            now = self._monotonic()
            if now < self._expires and kid in self._keys:
                return self._keys[kid]
            if now - self._last_attempt >= self.settings.oidc_jwks_refresh_cooldown_seconds:
                self._last_attempt = now
                try:
                    keys = await self._fetch_keys()
                except (
                    httpx.HTTPError,
                    jwt.PyJWTError,
                    ValueError,
                    TypeError,
                    KeyError,
                    TimeoutError,
                    RecursionError,
                ):
                    self._last_failed = True
                    raise _unavailable() from None
                self._keys = keys
                self._expires = self._monotonic() + self.settings.oidc_jwks_cache_seconds
                self._last_failed = False
            if self._last_failed or self._monotonic() >= self._expires:
                raise _unavailable()
            if kid not in self._keys:
                raise _invalid()
            return self._keys[kid]

    async def _fetch_keys(self):
        body = bytearray()
        async with asyncio.timeout(self.settings.oidc_jwks_timeout_seconds):
            async with self._client.stream(
                "GET",
                self.settings.oidc_jwks_url,
                follow_redirects=False,
                headers={"Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    raise ValueError("invalid provider status")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("compressed provider response forbidden")
                length = response.headers.get("content-length")
                if length is not None and int(length) > self.MAX_BYTES:
                    raise ValueError("provider response too large")
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > self.MAX_BYTES:
                        raise ValueError("provider response too large")
                    body.extend(chunk)
        document = json.loads(body)
        raw = document["keys"]
        if not isinstance(raw, list) or len(raw) > self.MAX_KEYS:
            raise ValueError("invalid key count")
        result = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("invalid key")
            if item.get("kty") != "RSA" or item.get("use", "sig") != "sig":
                continue
            if item.get("alg", "RS256") != "RS256":
                continue
            kid = item.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 256 or kid in result:
                raise ValueError("invalid key identifier")
            if "d" in item or item.get("key_ops", ["verify"]) != ["verify"]:
                raise ValueError("invalid signing key")
            key = RSAAlgorithm.from_jwk(item)
            if not 2048 <= key.key_size <= 4096:
                raise ValueError("invalid RSA key size")
            result[kid] = key
        return result
