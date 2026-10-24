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
* **Daily** (:func:`meter_storage`, cron ``tenant_storage_metering``; Phase 15
  T7-3, tech design §9): what a business keeps, sampled once a day and billed
  as that day's share of a month (size ÷ days in the month) —
  ``app-storage-gb-month`` (build logs, SBOMs and app files under
  ``<namespace>/apps/``), ``tenant-db-storage-gb-month`` (its database's size,
  split mode), ``tenant-backup-gb-month`` (the kept weekly exports, D45) — and
  ``custom-domain-month`` for each verified custom domain.
* **Per build** (:func:`bill_build`): ``app-build-second`` × the build's
  duration (replaces ``APP_BUILD_COST_PER_SECOND``).

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
SKU_BUILD = "app-build-second"
SKU_APP_STORAGE = "app-storage-gb-month"
SKU_DB_STORAGE = "tenant-db-storage-gb-month"
SKU_BACKUP = "tenant-backup-gb-month"
SKU_DOMAIN = "custom-domain-month"
GB = Decimal(1024 ** 3)
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
    SKU_BUILD: Dimension.SECOND,
    SKU_APP_STORAGE: Dimension.GB_MONTH,
    SKU_DB_STORAGE: Dimension.GB_MONTH,
    SKU_BACKUP: Dimension.GB_MONTH,
    SKU_DOMAIN: Dimension.MONTH,
}


async def _bill(company_id: Any, sku: str, quantity: Any, metadata: Dict[str, Any]) -> Optional[Any]:
    """Log the use (settled with the company's standalone usage, §6.5); the usage row, or ``None``."""
    if quantity <= 0:
        return None
    from src.ai.services.cost_attribution import CostAttribution
    from src.ai.usage_service import UsageService
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        return await UsageService(cdb).log_usage(company_id=uuid.UUID(str(company_id)), service_sku=sku,
                                                 raw_quantity=quantity, metadata=metadata,
                                                 dimension=SKU_DIMENSIONS[sku],
                                                 attribution=CostAttribution.HOSTING.value)


async def bill_build(company_id: Any, build: Any, app_name: str) -> Decimal:
    """A finished build's seconds as ``app-build-second`` usage; the cost to show on the build."""
    try:
        row = await _bill(company_id, SKU_BUILD, Decimal(int(build.duration_seconds or 0)),
                          {"build_id": str(build.id), "app_id": str(build.app_id), "app": app_name,
                           "commit_sha": build.commit_sha})
    except Exception:  # noqa: BLE001 - the build's result stands; the usage is logged by the next build
        logger.warning("build %s not billed", build.id, exc_info=True)
        return Decimal(0)
    return Decimal(str(row.calculated_cost)) if row is not None and row.calculated_cost is not None else Decimal(0)


def _month_share(day: datetime) -> Decimal:
    """One day as a fraction of its month (a GB-month sampled daily, §9)."""
    import calendar

    return Decimal(1) / calendar.monthrange(day.year, day.month)[1]


async def _sampled(company_id: Any, sku_ids: Dict[str, Any], sku: str, day: str) -> bool:
    """Whether ``sku`` was already logged for the company and day (the job is idempotent)."""
    from src.ai.orm.usage import UsageLog
    from src.common.tenancy.session import control_session

    if sku not in sku_ids:
        return False
    async with control_session() as cdb:
        return bool((await cdb.execute(select(func.count()).select_from(UsageLog).where(
            UsageLog.company_id == company_id, UsageLog.sku_id == sku_ids[sku],
            UsageLog.log_metadata["day"].astext == day))).scalar())


async def _stored_bytes(prefix: str) -> int:
    from src.common.platform.storage import get_storage

    storage = get_storage()
    total = 0
    for key in await storage.list(prefix):
        total += await storage.size(key) or 0
    return total


async def _database_bytes(company_id: Any) -> int:
    """The business's own database (split mode); in single mode there is no database of its own to size."""
    from sqlalchemy import text

    from src.common.config import settings
    from src.common.tenancy.session import tenant_session

    if settings.TENANCY_MODE != "split":
        return 0
    async with tenant_session(company_id) as db:
        return int((await db.execute(text("SELECT pg_database_size(current_database())"))).scalar() or 0)


async def meter_storage(day: datetime) -> Dict[str, int]:
    """What each business keeps on ``day``: app files, its database, its backups, its custom domains."""
    from src.apps.models import CustomDomain
    from src.common.tenancy.directory import directory
    from src.common.tenancy.session import control_session
    from src.config.models import IntegrationRegistry

    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    stamp = start.date().isoformat()
    share = _month_share(start)
    skus = (SKU_APP_STORAGE, SKU_DB_STORAGE, SKU_BACKUP, SKU_DOMAIN)
    async with control_session() as cdb:
        sku_ids = dict((await cdb.execute(select(IntegrationRegistry.service_sku, IntegrationRegistry.id).where(
            IntegrationRegistry.service_sku.in_(skus)))).all())
        domains = dict((await cdb.execute(select(CustomDomain.company_id, func.count()).where(
            CustomDomain.status == "verified", CustomDomain.created_at < start + timedelta(days=1))
            .group_by(CustomDomain.company_id))).all())
    out = {"billed": 0, "skipped": 0, "errors": 0}
    for company_id in await directory.ready_company_ids():
        location = await directory.find(company_id)
        if location is None:
            continue
        namespace = f"t-{location.key}"
        try:
            measures = {
                SKU_APP_STORAGE: lambda: _stored_bytes(f"{namespace}/apps/"),
                SKU_DB_STORAGE: lambda: _database_bytes(company_id),
                SKU_BACKUP: lambda: _stored_bytes(f"{namespace}/backups/"),
            }
            for sku, measure in measures.items():
                if await _sampled(company_id, sku_ids, sku, stamp):
                    out["skipped"] += 1
                    continue
                size = await measure()
                gb = Decimal(size) / GB
                if await _bill(company_id, sku, gb * share, {"day": stamp, "bytes": size}):
                    out["billed"] += 1
            count = int(domains.get(uuid.UUID(str(company_id)), 0) or 0)
            if count and not await _sampled(company_id, sku_ids, SKU_DOMAIN, stamp):
                if await _bill(company_id, SKU_DOMAIN, Decimal(count) * share, {"day": stamp, "domains": count}):
                    out["billed"] += 1
        except Exception:  # noqa: BLE001 - one business does not stop the rest
            logger.exception("storage metering failed for %s", company_id)
            out["errors"] += 1
    return out


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
