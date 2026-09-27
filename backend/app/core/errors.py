from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, extra=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.extra = extra


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class InsufficientStock(Conflict):
    code = "insufficient_stock"


class IdempotentReplay(Exception):
    """Raised by the idempotency dependency to short-circuit with a stored response."""

    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self.body = body


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    body = {"detail": exc.message, "code": exc.code}
    if exc.extra is not None:
        body["extra"] = exc.extra
    return JSONResponse(status_code=exc.status_code, content=body)


async def replay_handler(_: Request, exc: IdempotentReplay) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body, headers={"Idempotent-Replay": "true"})
