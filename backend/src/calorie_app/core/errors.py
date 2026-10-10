from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException


class DomainError(Exception):
    """Safe domain rejection. Details contain only controlled protocol metadata."""

    def __init__(self, status: int, code: str, details: list[dict] | None = None):
        self.status = status
        self.code = code
        self.details = details or []
        super().__init__(code)


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str = Field(min_length=1, max_length=1000)
    details: list[ErrorDetail] = Field(max_length=100)
    request_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    headers: dict | None = None,
    details: list[dict] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content=ApiError(
            code=code, message=message, details=details or [], request_id=request.state.request_id
        ).model_dump(),
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        headers = {"Retry-After": "5"} if error.status == 503 else None
        if error.status == 401:
            headers = {"WWW-Authenticate": "Bearer"}
        return error_response(
            request, error.status, error.code, "Nie można wykonać żądania.", headers, error.details
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "version_conflict",
            410: "page_expired",
            413: "request_too_large",
            422: "invalid_request",
            429: "rate_limited",
            503: "service_unavailable",
        }
        return error_response(
            request,
            error.status_code,
            codes.get(error.status_code, "request_failed"),
            "Nie można wykonać żądania.",
            error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _: RequestValidationError) -> JSONResponse:
        # Pydantic errors can contain passwords or raw input. Do not echo them.
        return error_response(request, 422, "invalid_request", "Niepoprawne dane żądania.")
