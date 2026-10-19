"""What a request is told when its tenant database cannot be opened (Phase 14 WS2 2.9).

With ``TENANCY_MODE=split`` a route opens the caller's tenant database. A
company still being provisioned (``TenantNotReady``) or one with no database
(``TenantNotFound``) gets a 503 with a code the screens recognise —
``workspace_not_ready`` (retry shortly; ``GET /api/v1/workspace`` shows the
steps) or ``workspace_not_provisioned`` — instead of a 500.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.common.tenancy.directory import TenantNotFound, TenantNotReady
from src.common.tenancy.session import TenantRequired

RETRY_AFTER_SECONDS = 10


async def _not_ready(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, headers={"Retry-After": str(RETRY_AFTER_SECONDS)}, content={
        "code": "workspace_not_ready",
        "detail": "Your workspace is still being set up. Try again in a few seconds.",
    })


async def _not_provisioned(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "code": "workspace_not_provisioned",
        "detail": "This workspace has no database yet. Platform staff can set it up.",
    })


def install_tenancy_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TenantNotReady, _not_ready)
    app.add_exception_handler(TenantNotFound, _not_provisioned)
    app.add_exception_handler(TenantRequired, _not_provisioned)
