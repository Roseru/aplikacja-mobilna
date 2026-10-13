"""Private online energy analyses and immutable estimate history."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.energy import repository, service
from calorie_app.modules.energy.schemas import (
    AffirmRead,
    AffirmRequest,
    AnalysisPage,
    AnalysisRead,
    AnalysisRequest,
    DecisionRequest,
    EnergyEntity,
    EnergyState,
    HistoryPage,
    RevertRequest,
    UnavailableRead,
)
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.router import idempotency_key
from calorie_app.modules.identity.service import require_account

router = APIRouter(prefix="/api/v1/me/energy", tags=["energy"])
ERRORS = {status: {"model": ApiError} for status in (401, 403, 404, 409, 410, 413, 422, 429, 503)}
PrincipalDep = Annotated[Principal, Depends(current_principal)]
KeyHeader = Annotated[str, Header(alias="Idempotency-Key")]


def _mutate(request, principal, key, kind, data):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            return service.mutate(
                session, principal, request.app.state.settings, idempotency_key(key), kind, data
            )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.post(
    "/analyses",
    responses=ERRORS,
    operation_id="energy_analysis_create",
    response_model=AnalysisRead | UnavailableRead,
)
def create(request: Request, data: AnalysisRequest, principal: PrincipalDep, key: KeyHeader):
    return _mutate(request, principal, key, "create", data)


@router.post(
    "/analyses/accept",
    responses=ERRORS,
    operation_id="energy_analysis_accept",
    response_model=EnergyEntity,
)
def accept(request: Request, data: DecisionRequest, principal: PrincipalDep, key: KeyHeader):
    return _mutate(request, principal, key, "accept", data)


@router.post(
    "/analyses/reject",
    responses=ERRORS,
    operation_id="energy_analysis_reject",
    response_model=AnalysisRead,
)
def reject(request: Request, data: DecisionRequest, principal: PrincipalDep, key: KeyHeader):
    return _mutate(request, principal, key, "reject", data)


@router.post(
    "/affirm", responses=ERRORS, operation_id="energy_baseline_affirm", response_model=AffirmRead
)
def affirm(request: Request, data: AffirmRequest, principal: PrincipalDep, key: KeyHeader):
    return _mutate(request, principal, key, "affirm", data)


@router.post(
    "/revert", responses=ERRORS, operation_id="energy_estimate_revert", response_model=EnergyEntity
)
def revert(request: Request, data: RevertRequest, principal: PrincipalDep, key: KeyHeader):
    return _mutate(request, principal, key, "revert", data)


@router.get(
    "/analyses/{analysis_id}",
    responses=ERRORS,
    operation_id="energy_analysis_read",
    response_model=AnalysisRead,
)
def read(request: Request, analysis_id: UUID, principal: PrincipalDep):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return repository.analysis(session, account.id, analysis_id)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get(
    "/analyses", responses=ERRORS, operation_id="energy_analysis_list", response_model=AnalysisPage
)
def analyses(
    request: Request, principal: PrincipalDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return {"items": repository.analyses(session, account.id, limit)}
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get("/history", responses=ERRORS, operation_id="energy_history", response_model=HistoryPage)
def history(
    request: Request,
    principal: PrincipalDep,
    after_revision: Annotated[int, Query(ge=0, le=2147483647)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            items = repository.history(session, account.id, limit, after_revision)
            return {
                "items": items,
                "next_revision": items[-1]["revision"] if items else after_revision,
            }
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None


@router.get("/state", responses=ERRORS, operation_id="energy_state", response_model=EnergyState)
def state(request: Request, principal: PrincipalDep):
    try:
        with Session(request.app.state.engine) as session, session.begin():
            account = require_account(session, principal)
            return repository.state(session, account.id)
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
