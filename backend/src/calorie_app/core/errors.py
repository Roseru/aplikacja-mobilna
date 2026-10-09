from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException


class ApiError(BaseModel):
    code: str
    message: str
    details: dict
    request_id: str


def error_response(
    request: Request, status: int, code: str, message: str, headers: dict | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content=ApiError(
            code=code, message=message, details={}, request_id=request.state.request_id
        ).model_dump(),
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            410: "gone",
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
