"""Authenticated online publication and read-only community endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.catalog.community.idempotency import execute_mutation, outcome_response
from calorie_app.modules.catalog.community.schemas import (
    CommunityProductDTO,
    CommunityProductPage,
    MatchProductRequest,
    MatchProductResponse,
    PublishProductRequest,
    PublishProductResult,
)
from calorie_app.modules.catalog.community.service import (
    list_community,
    match_draft,
    publish_draft,
    read_community,
)
from calorie_app.modules.catalog.pagination import CursorNotConfigured
from calorie_app.modules.catalog.schemas import Uuid
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.router import idempotency_key

router = APIRouter(prefix="/api/v1", tags=["community"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 404, 409, 410, 413, 422, 429, 503)}


class CommunityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=100, ge=1, le=500)
    page_token: str | None = Field(default=None, min_length=1, max_length=4096)


class CommunityRevisionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = Field(default=None, ge=1, le=2147483647)


@router.post(
    "/products",
    response_model=PublishProductResult,
    operation_id="publish_product",
    responses=ERRORS,
    description=(
        "Publikuje zatwierdzone metadata własnej żywej rewizji szkicu; nie "
        "zmienia szkicu. UUID Idempotency-Key i X-Sync-Epoch wymagane; wynik "
        "zawiera wyłącznie decyzję i exact ref."
    ),
)
def publish_product(
    request: Request,
    data: PublishProductRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
):
    operation_id, sync_epoch = idempotency_key(key), idempotency_key(epoch)
    semantic = {"method": "POST", "path": "/api/v1/products", "body": data.model_dump(mode="json")}
    try:
        with Session(request.app.state.engine) as session, session.begin():
            outcome = execute_mutation(
                session,
                principal,
                "publish_product",
                operation_id,
                sync_epoch,
                semantic,
                lambda account: publish_draft(session, account, data, operation_id),
            )
        return outcome_response(request, outcome)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.post(
    "/products/matches",
    response_model=MatchProductResponse,
    operation_id="match_products",
    responses=ERRORS,
    description=(
        "Ograniczony odczyt podobnych publicznych produktów na podstawie własnego "
        "szkicu i metadata. Nie rezerwuje produktu; publikacja ponownie sprawdza "
        "duplikaty pod blokadą. X-Sync-Epoch wymagane."
    ),
)
def match_products(
    request: Request,
    data: MatchProductRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
):
    sync_epoch = idempotency_key(epoch)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            return match_draft(session, principal, data, sync_epoch)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/community/products",
    response_model=CommunityProductPage,
    operation_id="list_community_products",
    responses=ERRORS,
    description=(
        "Indexed keyset community roots. Token przypina "
        "konto/generację/epokę/query/limit i catalog revision na60min; zmiana "
        "katalogu wymaga restartu przez catalog_changed."
    ),
)
def list_products(
    request: Request,
    query: Annotated[CommunityQuery, Query()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            return list_community(
                session, principal, query, request.app.state.catalog_page_token_secret
            )
    except (SQLAlchemyError, CursorNotConfigured):
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/community/products/{id}",
    response_model=CommunityProductDTO,
    operation_id="read_community_product",
    responses=ERRORS,
    description=(
        "Aktualny albo dokładny publiczny community snapshot. Po merge zachowuje "
        "pierwotne makra i podaje canonical_ref; hide źródła/celu odcina odczyt."
    ),
)
def read_product(
    request: Request,
    id: Uuid,
    query: Annotated[CommunityRevisionQuery, Query()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            return read_community(session, principal, id, query.revision)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
