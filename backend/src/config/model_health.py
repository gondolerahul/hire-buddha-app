"""Whether the platform can run an agent at all (LP-10): the ``models`` block of
``GET /api/v1/health``.

A fresh install has no ``model_task_defaults``; every run then fails with "No
model configured", and nothing pointed the operator at the fix. The health
endpoint now says which of the task types a run needs have no platform
default with an active integration.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Every run's steps resolve text_generation, and its planner thinking.
REQUIRED_TASK_TYPES = ("text_generation", "thinking")

# What the "No model configured" error and the health block tell the operator.
HOW_TO_CONFIGURE = ("An app admin sets it on the AI Model Configuration page (/ai-config); "
                    "a fresh install seeds the platform defaults with "
                    "db-scripts/seed_integration_registry.py.")


async def _configured() -> set[str]:
    from src.auth.platform import platform_company_id
    from src.common.database import AsyncSessionLocal
    from src.config.models import IntegrationRegistry, ModelTaskDefault

    async with AsyncSessionLocal() as db:
        app_id = await platform_company_id(db)
        if app_id is None:
            return set()
        return set((await db.execute(
            select(ModelTaskDefault.task_type)
            .join(IntegrationRegistry, IntegrationRegistry.id == ModelTaskDefault.integration_id)
            .where(ModelTaskDefault.company_id == app_id,
                   ModelTaskDefault.task_type.in_(REQUIRED_TASK_TYPES),
                   IntegrationRegistry.status == "active")
        )).scalars())


async def model_status() -> dict:
    """``{"status": "ok" | "missing" | "unknown", "missing": [...]}``; ``unknown``
    when the database does not answer within two seconds."""
    try:
        configured = await asyncio.wait_for(_configured(), timeout=2)
    except Exception as exc:                                               # noqa: BLE001
        logger.warning("model status unavailable: %s", exc)
        return {"status": "unknown", "missing": []}
    missing = [t for t in REQUIRED_TASK_TYPES if t not in configured]
    if not missing:
        return {"status": "ok", "missing": []}
    return {"status": "missing", "missing": missing, "fix": HOW_TO_CONFIGURE}
