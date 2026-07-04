"""
Domain exceptions + the single global handler that maps them to HTTP.

The layering rule: services and repositories raise these framework-agnostic
errors; they never import FastAPI or raise HTTPException. Exactly one place —
`register_exception_handlers(app)` — knows how to turn them into HTTP responses,
so routers stay thin (no try/except HTTPException, no status-code logic).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base for all domain errors. Subclasses set status_code + a default detail."""
    status_code: int = 500
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None, *, status_code: int | None = None):
        if detail is not None:
            self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    detail = "Not found"


class ConflictError(AppError):
    status_code = 409
    detail = "Already exists"


class ForbiddenError(AppError):
    status_code = 403
    detail = "Forbidden"


class BadRequestError(AppError):
    status_code = 400
    detail = "Invalid request"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        # 5xx is worth logging; 4xx is expected client error.
        if exc.status_code >= 500:
            logger.exception("Unhandled AppError: %s", exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
