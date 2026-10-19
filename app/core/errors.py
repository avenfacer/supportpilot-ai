import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An error with a stable, client-safe code and message."""

    def __init__(self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class NotFoundError(AppError):
    def __init__(self, message: str = "The requested resource was not found."):
        super().__init__("not_found", message, status.HTTP_404_NOT_FOUND)


class AuthenticationRequiredError(AppError):
    def __init__(self, message: str = "Customer authentication is required for this request."):
        super().__init__("authentication_required", message, status.HTTP_401_UNAUTHORIZED)


class ServiceUnavailableError(AppError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, status.HTTP_503_SERVICE_UNAVAILABLE)


def error_body(code: str, message: str) -> dict[str, dict[str, str | None]]:
    return {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.info("app_error", extra={"error_code": exc.code, "http_status": exc.http_status})
        return JSONResponse(status_code=exc.http_status, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Echo field locations and messages only; never echo the submitted input values.
        fields = [
            {"loc": ".".join(str(p) for p in err.get("loc", ())), "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ]
        body = error_body("validation_error", "The request is invalid.")
        return JSONResponse(
            status_code=422,
            content={**body, "fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = (
            "The requested resource was not found." if exc.status_code == 404 else "Request failed."
        )
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "An unexpected error occurred. Please try again."),
        )
