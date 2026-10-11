"""Private view transport; read services own all transaction boundaries."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.diary.read_schemas import DiaryDayPage, MealPage, WeightPage
from calorie_app.modules.diary.read_service import read
from calorie_app.modules.identity.dependencies import current_principal

router = APIRouter(prefix="/api/v1/me", tags=["diary"])
NO_STORE = {
    "Cache-Control": {
        "schema": {"type": "string", "const": "no-store"},
        "description": "Private responses must not be stored by HTTP caches.",
    }
}
ERRORS = {
    status: {"model": ApiError, "headers": NO_STORE} for status in (401, 403, 409, 410, 422, 503)
} | {200: {"headers": NO_STORE}}
PARAMETERS = [
    {"name": name, "in": "query", "required": True, "schema": {"type": "string", "format": "date"}}
    for name in ("from", "to")
] + [
    {
        "name": "limit",
        "in": "query",
        "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
    },
    {
        "name": "page_token",
        "in": "query",
        "schema": {"type": "string", "minLength": 1, "maxLength": 4096},
    },
]


def _read(request, principal, endpoint):
    query = {}
    for key, value in request.query_params.multi_items():
        if key in query:
            raise DomainError(422, "invalid_request")
        query[key] = value
    return read(
        request.app.state.session_factory,
        principal,
        endpoint,
        query,
        request.app.state.catalog_page_token_secret,
    )


@router.get(
    "/meals",
    response_model=MealPage,
    responses=ERRORS,
    operation_id="read_meals",
    openapi_extra={"parameters": PARAMETERS},
    description=(
        "Own live snapshots; inclusive local dates, at most 366 days. "
        "Frozen pages are not sync checkpoints."
    ),
)
def meals(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    return _read(request, principal, "meals")


@router.get(
    "/weights",
    response_model=WeightPage,
    responses=ERRORS,
    operation_id="read_weights",
    description="All real live measurements ordered by (occurred_at, entity_id); frozen pages.",
    openapi_extra={"parameters": PARAMETERS},
)
def weights(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    return _read(request, principal, "weights")


@router.get(
    "/diary-days",
    response_model=DiaryDayPage,
    responses=ERRORS,
    operation_id="read_diary_days",
    description=(
        "Live declarations ordered by (local_date, entity_id); "
        "effective_complete is computed from the same frozen live meal state."
    ),
    openapi_extra={"parameters": PARAMETERS},
)
def diary_days(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    return _read(request, principal, "diary-days")
