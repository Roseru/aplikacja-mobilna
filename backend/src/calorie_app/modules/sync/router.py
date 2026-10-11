"""Transport/preflight and caller-owned operation commits."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from calorie_app.integrations.keycloak import AuthFailure, Principal
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import require_account
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.schemas import (
    PullResponse,
    PushResponse,
    SyncError,
    expanded_schema,
    preflight_structure,
)
from calorie_app.modules.sync.service import apply_operation, context
from calorie_app.modules.sync.snapshots import pull as pull_service
from calorie_app.modules.sync.transport import read_push

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])
ERRORS = {status: {"model": SyncError} for status in (401, 403, 409, 410, 413, 422, 429, 503)}


def preflight(factory, principal, data, secret):
    with factory() as session, session.begin():
        account = require_account(session, principal)
        context(session, account.id, data, secret)
        return account.id, account.generation


def execute_one(factory, owner, generation, data, operation, secret):
    for attempt in range(3):
        try:
            with factory() as session, session.begin():
                result = apply_operation(session, owner, data, operation, secret, generation)
                now = database_now(session)
            return result, now
        except SQLAlchemyError as error:
            code = getattr(getattr(error, "orig", None), "sqlstate", None)
            if code not in {"40001", "40P01"} or attempt == 2:
                raise SyncFailure(503, "service_unavailable") from None


@router.post(
    "/push",
    response_model=PushResponse,
    responses=ERRORS,
    operation_id="sync_push",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": expanded_schema("PushRequest")}},
        }
    },
    description="Full bounded preflight, then one commit per operation; ACK only after commit.",
)
async def push(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    data = await read_push(request)
    preflight_structure(data)
    factory, secret = request.app.state.session_factory, request.app.state.catalog_page_token_secret
    try:
        owner, generation = await run_in_threadpool(preflight, factory, principal, data, secret)
        results, now = [], None
        for operation in data["operations"]:
            # A later provider/session failure does not undo the committed prefix.
            try:
                verified = await request.app.state.oidc_verifier.verify(
                    request.headers["authorization"].split(" ", 1)[1]
                )
            except AuthFailure as error:
                raise SyncFailure(error.status, error.code) from None
            if (verified.issuer, verified.subject) != (principal.issuer, principal.subject):
                raise SyncFailure(401, "unauthorized")
            if "user" not in verified.roles:
                raise SyncFailure(403, "forbidden")
            result, now = await run_in_threadpool(
                execute_one, factory, owner, generation, data, operation, secret
            )
            results.append(result)
        return {"sync_epoch": data["sync_epoch"], "server_time": utc_text(now), "results": results}
    except SQLAlchemyError:
        raise SyncFailure(503, "service_unavailable") from None


@router.get(
    "/pull",
    response_model=PullResponse,
    responses=ERRORS,
    operation_id="sync_pull",
    openapi_extra={
        "parameters": [
            {"name": name, "in": "query", "required": False, "schema": {"type": "string"}}
            for name in ("sync_epoch", "checkpoint", "snapshot_token", "page_token")
        ]
        + [
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 500},
            },
            {
                "name": "recovery_operation_ids",
                "in": "query",
                "style": "form",
                "explode": True,
                "schema": {
                    "type": "array",
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": {"type": "string", "format": "uuid"},
                },
            },
        ]
    },
)
def pull(request: Request, principal: Annotated[Principal, Depends(current_principal)]):
    query = {}
    for key, value in request.query_params.multi_items():
        if key == "recovery_operation_ids":
            query.setdefault(key, []).append(value)
        elif key in query:
            raise SyncFailure(422, "invalid_request")
        else:
            query[key] = value
    if "limit" in query:
        value = query["limit"]
        if not value.isascii() or not value.isdigit():
            raise SyncFailure(422, "invalid_request")
        if len(value) > 3:
            raise SyncFailure(422, "invalid_request")
        query["limit"] = int(value)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            owner = UUID(str(account.id))
        return pull_service(
            request.app.state.session_factory,
            owner,
            query,
            request.app.state.catalog_page_token_secret,
        )
    except SQLAlchemyError:
        raise SyncFailure(503, "service_unavailable") from None
