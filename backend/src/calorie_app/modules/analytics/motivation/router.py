"""Motivation transport. Source and projection transactions remain in services."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.analytics.motivation.ranking import ranking_page
from calorie_app.modules.analytics.motivation.schemas import (
    MotivationRead,
    RankingPage,
    RankingQuery,
)
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import require_account

router = APIRouter(prefix="/api/v1", tags=["motivation"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 409, 410, 422, 429, 503)}


@router.get(
    "/me/motivation",
    response_model=MotivationRead,
    operation_id="read_motivation",
    responses=ERRORS,
    description="Prywatny wynik serwerowy regularity_v1. Pending nie jest wynikiem ostatecznym.",
)
def motivation(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    from calorie_app.modules.analytics.motivation.service import read_motivation

    if request.query_params:
        raise DomainError(422, "invalid_request")
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return read_motivation(session, account.id, account.generation)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/ranking",
    response_model=RankingPage,
    operation_id="read_ranking",
    responses=ERRORS,
    description="Bieżący dobrowolny ranking. RANK liczy wyłącznie punkty. Losowy cursor "
    "wygasa po 10 minutach; 410 wymaga restartu. Zmiany między stronami mogą powodować "
    "powtórzenia lub pominięcia. Cursor nie zachowuje kopii wyników.",
)
def ranking(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    query: Annotated[RankingQuery, Query()],
):
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise DomainError(422, "invalid_request")
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return ranking_page(
                session, account.id, query.limit, query.page_token, account.generation
            )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
