"""Moderator roles are checked before resource lookup and receipt replay."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.catalog.community.feedback_router import mutate
from calorie_app.modules.catalog.community.schemas import ReportResultDTO, ReportStatus
from calorie_app.modules.catalog.moderation.reads import list_reports
from calorie_app.modules.catalog.moderation.schemas import (
    MergeProductRequest,
    MergeProductResultDTO,
    ModerateProductRequest,
    ModerationProductResultDTO,
    ModerationReportPage,
    ReportResolutionRequest,
)
from calorie_app.modules.catalog.moderation.service import (
    merge_products,
    moderate_product,
    require_moderator,
    resolve_report,
)
from calorie_app.modules.catalog.pagination import CursorNotConfigured
from calorie_app.modules.catalog.schemas import Uuid
from calorie_app.modules.identity.dependencies import current_principal

router = APIRouter(prefix="/api/v1/moderation", tags=["moderation"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 404, 409, 410, 413, 422, 429, 503)}


def moderator(principal: Annotated[Principal, Depends(current_principal)]):
    require_moderator(principal)
    return principal


class ReportQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReportStatus | None = None
    limit: int = Field(default=100, ge=1, le=500)
    page_token: str | None = Field(default=None, min_length=1, max_length=4096)


@router.get(
    "/reports",
    response_model=ModerationReportPage,
    operation_id="list_moderation_reports",
    responses=ERRORS,
    description=(
        "Ograniczona kolejka bez konta/szkicu zgłaszającego; token mq1 wiąże "
        "kontekst i wersję kolejki na60min."
    ),
)
def reports(
    request: Request,
    query: Annotated[ReportQuery, Query()],
    principal: Annotated[Principal, Depends(moderator)],
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            return list_reports(
                session, principal, query, request.app.state.catalog_page_token_secret
            )
    except (SQLAlchemyError, CursorNotConfigured):
        raise DomainError(503, "service_unavailable") from None


@router.patch(
    "/reports/{id}",
    response_model=ReportResultDTO,
    operation_id="resolve_moderation_report",
    responses=ERRORS,
    description=(
        "Jawne resolved/dismissed/referred_to_admin z rewizją i powodem; official "
        "wymaga kontrolowanego nowego release."
    ),
)
def resolve(
    request: Request,
    id: Uuid,
    data: ReportResolutionRequest,
    principal: Annotated[Principal, Depends(moderator)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
):
    return mutate(
        request,
        principal,
        key,
        epoch,
        "resolve_report",
        {
            "method": "PATCH",
            "path": f"/api/v1/moderation/reports/{id}",
            "body": data.model_dump(mode="json"),
        },
        lambda session, account, operation: resolve_report(session, account, id, data, operation),
    )


@router.patch(
    "/products/{id}",
    response_model=ModerationProductResultDTO,
    operation_id="moderate_community_product",
    responses=ERRORS,
    description=(
        "Community korekta tworzy nową immutable wersję; verified/visibility mają "
        "osobną rewizję. Brak PATCH official."
    ),
)
def product(
    request: Request,
    id: Uuid,
    data: ModerateProductRequest,
    principal: Annotated[Principal, Depends(moderator)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
):
    return mutate(
        request,
        principal,
        key,
        epoch,
        "moderate_product",
        {
            "method": "PATCH",
            "path": f"/api/v1/moderation/products/{id}",
            "body": data.model_dump(mode="json"),
        },
        lambda session, account, operation: moderate_product(session, account, id, data, operation),
    )


@router.post(
    "/products/{id}/merge",
    response_model=MergeProductResultDTO,
    operation_id="merge_community_products",
    responses=ERRORS,
    description=(
        "Source→canonical target dwóch widocznych community roots; nie przenosi "
        "opinii source i zachowuje exact historię."
    ),
)
def merge(
    request: Request,
    id: Uuid,
    data: MergeProductRequest,
    principal: Annotated[Principal, Depends(moderator)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
):
    return mutate(
        request,
        principal,
        key,
        epoch,
        "merge_products",
        {
            "method": "POST",
            "path": f"/api/v1/moderation/products/{id}/merge",
            "body": data.model_dump(mode="json"),
        },
        lambda session, account, operation: merge_products(session, account, id, data, operation),
    )
