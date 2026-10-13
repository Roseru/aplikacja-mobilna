"""Production lifecycle and private statistics routes with DB capability gating."""

import re
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from calorie_app.core.errors import ApiError, DomainError, error_response
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.catalog.community.transport import validate_body
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.nemesis import service
from calorie_app.modules.nemesis.schemas import (
    AcceptNemesis,
    CancelNemesis,
    CreateNemesis,
    NemesisMetadata,
    NemesisPage,
    NemesisStatistics,
    RevokeCodeReceipt,
    ShareCodeReceipt,
)


class NemesisRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def protected(request):
            request.state.request_id = getattr(request.state, "request_id", str(uuid4()))
            try:
                if request.method in {"POST", "DELETE"}:
                    if request.headers.get("content-encoding", "identity") != "identity":
                        raise DomainError(422, "invalid_request")
                    raw = bytearray()
                    async for chunk in request.stream():
                        if len(raw) + len(chunk) > 16384:
                            raise DomainError(413, "request_too_large")
                        raw.extend(chunk)
                    request._body = bytes(raw)
                    bodyless = request.url.path.endswith("/share-code")
                    if bodyless:
                        if raw:
                            raise DomainError(422, "invalid_request")
                    else:
                        if (
                            request.headers.get("content-type", "").split(";", 1)[0]
                            != "application/json"
                        ):
                            raise DomainError(422, "invalid_request")
                        try:
                            validate_body(bytes(raw))
                        except (ValueError, UnicodeError, RecursionError):
                            raise DomainError(422, "invalid_request") from None
                response = await original(request)
                if len(getattr(response, "body", b"")) > 1048576:
                    raise DomainError(503, "response_too_large")
            except RequestValidationError:
                response = error_response(
                    request, 422, "invalid_request", "Niepoprawne dane żądania."
                )
            except ResponseValidationError:
                response = error_response(
                    request,
                    503,
                    "service_unavailable",
                    "Nie można wykonać żądania.",
                    {"Retry-After": "5"},
                )
            except DomainError as error:
                headers = (
                    {"Retry-After": "900"}
                    if error.status == 429
                    else ({"Retry-After": "5"} if error.status == 503 else None)
                )
                if error.status == 401:
                    headers = {"WWW-Authenticate": "Bearer"}
                response = error_response(
                    request, error.status, error.code, "Nie można wykonać żądania.", headers
                )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Request-ID"] = request.state.request_id
            return response

        return protected


router = APIRouter(
    prefix="/api/v1",
    tags=["nemesis"],
    route_class=NemesisRoute,
    responses={status: {"model": ApiError} for status in (401, 403, 404, 409, 413, 422, 429, 503)},
)
Auth = Annotated[Principal, Depends(current_principal)]


def header(request, name):
    values = request.headers.getlist(name)
    if len(values) != 1:
        raise DomainError(422, "invalid_request")
    return values[0]


def uuid_header(request, name):
    value = header(request, name)
    try:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError
        return parsed
    except ValueError:
        raise DomainError(422, "invalid_request") from None


def revision_header(request):
    value = header(request, "If-Match")
    if re.fullmatch(r'"[1-9][0-9]{0,9}"', value) is None:
        raise DomainError(422, "invalid_request")
    revision = int(value[1:-1])
    if revision > 2147483647:
        raise DomainError(422, "invalid_request")
    return revision


def required_headers(*, mutation=False, revision=False):
    parameters = [
        {
            "name": "X-Sync-Epoch",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "format": "uuid"},
        }
    ]
    if mutation:
        parameters.append(
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        )
    if revision:
        parameters.append(
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "description": "Quoted revision in 1..2147483647",
                "schema": {"type": "string", "pattern": r'^"[1-9][0-9]{0,9}"$'},
            }
        )
    return {"parameters": parameters}


def operate(request, principal, operation, body=None, challenge_id=None):
    if request.query_params:
        raise DomainError(422, "invalid_request")
    return service.mutate(
        request.app.state.engine,
        principal,
        uuid_header(request, "X-Sync-Epoch"),
        operation,
        uuid_header(request, "Idempotency-Key"),
        body,
        challenge_id,
        revision_header(request) if challenge_id is not None else None,
        getattr(request.app.state, "nemesis_projection_initializer", None),
    ).response


@router.post(
    "/me/nemesis/share-code",
    operation_id="issue_nemesis_share_code",
    response_model=ShareCodeReceipt,
    openapi_extra=required_headers(mutation=True),
)
def issue(request: Request, principal: Auth):
    return operate(request, principal, "issue")


@router.delete(
    "/me/nemesis/share-code",
    operation_id="revoke_nemesis_share_code",
    response_model=RevokeCodeReceipt,
    openapi_extra=required_headers(mutation=True),
)
def revoke(request: Request, principal: Auth):
    return operate(request, principal, "revoke")


@router.post(
    "/nemesis",
    operation_id="create_nemesis",
    response_model=NemesisMetadata,
    status_code=201,
    openapi_extra=required_headers(mutation=True),
)
def create(request: Request, principal: Auth, body: CreateNemesis):
    return operate(request, principal, "create", body)


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=30, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=128)


@router.get(
    "/me/nemesis",
    operation_id="list_nemesis",
    response_model=NemesisPage,
    openapi_extra=required_headers(),
)
def listing(request: Request, principal: Auth, query: Annotated[PageQuery, Query()]):
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise DomainError(422, "invalid_request")
    return service.read(
        request.app.state.engine,
        principal,
        uuid_header(request, "X-Sync-Epoch"),
        limit=query.limit,
        cursor=query.cursor,
    ).response


@router.get(
    "/nemesis/{challenge_id}",
    operation_id="read_nemesis",
    response_model=NemesisMetadata,
    openapi_extra=required_headers(),
)
def metadata(request: Request, principal: Auth, challenge_id: UUID):
    if request.query_params:
        raise DomainError(422, "invalid_request")
    return service.read(
        request.app.state.engine, principal, uuid_header(request, "X-Sync-Epoch"), challenge_id
    ).response


@router.post(
    "/nemesis/{challenge_id}/accept",
    operation_id="accept_nemesis",
    response_model=NemesisMetadata,
    openapi_extra=required_headers(mutation=True, revision=True),
)
def accept(request: Request, principal: Auth, challenge_id: UUID, body: AcceptNemesis):
    return operate(request, principal, "accept", body, challenge_id)


@router.post(
    "/nemesis/{challenge_id}/cancel",
    operation_id="cancel_nemesis",
    response_model=NemesisMetadata,
    openapi_extra=required_headers(mutation=True, revision=True),
)
def cancel(request: Request, principal: Auth, challenge_id: UUID, body: CancelNemesis):
    return operate(request, principal, "cancel", body, challenge_id)


@router.get(
    "/nemesis/{challenge_id}/statistics",
    operation_id="read_nemesis_statistics",
    response_model=NemesisStatistics,
    openapi_extra=required_headers(),
)
def statistics(request: Request, principal: Auth, challenge_id: UUID):
    if request.query_params:
        raise DomainError(422, "invalid_request")
    return service.statistics(
        request.app.state.engine, principal, uuid_header(request, "X-Sync-Epoch"), challenge_id
    ).response
