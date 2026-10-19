"""Each tenant's health (Phase 14 WS2 2.13).

``tenant_health(location)`` answers what an operator asks about one tenant
database: can the platform reach it, how long one round trip takes, and
whether its platform schema is at the version this code expects (a tenant
left behind by a migration run is "behind"). ``health_summary`` adds them up
over every tenant for the platform's own screens and alerts.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

__all__ = ["CHECK_TIMEOUT_SECONDS", "health_summary", "tenant_health"]

CHECK_TIMEOUT_SECONDS = 5.0


async def tenant_health(location: Any, *, target_version: Optional[str] = None) -> Dict[str, Any]:
    """``{"reachable", "latency_ms", "error", "schema_version", "target_version", "schema", "healthy"}``.

    ``schema`` is ``current``, ``behind`` (a migration has not reached it) or
    ``unknown`` (never migrated). A tenant whose database is not ready yet is
    reported as such without being connected to.
    """
    from src.common.tenancy.engines import engines
    from src.common.tenancy.migrate import tenant_schema_version

    target = target_version or tenant_schema_version()
    report: Dict[str, Any] = {
        "company_id": str(location.company_id), "tenant_key": location.key, "status": location.status,
        "database": location.db_name, "server": location.server_host,
        "schema_version": location.schema_version, "target_version": target,
        "schema": ("unknown" if not location.schema_version
                   else "current" if location.schema_version == target else "behind"),
        "reachable": None, "latency_ms": None, "error": None,
    }
    if not location.database_ready:
        report["healthy"] = False
        report["error"] = f"database not ready ({location.status})"
        return report
    started = time.perf_counter()
    try:
        async def ping() -> None:
            async with engines.get(location).connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(ping(), timeout=CHECK_TIMEOUT_SECONDS)
        report["reachable"] = True
        report["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    except Exception as exc:  # noqa: BLE001 - the report is the answer
        report["reachable"] = False
        report["error"] = (f"no answer in {CHECK_TIMEOUT_SECONDS:g}s" if isinstance(exc, asyncio.TimeoutError)
                           else f"{type(exc).__name__}: {exc}")[:500]
    report["healthy"] = bool(report["reachable"]) and report["schema"] == "current"
    return report


def health_summary(reports: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    reports = list(reports)
    unreachable: List[str] = [r["tenant_key"] for r in reports if r["reachable"] is False]
    behind: List[str] = [r["tenant_key"] for r in reports if r["schema"] == "behind"]
    return {"tenants": len(reports), "healthy": sum(1 for r in reports if r.get("healthy")),
            "unreachable": unreachable, "schema_behind": behind}
