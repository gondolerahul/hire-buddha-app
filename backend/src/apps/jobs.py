"""Tenant runtime jobs on the main worker (Phase 14 WS6).

* ``run_review_checks`` — a pull request's checks (code lanes, 6.3).
* ``build_app`` — one queued app build (6.7).
* ``app_hosting_metering`` — hourly: the last full hour of every business's apps (6.12).
* ``tenant_db_metering`` — daily: each business's database share for yesterday (6.12).
* ``expire_app_previews`` — hourly: previews past ``APP_PREVIEW_DAYS`` stop (6.9).
* ``sandbox_idle_reaper`` — every 5 minutes on AKS: idle sandbox pods are saved and deleted (6.1).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def run_review_checks(ctx: Dict[str, Any], review_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
    from src.code_lanes.service import run_review_checks as run

    return await run(company_id, review_id)


async def build_app(ctx: Dict[str, Any], build_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
    from src.apps.service import run_build

    return await run_build(company_id, build_id)


async def _businesses_with_apps() -> list:
    from src.common.tenancy.directory import directory

    return await directory.ready_company_ids()


async def app_hosting_metering(ctx: Dict[str, Any]) -> Dict[str, Any]:
    from src.apps.metering import meter_hour

    hour = (datetime.utcnow() - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    totals = {"apps": 0, "errors": 0}
    for company_id in await _businesses_with_apps():
        try:
            totals["apps"] += len(await meter_hour(company_id, hour))
        except Exception:  # noqa: BLE001 - one business does not stop the rest
            logger.exception("hosting metering failed for %s", company_id)
            totals["errors"] += 1
    return totals


async def tenant_db_metering(ctx: Dict[str, Any]) -> Dict[str, int]:
    from src.apps.metering import meter_databases

    return await meter_databases(datetime.utcnow() - timedelta(days=1))


async def expire_app_previews(ctx: Dict[str, Any]) -> Dict[str, int]:
    from src.apps.service import expire_previews

    totals = {"expired": 0, "errors": 0}
    for company_id in await _businesses_with_apps():
        try:
            totals["expired"] += await expire_previews(company_id)
        except Exception:  # noqa: BLE001
            logger.exception("preview expiry failed for %s", company_id)
            totals["errors"] += 1
    return totals


async def sandbox_idle_reaper(ctx: Dict[str, Any]) -> Dict[str, int]:
    from src.common.config import settings

    if (settings.SANDBOX_RUNTIME or "").lower() != "kubernetes":
        return {"skipped": 1}
    from src.ai.tools.sandbox.k8s_runtime import reap_idle

    return await reap_idle()
