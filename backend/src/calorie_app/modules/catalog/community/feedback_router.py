"""Separate feedback reads and exact account-versioned vote/report writes."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.catalog.community.feedback import (
    change_vote,
    create_report,
    public_feedback,
)
from calorie_app.modules.catalog.community.idempotency import execute_mutation, outcome_response
from calorie_app.modules.catalog.community.repository import lock_catalog
from calorie_app.modules.catalog.community.schemas import (
    FeedbackDTO,
    ReportRequest,
    ReportResultDTO,
    VoteRequest,
    VoteResultDTO,
)
from calorie_app.modules.catalog.schemas import Uuid
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.router import idempotency_key
from calorie_app.modules.identity.service import current_epoch, require_account

router = APIRouter(prefix="/api/v1", tags=["feedback"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 404, 409, 413, 422, 429, 503)}


def vote_revision(value):
    """A distinct E6 parser accepts zero without loosening E3 If-Match."""
    if not isinstance(value, str) or re.fullmatch(r'"(0|[1-9][0-9]{0,9})"', value) is None:
        raise DomainError(422, "invalid_vote_revision")
    revision = int(value[1:-1])
    if revision > 2147483647:
        raise DomainError(422, "invalid_vote_revision")
    return revision


def mutate(request, principal, key, epoch, kind, semantic, action):
    operation_id, sync_epoch = idempotency_key(key), idempotency_key(epoch)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            outcome = execute_mutation(
                session,
                principal,
                kind,
                operation_id,
                sync_epoch,
                semantic,
                lambda account: action(session, account, operation_id),
            )
        return outcome_response(request, outcome)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/products/{id}/feedback",
    response_model=FeedbackDTO,
    operation_id="read_product_feedback",
    responses=ERRORS,
    description=(
        "Oddzielne plus/minus, własny głos i jego rewizja. Dostępne "
        "official/community; autorstwo oblicza serwer."
    ),
)
def feedback(
    request: Request, id: Uuid, principal: Annotated[Principal, Depends(current_principal)]
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            current_epoch(session)
            lock_catalog(session, shared=True)
            return public_feedback(session, account, id)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.put(
    "/products/{id}/vote",
    response_model=VoteResultDTO,
    operation_id="replace_product_vote",
    responses=ERRORS,
    description=(
        'Jeden własny głos1/-1. If-Match dotyczy wyłącznie mojego głosu; "0" '
        "oznacza brak. UUID Idempotency-Key i X-Sync-Epoch wymagane."
    ),
)
def vote(
    request: Request,
    id: Uuid,
    data: VoteRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
    expected: Annotated[str, Header(alias="If-Match")],
):
    revision = vote_revision(expected)
    return mutate(
        request,
        principal,
        key,
        epoch,
        "vote",
        {
            "method": "PUT",
            "path": f"/api/v1/products/{id}/vote",
            "expected_vote_revision": revision,
            "body": data.model_dump(mode="json"),
        },
        lambda session, account, operation: change_vote(
            session, account, id, revision, data.value, operation
        ),
    )


@router.delete(
    "/products/{id}/vote",
    response_model=VoteResultDTO,
    operation_id="withdraw_product_vote",
    responses=ERRORS,
    description=(
        "Wycofanie zachowuje własną rewizję/tombstone. Ten sam rejestr idempotencji "
        "co PUT; zmieniona metoda daje409."
    ),
)
def withdraw(
    request: Request,
    id: Uuid,
    principal: Annotated[Principal, Depends(current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
    expected: Annotated[str, Header(alias="If-Match")],
):
    revision = vote_revision(expected)
    return mutate(
        request,
        principal,
        key,
        epoch,
        "vote",
        {
            "method": "DELETE",
            "path": f"/api/v1/products/{id}/vote",
            "expected_vote_revision": revision,
            "body": None,
        },
        lambda session, account, operation: change_vote(
            session, account, id, revision, None, operation
        ),
    )


@router.post(
    "/products/{id}/reports",
    response_model=ReportResultDTO,
    status_code=201,
    operation_id="report_product",
    responses=ERRORS,
    description=(
        "Zgłoszenie dostępnej dokładnej wersji official lub community; "
        "potwierdzenie zawiera tylko report_id/revision/status."
    ),
)
def report(
    request: Request,
    id: Uuid,
    data: ReportRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key")],
    epoch: Annotated[str, Header(alias="X-Sync-Epoch")],
):
    return mutate(
        request,
        principal,
        key,
        epoch,
        "report",
        {
            "method": "POST",
            "path": f"/api/v1/products/{id}/reports",
            "body": data.model_dump(mode="json"),
        },
        lambda session, account, operation: create_report(session, account, id, data, operation),
    )
