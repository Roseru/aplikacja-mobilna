import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.router import idempotency_key
from calorie_app.modules.identity.service import require_account
from calorie_app.modules.profiles.pagination import goal_page
from calorie_app.modules.profiles.schemas import (
    Consent,
    ConsentInput,
    Estimate,
    EstimateInput,
    GoalPage,
    GoalQuery,
    ProfileRead,
)
from calorie_app.modules.profiles.service import estimate_energy, put_consents, read_profile

router = APIRouter(prefix="/api/v1", tags=["profiles"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 409, 422, 503)}


def if_match_revision(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(r'"[1-9][0-9]{0,9}"', value) is None
        or int(value[1:-1]) > 2147483647
    ):
        raise DomainError(422, "invalid_request")
    return int(value[1:-1])


@router.get("/me", response_model=ProfileRead, operation_id="read_me", responses=ERRORS)
def me(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return read_profile(session, account.id)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/me/goals",
    response_model=GoalPage,
    operation_id="list_goals",
    responses=ERRORS | {410: {"model": ApiError}},
    description="Niezmienne wersje w porządku UUID. Podpisany token przypina "
    "właściciela, generację, epokę, limit i rewizję osi na 60 minut.",
)
def goals(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    query: Annotated[GoalQuery, Query()],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return goal_page(
                session,
                account.id,
                query.limit,
                query.page_token,
                request.app.state.catalog_page_token_secret,
            )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.post(
    "/energy-estimates",
    response_model=Estimate,
    operation_id="estimate_energy",
    responses=ERRORS,
    description="Szacunek utrzymania, bez zapisu lub ustawiania celu.",
)
def energy_estimate(
    request: Request,
    data: EstimateInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            require_account(session, principal)
            return estimate_energy(data)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.put(
    "/me/consents",
    response_model=Consent,
    operation_id="update_consents",
    responses=ERRORS,
    description="Pełne booleany, UUID Idempotency-Key i cytowana revision If-Match. "
    "Identyczny replay poprzedza sprawdzenie bieżącej revision. "
    "Pełny wynik minimum 60 dni; po sprzątaniu 409 idempotency_result_expired bez mutacji.",
)
def consents(
    request: Request,
    response: Response,
    data: ConsentInput,
    principal: Annotated[Principal, Depends(current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    match: Annotated[str, Header(alias="If-Match")],
):
    parsed_key, revision = idempotency_key(key), if_match_revision(match)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            result = put_consents(
                session, account.id, data, revision, parsed_key, account.generation
            )
            response.headers["ETag"] = f'"{result["revision"]}"'
            return result
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
