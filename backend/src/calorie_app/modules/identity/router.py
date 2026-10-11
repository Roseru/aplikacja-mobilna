from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.profiles.schemas import Bootstrap

router = APIRouter(prefix="/api/v1", tags=["identity"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 409, 422, 503)}


def idempotency_key(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        return UUID(value)
    except ValueError:
        raise DomainError(422, "invalid_request") from None


@router.post(
    "/me/bootstrap",
    response_model=Bootstrap,
    operation_id="bootstrap",
    responses=ERRORS,
    description="Wymaga Idempotency-Key UUID; body zabronione. "
    "Replay zachowuje pierwotny czas i sprawdza aktywność, generację oraz epokę.",
)
async def bootstrap_account(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
):
    parsed = idempotency_key(key)
    if await request.body():
        raise DomainError(422, "invalid_request")

    def transaction():
        with Session(request.app.state.engine) as session, session.begin():
            return bootstrap(session, principal, parsed)

    try:
        return await run_in_threadpool(transaction)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
