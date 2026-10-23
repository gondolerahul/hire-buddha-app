"""What apps and databases cost a business (Phase 14 WS6 6.12, tech spec §11.7).

* **Hourly** (:func:`meter_hour`, cron ``app_hosting_metering``): for each
  app, the hour's vCPU-hours and GB-hours of what its pods *requested* and the
  GB it sent out — from managed Prometheus on AKS (``PROMETHEUS_QUERY_URL``),
  else from the deployments that ran in the hour and their requested
  resources (local) — kept in ``app_usage`` (once per app and hour) and
  billed as ``app-hosting-vcpu-hour``, ``app-hosting-gb-hour``,
  ``app-egress-gb``.
* **Daily** (:func:`meter_databases`, cron ``tenant_db_metering``): each
  business's share of its database server — ``tenant-db-pool-share`` (the
  pool server's daily price split among its tenants) or
  ``tenant-db-dedicated`` (the whole price).

The SKUs are registry rows of the platform company (``scripts/seed_app_skus.py``);
without one, the use is recorded in ``app_usage`` and nothing is billed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from src.billing.units import Dimension

logger = logging.getLogger(__name__)

SKU_VCPU = "app-hosting-vcpu-hour"
SKU_MEMORY = "app-hosting-gb-hour"
SKU_EGRESS = "app-egress-gb"
SKU_DB_POOL = "tenant-db-pool-share"
SKU_DB_DEDICATED = "tenant-db-dedicated"
PROMETHEUS_SCOPE = "https://prometheus.monitor.azure.com/.default"


async def prometheus_query(promql: str, *, at: Optional[datetime] = None) -> Optional[float]:
    """One instant query's single value from managed Prometheus, or ``None``."""
    import httpx

    from src.common.config import settings

    if not settings.PROMETHEUS_QUERY_URL:
        return None
    from src.common.platform.identity import get_token_source

    params: Dict[str, Any] = {"query": promql}
    if at is not None:
        params["time"] = at.replace(microsecond=0).isoformat() + "Z"
    token = await get_token_source().token(PROMETHEUS_SCOPE)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{settings.PROMETHEUS_QUERY_URL.rstrip('/')}/api/v1/query", params=params,
                                    headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    result = (response.json().get("data") or {}).get("result") or []
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def _pods(app_name: str) -> str:
    return f"{app_name}(-pr[0-9]+|-preview)?-[a-z0-9]+-[a-z0-9]+"


async def _from_prometheus(namespace: str, app_name: str, end: datetime) -> Dict[str, float]:
    selector = f'namespace="{namespace}",pod=~"{_pods(app_name)}"'
    cpu = await prometheus_query(
        f'avg_over_time(sum(kube_pod_container_resource_requests{{{selector},resource="cpu"}})[1h:5m])', at=end)
    memory = await prometheus_query(
        f'avg_over_time(sum(kube_pod_container_resource_requests{{{selector},resource="memory"}})[1h:5m])', at=end)
    egress = await prometheus_query(f"sum(increase(container_network_transmit_bytes_total{{{selector}}}[1h]))", at=end)
    return {"vcpu_hours": cpu or 0.0, "gb_hours": (memory or 0.0) / 1024 ** 3, "egress_gb": (egress or 0.0) / 1e9}


def _overlap(start: datetime, end: datetime, began: datetime, ended: Optional[datetime]) -> float:
    """Hours of [began, ended) inside [start, end)."""
    lo, hi = max(start, began), min(end, ended or end)
    return max(0.0, (hi - lo).total_seconds() / 3600)


async def _from_requests(db: Any, app: Any, start: datetime, end: datetime) -> Dict[str, float]:
    """Requested CPU and memory × the time a deployment ran in the hour (previews sleep: one replica)."""
    from src.apps.models import AppDeployment
    from src.apps.runtime import cores, gb

    rows = (await db.execute(select(AppDeployment).where(
        AppDeployment.app_id == app.id, AppDeployment.created_at < end,
        AppDeployment.status.in_(("active", "superseded", "stopped", "expired"))))).scalars().all()
    resources = app.resources or {}
    cpu, memory = cores(resources.get("cpu", "250m")), gb(resources.get("memory", "256Mi"))
    replicas = int(resources.get("replicas", 1))
    vcpu = mem = 0.0
    for row in rows:
        ended = None if row.status == "active" else row.updated_at
        hours = _overlap(start, end, row.created_at, ended)
        count = replicas if row.kind == "published" else 1
        vcpu += hours * cpu * count
        mem += hours * memory * count
    return {"vcpu_hours": vcpu, "gb_hours": mem, "egress_gb": 0.0}  # exact: no rounding (T1-5)


# What each SKU's quantity measures (Phase 15 T1-3): a SKU priced in another
# dimension is a unit mismatch, charged $0 and flagged, not mis-billed.
SKU_DIMENSIONS = {
    SKU_VCPU: Dimension.VCPU_HOUR,
    SKU_MEMORY: Dimension.GB_HOUR,
    SKU_EGRESS: Dimension.GB,
    SKU_DB_POOL: Dimension.DAY,
    SKU_DB_DEDICATED: Dimension.DAY,
}


async def _bill(company_id: Any, sku: str, quantity: Any, metadata: Dict[str, Any]) -> None:
    if quantity <= 0:
        return
    from src.ai.services.cost_attribution import CostAttribution
    from src.ai.usage_service import UsageService
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        await UsageService(cdb).log_usage(company_id=uuid.UUID(str(company_id)), service_sku=sku,
                                          raw_quantity=quantity, metadata=metadata, dimension=SKU_DIMENSIONS[sku],
                                          attribution=CostAttribution.HOSTING.value)


async def meter_hour(company_id: Any, window_start: datetime, *, source: Optional[str] = None) -> List[Dict[str, Any]]:
    """Meter one business's apps for the hour starting ``window_start`` (once per app and hour)."""
    from src.apps.db import app_session
    from src.apps.models import App, AppUsage
    from src.common.tenancy.directory import directory

    start = window_start.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    location = await directory.find(company_id)
    if location is None or not location.database_ready:
        return []
    from src.common.config import settings

    source = source or ("prometheus" if settings.PROMETHEUS_QUERY_URL else "requests")
    out = []
    async with app_session(company_id) as db:
        apps = (await db.execute(select(App).where(App.company_id == uuid.UUID(str(company_id)),
                                                   App.created_at < end))).scalars().all()
        for app in apps:
            if (await db.execute(select(AppUsage.id).where(AppUsage.app_id == app.id,
                                                           AppUsage.window_start == start))).first():
                continue
            if source == "prometheus":
                usage = await _from_prometheus(f"t-{location.key}", app.name, end)
            else:
                usage = await _from_requests(db, app, start, end)
            if not any(usage.values()):
                continue
            db.add(AppUsage(company_id=app.company_id, app_id=app.id, window_start=start, source=source,
                            vcpu_hours=Decimal(str(usage["vcpu_hours"])),
                            gb_hours=Decimal(str(usage["gb_hours"])),
                            egress_gb=Decimal(str(usage["egress_gb"]))))
            await db.commit()
            meta = {"app_id": str(app.id), "app": app.name, "window_start": start.isoformat() + "Z", "source": source}
            await _bill(company_id, SKU_VCPU, usage["vcpu_hours"], meta)
            await _bill(company_id, SKU_MEMORY, usage["gb_hours"], meta)
            await _bill(company_id, SKU_EGRESS, usage["egress_gb"], meta)
            out.append({"app": app.name, **usage})
    return out


async def meter_databases(day: datetime) -> Dict[str, int]:
    """Each business's share of its database server for ``day`` (once per business and day)."""
    from src.ai.orm.usage import UsageLog
    from src.common.tenancy.models import DATABASE_READY_STATUSES, TenantDbServer, TenantDirectoryEntry
    from src.common.tenancy.session import control_session
    from src.config.models import IntegrationRegistry

    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    billed = skipped = 0
    async with control_session() as cdb:
        rows = (await cdb.execute(select(TenantDirectoryEntry, TenantDbServer).join(
            TenantDbServer, TenantDbServer.id == TenantDirectoryEntry.server_id).where(
            TenantDirectoryEntry.status.in_(sorted(DATABASE_READY_STATUSES))))).all()
        per_server: Dict[uuid.UUID, int] = {}
        for entry, server in rows:
            per_server[server.id] = per_server.get(server.id, 0) + 1
        sku_ids = dict((await cdb.execute(select(IntegrationRegistry.service_sku, IntegrationRegistry.id).where(
            IntegrationRegistry.service_sku.in_((SKU_DB_POOL, SKU_DB_DEDICATED))))).all())
    for entry, server in rows:
        dedicated = server.kind == "dedicated"
        sku = SKU_DB_DEDICATED if dedicated else SKU_DB_POOL
        async with control_session() as cdb:
            done = (await cdb.execute(select(func.count()).select_from(UsageLog).where(
                UsageLog.company_id == entry.company_id, UsageLog.sku_id == sku_ids.get(sku),
                UsageLog.log_metadata["day"].astext == start.date().isoformat()))).scalar() if sku in sku_ids else 0
        if done:
            skipped += 1
            continue
        share = Decimal(1) if dedicated else Decimal(1) / per_server[server.id]  # exact (T1-5)
        await _bill(entry.company_id, sku, share, {"day": start.date().isoformat(), "server": server.name,
                                                   "tenants_on_server": per_server[server.id]})
        billed += 1
    return {"billed": billed, "skipped": skipped}
