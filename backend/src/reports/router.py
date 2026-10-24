"""The report library's API (Phase 15 T9-4; 07 §7.4).

    GET /api/v1/reports                         the reports the viewer may open (its workspace's catalogue)
    GET /api/v1/reports/{id}?period=2026-10|30d|12m&from=&to=&company_id=&<filters>&format=csv|xlsx|pdf

The answer is ``{id, title, currency, as_of, period, filters, tiles, chart,
columns, rows, drill, notes}`` in the viewer's money view; ``format`` returns
the same as a file.

Staff or a partner working in a business (``X-Company-Id``, under the same checks
as every acting request) see that business's reports, as the business sees them.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.tenancy.session import ACTING_COMPANY_HEADER, acting_company_id, get_control_db
from src.reports import framework as fw

router = APIRouter(prefix="/api/v1/reports", tags=["Report library"])

RESERVED = {"period", "from", "to", "company_id", "format"}


async def _viewer(request: Request, db: AsyncSession, user: User) -> User:
    """The user, or — acting in a business — the business's admin view of it (its user for a partner_user)."""
    if not (request.headers.get(ACTING_COMPANY_HEADER) or "").strip():
        return user
    company_id = await acting_company_id(request, user, db)
    if company_id == user.company_id:
        return user
    from src.auth.models import Company
    company = await db.get(Company, company_id)
    if company is None or str(company.type) != "TENANT":
        return user
    role = "tenant_user" if str(user.role) in ("partner_user",) else "tenant_admin"
    return SimpleNamespace(id=user.id, email=user.email, role=role, company_id=company_id, staff_functions=[])  # type: ignore[return-value]


async def _partner_type(db: AsyncSession, user: User) -> Optional[str]:
    if fw.WORKSPACE.get(str(user.role)) != "partner":
        return None
    from src.partners.scope import partner_type_of
    return await partner_type_of(db, user.company_id)


async def _locked(db: AsyncSession, user: User, definition: fw.ReportDef) -> bool:
    if not definition.entitlement or str(user.role) in fw.STAFF:
        return False
    from src.billing.features import entitlement
    return not (await entitlement(db, user.company_id, definition.entitlement)).enabled


@router.get("")
async def catalogue(request: Request, db: AsyncSession = Depends(get_control_db),
                    user: User = Depends(get_current_user)):
    user = await _viewer(request, db, user)
    registry = fw.load()
    partner_type = await _partner_type(db, user)
    out = []
    for definition in registry.values():
        if fw.may_see(definition, user, partner_type):
            out.append({"id": definition.id, "title": definition.title, "description": definition.description,
                        "group": definition.group, "locked": await _locked(db, user, definition)})
    return {"workspace": fw.WORKSPACE.get(str(user.role)), "reports": sorted(out, key=lambda r: r["id"])}


@router.get("/{report_id}")
async def run_report(report_id: str, request: Request, period: Optional[str] = None,
                     from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
                     company_id: Optional[UUID] = None, format: Optional[str] = Query(None, pattern="^(csv|xlsx|pdf)$"),
                     db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.billing.currency import current_rate

    user = await _viewer(request, db, user)
    registry = fw.load()
    definition = registry.get(report_id.upper())
    if definition is None:
        raise HTTPException(status_code=404, detail="No such report")
    if not fw.may_see(definition, user, await _partner_type(db, user)):
        raise HTTPException(status_code=403, detail="This report is not in your workspace")
    if await _locked(db, user, definition):
        from src.billing.features import feature_locked
        raise feature_locked(definition.entitlement, "This report is not included in your plan")
    start, end = fw.period_of(period, from_, (to and date.fromordinal(to.toordinal() + 1)))
    if end <= start:
        raise HTTPException(status_code=422, detail="the period ends before it starts")
    companies, partner_id = await fw.scope_for(db, user, company_id)
    currency = await fw.viewer_currency(db, user)
    ctx = fw.Context(db=db, user=user, workspace=fw.WORKSPACE.get(str(user.role), "business"), companies=companies,
                     start=start, end=end, partner_id=partner_id, staff=str(user.role) in fw.STAFF,
                     filters={k: v for k, v in request.query_params.items() if k not in RESERVED},
                     currency=currency, rate=await current_rate(db, currency))
    built = await definition.builder(ctx)
    payload = fw.to_payload(definition, ctx, built)
    if format is None:
        return payload
    name = f"{definition.id}-{start.isoformat()}"
    if format == "csv":
        return Response(fw.to_csv(payload), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if format == "xlsx":
        return Response(fw.to_xlsx(payload),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(fw.to_pdf(payload), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
