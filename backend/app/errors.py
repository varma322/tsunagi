from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 422 is spelled literally: Starlette renamed its constant and importing either
# spelling ties this module to a single Starlette version.
HTTP_422 = 422

_STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    HTTP_422: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
}


class ApiError(StarletteHTTPException):
    """HTTP error carrying the machine-readable code used in the response envelope."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code


def unauthorized(message: str = "Invalid or expired token.") -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "unauthorized",
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(message: str) -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def not_found(message: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "not_found", message)


def bad_request(message: str) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, "bad_request", message)


def _envelope(code: str, message: str, status_code: int, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = getattr(exc, "code", None) or _STATUS_CODES.get(exc.status_code, "error")
        return _envelope(code, str(exc.detail), exc.status_code, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = first.get("msg", "Request validation failed.")
        if location:
            message = f"{location}: {message}"
        return _envelope("validation_error", message, HTTP_422)
