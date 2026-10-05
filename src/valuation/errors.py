"""labs API error shape — the same as trading-engine's API server so trading-ui reads both alike.

    {"detail": "사람이 읽을 한 줄", "code": "unauthorized", "errors": [{"field": null, "message": "…"}]}
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
AUTH_NOT_CONFIGURED = "auth_not_configured"
UNAVAILABLE = "unavailable"
CONFIG = "config"
NOT_FOUND = "not_found"
CONFLICT = "conflict"
VALIDATION = "validation"


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.headers = status, code, detail, headers


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError) -> JSONResponse:
        body = {"detail": exc.detail, "code": exc.code, "errors": [{"field": None, "message": exc.detail}]}
        return JSONResponse(status_code=exc.status, content=body, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(part) for part in error["loc"] if part != "body") or None, "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=400, content={"detail": "요청 형식이 잘못됐습니다", "code": VALIDATION, "errors": errors})
