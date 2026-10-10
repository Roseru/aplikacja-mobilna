"""JWT verification completes before a protected router acquires a DB connection."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import AuthFailure, Principal

bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


async def current_principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise DomainError(401, "unauthorized")
    try:
        principal = await request.app.state.oidc_verifier.verify(credentials.credentials)
    except AuthFailure as error:
        raise DomainError(error.status, error.code) from None
    if "user" not in principal.roles:
        raise DomainError(403, "forbidden")
    return principal
