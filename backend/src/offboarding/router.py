"""Closing and deleting businesses over the API (docs/phase15/13 §4, §6.6, §10, §13).

Business (its admin): ``/api/v1/settings/offboarding`` — see, request, confirm,
cancel, download the export; ``/api/v1/settings/data-requests`` — find and erase
one person. A reselling partner: ``POST /api/v1/partner/tenants/{id}/offboarding``
(request only). Staff: ``/api/v1/admin/offboarding`` and the company routes —
request on a business's behalf, bring forward, retry a failed step, mark a test
business, and delete a test business at once (Flow B).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker, StaffChecker, get_current_user
from src.auth.models import User
from src.common.tenancy.session import get_control_db
from src.offboarding import service
from src.offboarding.models import CompanyOffboarding, OffboardingStepLog

router = APIRouter(tags=["Offboarding and erasure"])
tenant_admin = RoleChecker(["tenant_admin"])
app_admin = RoleChecker(["app_admin"])
support = StaffChecker("support")


class ClosureBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    export: bool = False


class PersonBody(BaseModel):
    query: str = Field(..., min_length=3, max_length=200)


class ImmediateBody(BaseModel):
    confirm_name: str = Field(..., min_length=1, max_length=300)
    reason: str = Field(..., min_length=3, max_length=500)
    include_test_tenants: bool = False


class TestBody(BaseModel):
    is_test: bool
    reason: str = Field(..., min_length=3, max_length=500)


async def _latest(db: AsyncSession, company_id: UUID) -> Optional[CompanyOffboarding]:
    return (await db.execute(select(CompanyOffboarding).where(CompanyOffboarding.company_id == company_id)
                             .order_by(CompanyOffboarding.created_at.desc()).limit(1))).scalar_one_or_none()


async def _log(db: AsyncSession, off: CompanyOffboarding) -> list:
    return list((await db.execute(select(OffboardingStepLog).where(OffboardingStepLog.offboarding_id == off.id)
                                  .order_by(OffboardingStepLog.created_at))).scalars().all())


# ── the business ────────────────────────────────────────────────────────────

@router.get("/api/v1/settings/offboarding")
async def my_offboarding(db: AsyncSession = Depends(get_control_db), user: User = Depends(tenant_admin)):
    off = await _latest(db, user.company_id)
    return {"offboarding": service.view(off) if off and off.state != "cancelled" else None,
            "remaining_credit": await service.remaining_credit(db, user.company_id),
            "grace_days": int(await service._setting(db, "offboarding.grace_days"))}


@router.post("/api/v1/settings/offboarding", status_code=201)
async def request_my_closure(body: ClosureBody, db: AsyncSession = Depends(get_control_db),
                             user: User = Depends(tenant_admin)):
    off = await service.request_closure(db, user.company_id, actor=user, reason=body.reason, export=body.export)
    return service.view(off)


@router.post("/api/v1/settings/offboarding/confirm")
async def confirm_my_closure(db: AsyncSession = Depends(get_control_db), user: User = Depends(tenant_admin)):
    return service.view(await service.confirm_closure(db, user.company_id, actor=user))


@router.delete("/api/v1/settings/offboarding")
async def cancel_my_closure(db: AsyncSession = Depends(get_control_db), user: User = Depends(tenant_admin)):
    return service.view(await service.cancel_closure(db, user.company_id, actor=user))


@router.get("/api/v1/settings/offboarding/export")
async def my_export(db: AsyncSession = Depends(get_control_db), user: User = Depends(tenant_admin)):
    from datetime import datetime

    from src.common.platform.storage import get_storage

    off = await _latest(db, user.company_id)
    if off is None or not off.export_key:
        raise HTTPException(status_code=404, detail="No export is ready")
    if off.export_expires_at and off.export_expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="The export has expired")
    storage = get_storage()
    url = await storage.signed_url(off.export_key, ttl_seconds=600, file_name=f"{off.company_ref}-export.zip",
                                   content_type="application/zip")
    if url:
        return {"url": url}
    return Response(content=await storage.get(off.export_key), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{off.company_ref}-export.zip"'})


@router.post("/api/v1/settings/data-requests/search")
async def find_person(body: PersonBody, user: User = Depends(tenant_admin)):
    from src.offboarding import person
    return await person.search(user.company_id, body.query)


@router.post("/api/v1/settings/data-requests/erase")
async def erase_person(body: PersonBody, user: User = Depends(tenant_admin)):
    from src.offboarding import person
    return await person.erase(user.company_id, body.query, actor=user)


# ── a reselling partner ─────────────────────────────────────────────────────

@router.post("/api/v1/partner/tenants/{tenant_id}/offboarding", status_code=201)
async def partner_requests_closure(tenant_id: UUID, body: ClosureBody, db: AsyncSession = Depends(get_control_db),
                                   user: User = Depends(RoleChecker(["partner_admin"]))):
    from src.partners.scope import data_scope

    if tenant_id not in await data_scope(db, user.company_id):
        raise HTTPException(status_code=403, detail="Only a business you resell")
    return service.view(await service.request_closure(db, tenant_id, actor=user, reason=body.reason,
                                                      export=body.export))


# ── staff ───────────────────────────────────────────────────────────────────

@router.get("/api/v1/admin/offboarding")
async def list_offboardings(state: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                            user: User = Depends(support)):
    query = select(CompanyOffboarding).order_by(CompanyOffboarding.created_at.desc()).limit(200)
    if state:
        query = query.where(CompanyOffboarding.state == state)
    return {"offboardings": [service.view(o) for o in (await db.execute(query)).scalars().all()]}


@router.get("/api/v1/admin/companies/{company_id}/offboarding")
async def company_offboarding(company_id: UUID, include_test_tenants: bool = False,
                              db: AsyncSession = Depends(get_control_db), user: User = Depends(support)):
    off = await _latest(db, company_id)
    from src.auth.models import Company

    company = await db.get(Company, company_id)
    out = {"offboarding": service.view(off, await _log(db, off)) if off else None,
           "is_test": bool(company.is_test) if company else None}
    from src.auth.platform import platform_company_id

    if company is not None and company.id != await platform_company_id(db):
        out["immediate"] = await service.immediate_check(db, company_id, include_test_tenants=include_test_tenants)
    return out


@router.post("/api/v1/admin/companies/{company_id}/offboarding", status_code=201)
async def staff_requests_closure(company_id: UUID, body: ClosureBody, db: AsyncSession = Depends(get_control_db),
                                 user: User = Depends(app_admin)):
    return service.view(await service.request_closure(db, company_id, actor=user, reason=body.reason,
                                                      export=body.export))


@router.delete("/api/v1/admin/companies/{company_id}/offboarding")
async def staff_cancels_closure(company_id: UUID, db: AsyncSession = Depends(get_control_db),
                                user: User = Depends(app_admin)):
    return service.view(await service.cancel_closure(db, company_id, actor=user))


@router.post("/api/v1/admin/offboarding/{offboarding_id}/bring-forward")
async def bring_forward(offboarding_id: UUID, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(app_admin)):
    return service.view(await service.bring_forward(db, offboarding_id, actor=user))


@router.post("/api/v1/admin/offboarding/{offboarding_id}/retry")
async def retry(offboarding_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(app_admin)):
    from src.offboarding.runner import enqueue

    off = await db.get(CompanyOffboarding, offboarding_id)
    if off is None or off.state != "failed":
        raise HTTPException(status_code=409, detail="Only a failed offboarding is retried")
    await enqueue(off.id)
    return service.view(off)


@router.put("/api/v1/admin/companies/{company_id}/test")
async def mark_test(company_id: UUID, body: TestBody, db: AsyncSession = Depends(get_control_db),
                    user: User = Depends(app_admin)):
    company = await service.set_test(db, company_id, body.is_test, actor=user, reason=body.reason)
    return {"company_id": str(company.id), "is_test": company.is_test}


@router.delete("/api/v1/admin/companies/{company_id}", status_code=202)
async def delete_now(company_id: UUID, body: ImmediateBody, mode: str = Query("immediate"),
                     db: AsyncSession = Depends(get_control_db), user: User = Depends(app_admin)):
    """Flow B: a test business and its whole workspace, deleted now (13 §10)."""
    if mode != "immediate":
        raise HTTPException(status_code=422, detail="mode=immediate; a real business is closed through offboarding")
    made = await service.delete_immediately(db, company_id, actor=user, reason=body.reason,
                                            confirm_name=body.confirm_name,
                                            include_test_tenants=body.include_test_tenants)
    return {"offboardings": [service.view(o) for o in made]}


@router.get("/api/v1/admin/offboarding/{offboarding_id}")
async def one_offboarding(offboarding_id: UUID, db: AsyncSession = Depends(get_control_db),
                          user: User = Depends(support)):
    off = await db.get(CompanyOffboarding, offboarding_id)
    if off is None:
        raise HTTPException(status_code=404, detail="No such offboarding")
    return service.view(off, await _log(db, off))


@router.get("/api/v1/admin/offboarding/{offboarding_id}/certificate.pdf")
async def certificate_pdf(offboarding_id: UUID, db: AsyncSession = Depends(get_control_db),
                          user: User = Depends(support)):
    from src.common.platform.storage import get_storage
    from src.offboarding.certificate import build

    off = await db.get(CompanyOffboarding, offboarding_id)
    if off is None or off.state != "erased":
        raise HTTPException(status_code=404, detail="No certificate yet")
    if off.certificate_key:
        body = await get_storage().get(off.certificate_key)
    else:
        body = build(off, await _log(db, off))[1]
    return Response(content=body, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="erasure-{off.company_ref}.pdf"'})
