"""Optional routers: mount them, or record why they could not be mounted.

A router whose module fails to import is left out so the rest of the API still
boots. The failure is kept on ``app.state.unmounted_routers`` and reported by
``GET /api/v1/health`` (PO-10) — before, a broken import showed up only as a
404 on every route of that router and a warning line in the startup log.
"""
import importlib
from typing import Optional
import logging

from fastapi import APIRouter, FastAPI, Request

from src.common.instance import instance_info
from src.common.worker_health import worker_status
from src.config.model_health import model_status

logger = logging.getLogger(__name__)


def _describe(exc: ImportError) -> str:
    """The error without the file path an ImportError message can carry."""
    message = str(exc)
    if exc.path:
        message = message.replace(f" ({exc.path})", "")
    return f"{type(exc).__name__}: {message}"


def mount_optional(app: FastAPI, module: str, prefix: str = "", feature: Optional[str] = None) -> bool:
    """Include ``module.router`` in ``app``; on an ImportError, record it and go on.

    ``feature``: every route of the router needs the plan feature (Phase 15 T6-2).
    """
    if not hasattr(app.state, "unmounted_routers"):
        app.state.unmounted_routers = []
    try:
        router = importlib.import_module(module).router
    except ImportError as exc:
        logger.error("Router %s not mounted; its routes will 404", module, exc_info=True)
        app.state.unmounted_routers.append({"router": module, "error": _describe(exc)})
        return False
    if feature:
        from fastapi import Depends

        from src.billing.features import require_feature
        app.include_router(router, prefix=prefix, dependencies=[Depends(require_feature(feature))])
    else:
        app.include_router(router, prefix=prefix)
    return True


health_router = APIRouter(tags=["health"])


@health_router.get("/api/v1/health")
@health_router.get("/health", include_in_schema=False)
async def health(request: Request) -> dict:
    """Liveness, the routers that failed to mount, whether a worker is consuming,
    and whether the platform has the model defaults a run needs.

    Always 200: every replica runs the same code, so a 503 here would pull all
    of them out of rotation for one broken feature area — or for a dead
    worker, which is not the API's fault. ``status`` says ``degraded``
    instead. ``/health`` is the path the gateway answered on before it was
    merged into the API; both paths return the same body.
    """
    from src.common.config import settings

    unmounted = getattr(request.app.state, "unmounted_routers", [])
    worker = await worker_status()
    models = await model_status()
    return {
        "status": "degraded" if unmounted or worker["status"] != "ok" or models["status"] == "missing" else "ok",
        "unmounted_routers": unmounted,
        # Live arq workers per queue, and the queue's due jobs (SA-I4).
        "worker": worker,
        # The platform defaults a run needs (LP-10).
        "models": models,
        # Configuration, not health: disabled until INTERNAL_TOKEN is a real secret.
        "internal_events": "enabled" if settings.internal_events_enabled else "disabled",
        # Which process answered: the API is one instance by decision (HD12, GW-21).
        "instance": instance_info(),
    }
