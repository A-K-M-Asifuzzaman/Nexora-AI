from collections.abc import Mapping
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.context import request_id_var


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__("RESOURCE_NOT_FOUND", message, 404)


class PermissionDeniedError(AppError):
    def __init__(
        self, code: str = "PERMISSION_DENIED", message: str = "Permission denied."
    ) -> None:
        super().__init__(code, message, 403)


class ConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 409)


class AuthenticationError(AppError):
    def __init__(
        self, code: str = "TOKEN_INVALID", message: str = "Authentication failed."
    ) -> None:
        super().__init__(code, message, 401)


class DomainValidationError(AppError):
    def __init__(self, code: str = "VALIDATION_ERROR", message: str = "Validation failed.") -> None:
        super().__init__(code, message, 422)


class BusinessRuleViolation(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 422)


class RateLimitedError(AppError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "RATE_LIMITED",
            "Too many requests. Please try again later.",
            429,
            {"retry_after": retry_after},
        )


class ExternalServiceError(AppError):
    def __init__(self, message: str = "A required service is unavailable.") -> None:
        super().__init__("SERVICE_UNAVAILABLE", message, 503)


def _payload(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": dict(details or {})},
        "request_id": request_id_var.get(),
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_payload("VALIDATION_ERROR", "Request validation failed.", {"errors": errors}),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        structlog.get_logger(__name__).exception(
            "unhandled_request_error",
            request_id=request_id_var.get(),
            exception_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=_payload("INTERNAL_ERROR", "An unexpected error occurred."),
        )
