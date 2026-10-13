"""Authenticate and check context before bounded memory-only parsing."""

from typing import Annotated

from anyio.from_thread import run as from_thread_run
from fastapi import APIRouter, Depends, Header, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import AuthFailure
from calorie_app.modules.ai import decisions, service
from calorie_app.modules.ai.result import ProviderResultError, parse_bounded_json
from calorie_app.modules.ai.schemas import (
    AnalysisResponse,
    CancelRequest,
    CancelResponse,
    Capabilities,
    ConfirmRequest,
    ConfirmResponse,
    CreateMetadata,
    CreateResponse,
)
from calorie_app.modules.ai.transport import parse_multipart, read_body
from calorie_app.modules.catalog.community.idempotency import outcome_response
from calorie_app.modules.catalog.schemas import Uuid
from calorie_app.modules.identity.dependencies import current_principal

ERRORS = {status: {"model": ApiError} for status in (401, 403, 404, 409, 410, 413, 422, 429, 503)}
router = APIRouter(prefix="/api/v1/ai", tags=["photo-analysis"], responses=ERRORS)
PrincipalDep = Annotated[object, Depends(current_principal)]
Key = Annotated[Uuid, Header(alias="Idempotency-Key")]
Epoch = Annotated[Uuid, Header(alias="X-Sync-Epoch")]


def body_schema(model):
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    schema.pop("$defs", None)
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}


async def guarded(request, principal, epoch=None):
    try:
        await run_in_threadpool(
            service.initial_context, request.app.state.session_factory, principal, epoch
        )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
    if request.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise DomainError(422, "invalid_request")


async def json_request(request, model):
    if (
        request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise DomainError(422, "invalid_request")
    try:
        return model.model_validate(parse_bounded_json(await read_body(request, 1024 * 1024)))
    except (ProviderResultError, ValidationError, ValueError):
        raise DomainError(422, "invalid_request") from None


def reply(request, outcome):
    if outcome.error is not None:
        return outcome_response(request, outcome)
    return outcome.payload


async def reauthorization_async(request, principal):
    try:
        token = request.headers.get("authorization", "").split(" ", 1)[1]
        verified = await request.app.state.oidc_verifier.verify(token)
    except (IndexError, AuthFailure) as error:
        raise DomainError(
            getattr(error, "status", 401), getattr(error, "code", "unauthorized")
        ) from None
    if (verified.issuer, verified.subject) != (principal.issuer, principal.subject):
        raise DomainError(401, "unauthorized")
    if "user" not in verified.roles:
        raise DomainError(403, "forbidden")
    return verified


def reauthorization(request, principal):
    return lambda: from_thread_run(reauthorization_async, request, principal)


@router.get("/capabilities", response_model=Capabilities)
async def capabilities(request: Request, principal: PrincipalDep):
    try:
        return await run_in_threadpool(
            service.capabilities,
            request.app.state.session_factory,
            principal,
            request.app.state.settings,
        )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.post(
    "/food-analyses",
    status_code=202,
    response_model=CreateResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["metadata", "image"],
                        "properties": {
                            "metadata": {
                                "type": "string",
                                "description": "UTF-8 JSON CreateMetadata, <=16 KiB",
                            },
                            "image": {
                                "type": "string",
                                "format": "binary",
                                "description": "JPEG/PNG/WebP <=5 MiB",
                            },
                        },
                    },
                    "encoding": {
                        "metadata": {"contentType": "application/json"},
                        "image": {"contentType": "image/jpeg, image/png, image/webp"},
                    },
                }
            },
        }
    },
)
async def create(request: Request, principal: PrincipalDep, key: Key, epoch: Epoch):
    await guarded(request, principal, epoch)
    metadata, image = parse_multipart(
        await read_body(request), request.headers.get("Content-Type", "")
    )
    try:
        metadata = CreateMetadata.model_validate(metadata)
    except ValidationError:
        raise DomainError(422, "photo_consent_required") from None
    try:
        outcome = await run_in_threadpool(
            service.create_analysis,
            request.app.state.engine,
            principal,
            epoch,
            key,
            metadata.model_dump(mode="json"),
            image,
            request.app.state.settings,
            reauthorization(request, principal),
        )
        return reply(request, outcome)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get("/food-analyses/{analysis_id}", response_model=AnalysisResponse)
async def get(request: Request, principal: PrincipalDep, analysis_id: Uuid):
    try:
        return await run_in_threadpool(
            service.read_analysis, request.app.state.session_factory, principal, analysis_id
        )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.post(
    "/food-analyses/{analysis_id}/confirm",
    response_model=ConfirmResponse,
    openapi_extra=body_schema(ConfirmRequest),
)
async def confirm(
    request: Request, principal: PrincipalDep, analysis_id: Uuid, key: Key, epoch: Epoch
):
    await guarded(request, principal, epoch)
    body = await json_request(request, ConfirmRequest)
    principal = await reauthorization_async(request, principal)
    try:
        outcome = await run_in_threadpool(
            decisions.confirm,
            request.app.state.session_factory,
            principal,
            epoch,
            key,
            analysis_id,
            body,
        )
        return reply(request, outcome)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.post(
    "/food-analyses/{analysis_id}/cancel",
    response_model=CancelResponse,
    openapi_extra=body_schema(CancelRequest),
)
async def cancel(
    request: Request, principal: PrincipalDep, analysis_id: Uuid, key: Key, epoch: Epoch
):
    await guarded(request, principal, epoch)
    body = await json_request(request, CancelRequest)
    principal = await reauthorization_async(request, principal)
    try:
        outcome = await run_in_threadpool(
            decisions.cancel,
            request.app.state.session_factory,
            principal,
            epoch,
            key,
            analysis_id,
            body,
        )
        return reply(request, outcome)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
