"""The tenancy API (Phase 14 WS2 2.8, 2.9, 2.13).

    GET  /api/v1/workspace                              the caller's workspace: being set up, or ready
    GET  /api/v1/admin/tenants                          every tenant (``?health=true``: and each one's health)
    POST /api/v1/admin/tenants                          give a company its own database (request + provision)
    GET  /api/v1/admin/tenants/{company_id}             one tenant: its steps and its health
    POST /api/v1/admin/tenants/{company_id}/provision   run its remaining steps again (after a failure)
    GET  /api/v1/admin/tenant-servers                   the servers tenant databases live on

The admin routes are platform staff's (``app_admin``). Each endpoint carries
the capability annotations (PR-2). With ``TENANCY_MODE=single`` every company
works in the one shared database: the workspace is ready, and provisioning
gives a company a database nothing reads until the switch to ``split``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker, get_current_user
from src.auth.models import User
from src.automation.api import capability
from src.common.tenancy import health as health_mod
from src.common.tenancy import provisioner
from src.common.tenancy.session import get_control_db, is_split, tenancy_mode

router = APIRouter(tags=["Tenancy"])

staff_only = RoleChecker(["app_admin"])


class TenantRequest(BaseModel):
    company_id: UUID
    server: Optional[str] = Field(None, description="A server's name; default: the emptiest pool server with room")


def _entry_view(entry: Any, server: Any) -> Dict[str, Any]:
    return {"company_id": str(entry.company_id), "tenant_key": entry.tenant_key, "slug": entry.slug,
            "status": entry.status, "automation_state": entry.automation_state, "timezone": entry.timezone,
            "database": entry.db_name, "server": server.name if server else None,
            "platform_schema_version": entry.platform_schema_version,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None}


async def _location(company_id: Any) -> Any:
    from src.common.tenancy.directory import directory

    directory.invalidate(company_id)
    return await directory.find(company_id)


async def _enqueue(company_id: UUID) -> None:
    from src.common.job_queue import enqueue_job

    try:
        await enqueue_job("provision_tenant", str(company_id))
    except Exception as exc:  # noqa: BLE001 - the row is requested; a retry enqueues again
        raise HTTPException(status_code=503, detail=f"Provisioning could not be queued: {exc}")


@router.get("/api/v1/workspace", openapi_extra=capability(
    "Whether the caller's workspace is ready, or which setup steps are left.", "read", "any signed-in user"))
async def workspace(current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    if not is_split():
        return {"company_id": str(current_user.company_id), "mode": tenancy_mode(), "status": "active",
                "ready": True, "steps": []}
    view = await provisioner.provisioning_status(db, current_user.company_id)
    # A person sees what is being set up, not the servers or the errors behind it.
    steps = [{"step": s["step"], "outcome": s["outcome"]} for s in view["steps"]]
    return {"company_id": view["company_id"], "mode": tenancy_mode(), "status": view["status"],
            "ready": view["ready"], "steps": steps}


@router.get("/api/v1/admin/tenants", openapi_extra=capability(
    "Every tenant: its database, server, status and schema version; with health=true, whether each "
    "database answers and is at the current schema.", "read", "app_admin", scope="platform"))
async def list_tenants(health: bool = Query(False), _: User = Depends(staff_only),
                       db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry

    rows = (await db.execute(
        select(TenantDirectoryEntry, TenantDbServer)
        .join(TenantDbServer, TenantDbServer.id == TenantDirectoryEntry.server_id)
        .order_by(TenantDirectoryEntry.tenant_key)
    )).all()
    tenants = [_entry_view(entry, server) for entry, server in rows]
    result: Dict[str, Any] = {"mode": tenancy_mode(), "tenants": tenants}
    if health:
        import asyncio

        from src.common.tenancy.migrate import tenant_schema_version

        target = tenant_schema_version()
        locations = [await _location(entry.company_id) for entry, _server in rows]
        reports = await asyncio.gather(*(health_mod.tenant_health(loc, target_version=target)
                                         for loc in locations if loc is not None))
        by_company = {r["company_id"]: r for r in reports}
        for view in tenants:
            view["health"] = by_company.get(view["company_id"])
        result["health"] = health_mod.health_summary(reports)
    return result


@router.post("/api/v1/admin/tenants", status_code=202, openapi_extra=capability(
    "Give a company a database of its own: its tenant is requested and its provisioning queued.",
    "write_internal", "app_admin", scope="platform"))
async def add_tenant(body: TenantRequest, _: User = Depends(staff_only)) -> Dict[str, Any]:
    try:
        await provisioner.request_tenant(body.company_id, server_name=body.server)
    except provisioner.NoServerAvailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except provisioner.ProvisioningError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _enqueue(body.company_id)
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        return await provisioner.provisioning_status(db, body.company_id)


@router.get("/api/v1/admin/tenants/{company_id}", openapi_extra=capability(
    "One tenant: every provisioning step with its outcome and error, and its database's health.",
    "read", "app_admin", scope="platform"))
async def get_tenant(company_id: UUID, _: User = Depends(staff_only),
                     db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    view = await provisioner.provisioning_status(db, company_id)
    if view["status"] == "not_requested":
        raise HTTPException(status_code=404, detail="This company has no tenant database")
    location = await _location(company_id)
    view["health"] = await health_mod.tenant_health(location) if location is not None else None
    return view


@router.post("/api/v1/admin/tenants/{company_id}/provision", status_code=202, openapi_extra=capability(
    "Run a tenant's remaining provisioning steps again, from the last one that succeeded.",
    "write_internal", "app_admin", scope="platform"))
async def retry_tenant(company_id: UUID, _: User = Depends(staff_only),
                       db: AsyncSession = Depends(get_control_db)) -> Dict[str, Any]:
    view = await provisioner.provisioning_status(db, company_id)
    if view["status"] == "not_requested":
        raise HTTPException(status_code=404, detail="This company has no tenant requested")
    await _enqueue(company_id)
    return view


@router.get("/api/v1/admin/tenant-servers", openapi_extra=capability(
    "The servers tenant databases live on, with how many tenants each holds.", "read", "app_admin",
    scope="platform"))
async def list_servers(_: User = Depends(staff_only),
                       db: AsyncSession = Depends(get_control_db)) -> List[Dict[str, Any]]:
    from src.common.tenancy.models import TenantDbServer, TenantDirectoryEntry

    counts = dict((await db.execute(
        select(TenantDirectoryEntry.server_id, func.count())
        .where(TenantDirectoryEntry.status != "retired").group_by(TenantDirectoryEntry.server_id)
    )).all())
    servers = (await db.execute(select(TenantDbServer).order_by(TenantDbServer.name))).scalars().all()
    return [{"name": s.name, "host": s.host, "kind": s.kind, "region": s.region, "capacity": s.capacity,
             "status": s.status, "tenants": counts.get(s.id, 0)} for s in servers]
