from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from calorie_app.core.errors import ApiError, error_response

EXPECTED_REVISION = "0001_foundation"
router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str = "ok"


@router.get("/health/live", response_model=Health)
def live() -> Health:
    return Health()


@router.get("/health/ready", response_model=Health, responses={503: {"model": ApiError}})
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            version = connection.scalar(text("SHOW server_version_num"))
            revisions = set(connection.scalars(text("SELECT version_num FROM app.alembic_version")))
            if not 170000 <= int(version) < 180000 or revisions != {EXPECTED_REVISION}:
                return error_response(request, 503, "service_unavailable", "Baza nie jest gotowa.")
    except (SQLAlchemyError, OSError):
        return error_response(request, 503, "service_unavailable", "Baza nie jest gotowa.")
    return Health()
