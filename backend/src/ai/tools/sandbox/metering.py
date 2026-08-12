"""
ai.tools.sandbox.metering — sandbox runtime cost attribution (Phase 12 `02` S6).

Every sandbox exec / browser session is metered against the ``sandbox`` cost
attribution so the cost dashboard can break out how much agent runtime is spent
in the sandbox substrate (host subprocess or per-tenant container).

Time is billed against the ``settings.SANDBOX_COST_SKU`` IntegrationRegistry SKU
(cost_unit ``second``, owned by the APP company — seed it with
``scripts/seed_sandbox_sku.py``). When the SKU is absent ``UsageService`` logs a
warning and records nothing, exactly like embedding cost before its SKU existed —
metering never raises into the tool path.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


async def meter_sandbox_usage(
    context: Optional[Mapping[str, Any]],
    *,
    duration_ms: int,
    runtime_name: str,
    kind: str = "exec",
) -> None:
    """Record sandbox runtime time as an attributed usage row. Best-effort.

    Needs ``company_id`` in ``context`` and a positive duration; ``run_id`` links
    the charge to the execution. Uses its own DB session (the tool's request
    transaction is not in scope here) and swallows every error.
    """
    if not context:
        return
    company_id = context.get("company_id")
    if not company_id or duration_ms <= 0:
        return
    seconds = round(duration_ms / 1000.0, 6)
    if seconds <= 0:
        return
    run_id = context.get("run_id")
    try:
        from src.ai.services.cost_attribution import CostAttribution
        from src.ai.usage_service import UsageService
        from src.common.config import settings
        from src.common.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await UsageService(db).log_usage(
                company_id=UUID(str(company_id)),
                service_sku=getattr(settings, "SANDBOX_COST_SKU", "sandbox-runtime"),
                raw_quantity=seconds,
                execution_id=UUID(str(run_id)) if run_id else None,
                metadata={
                    "sandbox_runtime": runtime_name,
                    "sandbox_kind": kind,
                    "duration_ms": int(duration_ms),
                },
                attribution=CostAttribution.SANDBOX.value,
            )
    except Exception as exc:  # noqa: BLE001 - metering must never break a tool
        logger.debug("sandbox usage metering skipped: %s", exc)
