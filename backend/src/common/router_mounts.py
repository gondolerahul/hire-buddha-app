"""Optional routers: mount them, or record why they could not be mounted.

A router whose module fails to import is left out so the rest of the API still
boots. The failure is kept on ``app.state.unmounted_routers`` and reported by
``GET /api/v1/health`` (PO-10) — before, a broken import showed up only as a
404 on every route of that router and a warning line in the startup log.
"""
import importlib
import logging

from fastapi import APIRouter, FastAPI, Request

logger = logging.getLogger(__name__)


def _describe(exc: ImportError) -> str:
    """The error without the file path an ImportError message can carry."""
    message = str(exc)
    if exc.path:
        message = message.replace(f" ({exc.path})", "")
    return f"{type(exc).__name__}: {message}"


def mount_optional(app: FastAPI, module: str, prefix: str = "") -> bool:
    """Include ``module.router`` in ``app``; on an ImportError, record it and go on."""
    if not hasattr(app.state, "unmounted_routers"):
        app.state.unmounted_routers = []
    try:
        router = importlib.import_module(module).router
    except ImportError as exc:
        logger.error("Router %s not mounted; its routes will 404", module, exc_info=True)
        app.state.unmounted_routers.append({"router": module, "error": _describe(exc)})
        return False
    app.include_router(router, prefix=prefix)
    return True


health_router = APIRouter(tags=["health"])


@health_router.get("/api/v1/health")
async def health(request: Request) -> dict:
    """Liveness plus the routers that failed to mount.

    Always 200: every replica runs the same code, so a 503 here would pull all
    of them out of rotation for one broken feature area. ``status`` says
    ``degraded`` instead. The path sits under ``/api/v1`` because the gateway
    answers ``/health`` itself and only proxies other paths here.
    """
    unmounted = getattr(request.app.state, "unmounted_routers", [])
    return {"status": "degraded" if unmounted else "ok", "unmounted_routers": unmounted}
