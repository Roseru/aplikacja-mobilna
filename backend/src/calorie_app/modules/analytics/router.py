"""Private statistics read transport; SQL and calculation stay in services."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import ApiError, DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.analytics.schemas import Statistics, StatisticsQuery
from calorie_app.modules.analytics.service import STATISTICS_STATEMENT_TIMEOUT_MS, statistics
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import require_account

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get(
    "/me/statistics",
    response_model=Statistics,
    operation_id="read_statistics",
    responses={
        200: {"headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}},
        **{
            status: {
                "model": ApiError,
                "headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}},
            }
            for status in (401, 403, 409, 422, 503)
        },
    },
    description="statistics_v1: exactly 7/30/90 profile-zone dates; today is preliminary. "
    "Each nutrient average has its own closed complete-day denominator. "
    "Historical correction-aware goal_band_v1, exact Decimal comparisons. "
    "as_of/server_position describe server state, never a sync checkpoint.",
)
def read_statistics(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    query: Annotated[StatisticsQuery, Query()],
):
    try:
        with request.app.state.engine.connect() as connection:
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with Session(connection) as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(
                    text(f"SET LOCAL statement_timeout = '{STATISTICS_STATEMENT_TIMEOUT_MS}ms'")
                )
                account = require_account(session, principal)
                return statistics(
                    session, account.id, query.days, expected_generation=account.generation
                )
    except SQLAlchemyError:
        raise DomainError(503, "service_unavailable") from None
