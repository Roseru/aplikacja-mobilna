"""Purpose-separated read tokens reuse the tested E4 canonical HMAC codec."""

import hmac

from calorie_app.core.errors import DomainError
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.tokens import _key, read_token, sign_token


def domain_secret(secret):
    try:
        return hmac.digest(_key(secret), b"calorie-app/private-read/v1", "sha256").hex()
    except SyncFailure:
        raise DomainError(503, "service_unavailable") from None


def sign(claims, secret):
    token = sign_token(claims, domain_secret(secret))
    return "read1." + token.removeprefix("sync1.")


def verify(token, secret, *, owner_id, generation, epoch):
    if not isinstance(token, str) or not token.startswith("read1."):
        raise DomainError(422, "invalid_read_token")
    try:
        return read_token(
            "sync1." + token.removeprefix("read1."),
            domain_secret(secret),
            kind="read_page",
            owner_id=owner_id,
            generation=generation,
            epoch=epoch,
        )
    except SyncFailure as error:
        code = "invalid_read_token" if error.code == "invalid_sync_token" else error.code
        raise DomainError(error.status, code) from None
