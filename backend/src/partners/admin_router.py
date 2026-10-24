"""The partner programme for staff (Phase 15 T8-1…T8-13; 07 §4.1 Partners, §5.10; ``app_admin``, audited).

    GET  /api/v1/admin/partners                         every partner: type, status, depth, tenants, fee, KYC
    GET  /api/v1/admin/partners/tree-check              what the company tree and roles break (T8-1)
    GET  /api/v1/admin/partners/{id}                    Partner 360
    PUT  /api/v1/admin/partners/{id}/kyc                {status, bank_verified, reason}
    POST /api/v1/admin/partners/{id}/status             {status: active|suspended|terminated, reason}
    POST /api/v1/admin/partners/{id}/agreement          a new agreement version (today's rules)
    POST /api/v1/admin/partners/{id}/adjustment         a ledger adjustment {amount, reason}
    GET  /api/v1/admin/partners/applications[/{id}], POST …/{id}/review|approve|reject
    GET  /api/v1/admin/partners/rules, PUT …/rules/commission|fee, POST …/simulate
    GET  /api/v1/admin/partners/leads, PATCH …/leads/{id}, POST …/leads/{id}/convert
    GET  /api/v1/admin/partners/assignments?tenant_id=, POST …/assignments/reassign
    GET  /api/v1/admin/partners/charges, POST …/charges          (BCL raises Silver customers' fees)
    GET  /api/v1/admin/partners/statements, POST …/statements/build,
         POST …/statements/{id}/approve|paid|reopen, GET …/statements/export.csv, GET …/statements/{id}[/pdf]
    GET  /api/v1/admin/partners/ledger                  totals by partner, level and status (R-A10)
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker, StaffChecker
from src.auth.models import User
from src.common.tenancy.session import get_control_db
from src.partners import access, applications, assignments, charges, leads, rules, statements
from src.partners.common import billed_mtd_usd, iso, names
from src.partners.models import (
    OneTimeCharge, PartnerAccessGrant, PartnerApplication, PartnerAssignment, PartnerLead, PartnerLedgerEntry,
    PartnerProfile, PartnerStatement,
)

router = APIRouter(prefix="/api/v1/admin/partners", tags=["Partner programme: staff"])
staff = RoleChecker(["app_admin"])
sales = StaffChecker('sales')
finance = StaffChecker('finance')
money = StaffChecker('sales', 'finance')


async def _profile(db: AsyncSession, partner_id: UUID) -> PartnerProfile:
    profile = await db.get(PartnerProfile, partner_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No such partner")
    return profile


def _profile_view(p: PartnerProfile, *, name: Optional[str], recruiter: Optional[str] = None) -> Dict[str, Any]:
    return {"partner_id": str(p.company_id), "name": name, "partner_type": p.partner_type, "status": p.status,
            "status_reason": p.status_reason, "legal_name": p.legal_name, "country_code": p.country_code,
            "currency": p.billing_currency, "pan": p.pan, "gstin": p.gstin, "kyc_status": p.kyc_status,
            "bank_last4": p.bank_last4, "bank_verified": p.bank_verified, "depth": p.depth,
            "recruiter_partner_id": str(p.recruiter_partner_id) if p.recruiter_partner_id else None,
            "recruiter": recruiter, "activated_at": iso(p.activated_at), "fee_paid_until": iso(p.fee_paid_until),
            "probation_until": iso(p.probation_until)}


@router.get("")
async def list_partners(db: AsyncSession = Depends(get_control_db), user: User = Depends(sales)):
    profiles = (await db.execute(select(PartnerProfile).order_by(PartnerProfile.depth))).scalars().all()
    named = await names(db, [*(p.company_id for p in profiles), *(p.recruiter_partner_id for p in profiles)])
    counts = dict((await db.execute(select(PartnerAssignment.partner_id, func.count()).where(
        PartnerAssignment.until.is_(None)).group_by(PartnerAssignment.partner_id))).all())
    tenants = (await db.execute(select(PartnerAssignment.partner_id, PartnerAssignment.tenant_id).where(
        PartnerAssignment.until.is_(None)))).all()
    billed = await billed_mtd_usd(db, [t for _, t in tenants])
    sourced: Dict[Any, Decimal] = {}
    for partner_id, tenant_id in tenants:
        sourced[partner_id] = sourced.get(partner_id, Decimal(0)) + billed.get(tenant_id, Decimal(0))
    return [{**_profile_view(p, name=named.get(p.company_id), recruiter=named.get(p.recruiter_partner_id)),
             "tenants": counts.get(p.company_id, 0), "sourced_billed_mtd_usd": str(sourced.get(p.company_id, 0))}
            for p in profiles]


@router.get("/tree-check")
async def tree_check(db: AsyncSession = Depends(get_control_db), user: User = Depends(sales)):
    from src.partners.tree import violations

    found = await violations(db)
    return {"violations": found, "count": len(found)}


# ── rules (before /{partner_id}) ─────────────────────────────────────────────

@router.get("/rules")
async def get_rules(db: AsyncSession = Depends(get_control_db), user: User = Depends(sales)):
    from src.billing.settings_catalogue import CATALOGUE, value
    from src.partners.models import PartnerType

    types = (await db.execute(select(PartnerType))).scalars().all()
    policy = {key: str(await value(db, key)) for key in CATALOGUE if key.startswith("partners.")}
    return {**await rules.current_rules(db), "policy": policy,
            "types": [{"code": t.code, "name": t.name, "can_create_tenants": t.can_create_tenants,
                       "tenant_data_access": t.tenant_data_access, "annual_fee_item": t.annual_fee_item}
                      for t in types]}


class CommissionBody(BaseModel):
    partner_type: str
    revenue_kind: str
    level: int = Field(..., ge=0, le=2)
    rate_pct: Decimal = Field(..., ge=0, le=100)
    cap_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    months: Optional[int] = Field(None, ge=1, le=600)
    reason: Optional[str] = Field(None, max_length=500)


@router.put("/rules/commission")
async def put_commission(body: CommissionBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    row = await rules.set_commission_rule(db, partner_type=body.partner_type.upper(), revenue_kind=body.revenue_kind,
                                          level=body.level, rate_pct=body.rate_pct, cap_pct=body.cap_pct,
                                          months=body.months, actor=user, reason=body.reason)
    await db.commit()
    return rules.commission_view(row)


class FeeBody(BaseModel):
    partner_type: str
    fee_kind: str
    min_usd: Decimal = Field(..., ge=0)
    max_usd: Decimal = Field(..., ge=0)
    split: Dict[str, Decimal]
    reason: Optional[str] = Field(None, max_length=500)


@router.put("/rules/fee")
async def put_fee(body: FeeBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    row = await rules.set_fee_rule(db, partner_type=body.partner_type.upper(), fee_kind=body.fee_kind,
                                   min_usd=body.min_usd, max_usd=body.max_usd, split=body.split, actor=user,
                                   reason=body.reason)
    await db.commit()
    return rules.fee_view(row)


class SimulateBody(BaseModel):
    revenue_kind: str
    base: Decimal = Field(..., gt=0)
    chain: List[Dict[str, Any]]
    billed: Optional[Decimal] = None
    cost: Optional[Decimal] = None
    rates: Optional[Dict[str, Decimal]] = None
    cap_pct: Optional[Decimal] = Field(None, ge=0, le=100)


@router.post("/simulate")
async def simulate(body: SimulateBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.partners.simulator import simulate as run

    return await run(db, revenue_kind=body.revenue_kind, base=body.base, chain=body.chain, billed=body.billed,
                     cost=body.cost, rates=body.rates, cap_pct=body.cap_pct)


# ── applications ─────────────────────────────────────────────────────────────

@router.get("/applications")
async def list_applications(status: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                            user: User = Depends(sales)):
    query = select(PartnerApplication).order_by(PartnerApplication.created_at.desc())
    if status:
        query = query.where(PartnerApplication.status == status)
    rows = (await db.execute(query)).scalars().all()
    named = await names(db, [r.recruiter_partner_id for r in rows])
    return {"checklist": list(applications.CHECKLIST),
            "applications": [applications.view(r, recruiter=named.get(r.recruiter_partner_id)) for r in rows]}


async def _application(db: AsyncSession, app_id: UUID) -> PartnerApplication:
    app = await db.get(PartnerApplication, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="No such application")
    return app


class ReviewBody(BaseModel):
    checklist: Optional[Dict[str, bool]] = None
    notes: Optional[str] = Field(None, max_length=2000)


@router.post("/applications/{app_id}/review")
async def review(app_id: UUID, body: ReviewBody, db: AsyncSession = Depends(get_control_db),
                 user: User = Depends(staff)):
    app = await applications.review(db, await _application(db, app_id), checklist=body.checklist, notes=body.notes,
                                    actor=user)
    await db.commit()
    return applications.view(app)


class ApproveBody(BaseModel):
    partner_type: str
    notes: Optional[str] = Field(None, max_length=2000)


@router.post("/applications/{app_id}/approve")
async def approve(app_id: UUID, body: ApproveBody, db: AsyncSession = Depends(get_control_db),
                  user: User = Depends(staff)):
    return await applications.approve(db, await _application(db, app_id), partner_type=body.partner_type.upper(),
                                      actor=user, notes=body.notes)


class RejectBody(BaseModel):
    notes: str = Field(..., min_length=3, max_length=2000)


@router.post("/applications/{app_id}/reject")
async def reject(app_id: UUID, body: RejectBody, db: AsyncSession = Depends(get_control_db),
                 user: User = Depends(staff)):
    app = await applications.reject(db, await _application(db, app_id), actor=user, notes=body.notes)
    await db.commit()
    return applications.view(app)


# ── leads ────────────────────────────────────────────────────────────────────

@router.get("/leads")
async def lead_queue(status: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                     user: User = Depends(sales)):
    query = select(PartnerLead).order_by(PartnerLead.created_at.desc())
    if status:
        query = query.where(PartnerLead.status == status)
    rows = (await db.execute(query)).scalars().all()
    named = await names(db, [r.partner_id for r in rows])
    return [leads.view(r, partner=named.get(r.partner_id)) for r in rows]


class LeadMove(BaseModel):
    status: Optional[str] = None
    owner_id: Optional[UUID] = None
    reason: Optional[str] = Field(None, max_length=500)


@router.patch("/leads/{lead_id}")
async def move_lead(lead_id: UUID, body: LeadMove, db: AsyncSession = Depends(get_control_db),
                    user: User = Depends(staff)):
    lead = await db.get(PartnerLead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="No such lead")
    await leads.move(db, lead, status=body.status, owner_id=body.owner_id, reason=body.reason)
    await db.commit()
    return leads.view(lead)


class ConvertBody(BaseModel):
    admin_email: Optional[str] = Field(None, max_length=200)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)


@router.post("/leads/{lead_id}/convert")
async def convert_lead(lead_id: UUID, body: ConvertBody, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(staff)):
    lead = await db.get(PartnerLead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="No such lead")
    return await leads.convert(db, lead, actor=user, admin_email=body.admin_email, country_code=body.country_code)


# ── assignments ──────────────────────────────────────────────────────────────

@router.get("/assignments")
async def list_assignments(tenant_id: Optional[UUID] = None, partner_id: Optional[UUID] = None,
                           db: AsyncSession = Depends(get_control_db), user: User = Depends(sales)):
    query = select(PartnerAssignment).order_by(PartnerAssignment.since.desc())
    if tenant_id:
        query = query.where(PartnerAssignment.tenant_id == tenant_id)
    if partner_id:
        query = query.where(PartnerAssignment.partner_id == partner_id)
    rows = (await db.execute(query.limit(500))).scalars().all()
    named = await names(db, [*(r.tenant_id for r in rows), *(r.partner_id for r in rows)])
    return [assignments.view(r, names=named) for r in rows]


class ReassignBody(BaseModel):
    tenant_id: UUID
    partner_id: Optional[UUID] = None
    relationship: str = "resold"
    effective_from: Optional[datetime] = None
    commission_until: Optional[datetime] = None
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/assignments/reassign")
async def reassign(body: ReassignBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    row = await assignments.reassign(db, tenant_id=body.tenant_id, partner_id=body.partner_id,
                                     relationship=body.relationship, effective_from=body.effective_from,
                                     reason=body.reason, actor=user, commission_until=body.commission_until)
    await db.commit()
    return {"assignment": assignments.view(row) if row else None,
            "history": [assignments.view(r) for r in await assignments.history(db, body.tenant_id)]}


# ── charges ──────────────────────────────────────────────────────────────────

@router.get("/charges")
async def all_charges(db: AsyncSession = Depends(get_control_db), user: User = Depends(money)):
    rows = (await db.execute(select(OneTimeCharge).order_by(OneTimeCharge.created_at.desc()).limit(500))
            ).scalars().all()
    named = await names(db, [*(r.tenant_id for r in rows), *(r.partner_id for r in rows)])
    return [charges.view(r, names=named) for r in rows]


class ChargeBody(BaseModel):
    tenant_id: UUID
    fee_kind: str
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    description: Optional[str] = Field(None, max_length=300)


@router.post("/charges", status_code=201)
async def staff_charge(body: ChargeBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    charge = await charges.raise_charge(db, actor=user, tenant_id=body.tenant_id, fee_kind=body.fee_kind,
                                        amount=body.amount, description=body.description)
    await db.commit()
    return charges.view(charge, names=await names(db, [charge.tenant_id, charge.partner_id]))


# ── statements and the ledger ────────────────────────────────────────────────

@router.get("/statements")
async def list_statements(status: Optional[str] = None, db: AsyncSession = Depends(get_control_db),
                          user: User = Depends(finance)):
    query = select(PartnerStatement).order_by(PartnerStatement.period.desc(), PartnerStatement.created_at.desc())
    if status:
        query = query.where(PartnerStatement.status == status)
    rows = (await db.execute(query.limit(500))).scalars().all()
    named = await names(db, [r.partner_id for r in rows])
    return [statements.view(r, partner=named.get(r.partner_id)) for r in rows]


class BuildBody(BaseModel):
    period: date


@router.post("/statements/build")
async def build_statements(body: BuildBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    """Statements of a month now (the job makes them on the statement day): margin guard, then statements."""
    period = statements.month_start(body.period)
    return {"period": period.isoformat(), "margin_guard": await statements.margin_guard(db, period),
            **await statements.build(db, period)}


@router.get("/statements/export.csv")
async def export(db: AsyncSession = Depends(get_control_db), user: User = Depends(finance)):
    from src.common.admin_audit import record_admin_change

    rows = (await db.execute(select(PartnerStatement).where(PartnerStatement.status == "approved"))).scalars().all()
    record_admin_change(db, actor=user, action="export", object_type="partner_payouts", object_key="approved",
                        new_value={"statements": len(rows)})
    await db.commit()
    return Response(await statements.export_csv(db, rows), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="partner-payouts.csv"'})


async def _statement(db: AsyncSession, statement_id: UUID) -> PartnerStatement:
    stmt = await db.get(PartnerStatement, statement_id)
    if stmt is None:
        raise HTTPException(status_code=404, detail="No such statement")
    return stmt


@router.get("/statements/{statement_id}")
async def statement(statement_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(finance)):
    stmt = await _statement(db, statement_id)
    rows = await statements.entries_of(db, stmt)
    named = await names(db, [stmt.partner_id, *(r.tenant_id for r in rows)])
    return {**statements.view(stmt, partner=named.get(stmt.partner_id)),
            "entries": [statements.entry_view(r, tenant=named.get(r.tenant_id)) for r in rows]}


@router.get("/statements/{statement_id}/pdf")
async def statement_pdf(statement_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(finance)):
    stmt = await _statement(db, statement_id)
    partner = (await names(db, [stmt.partner_id])).get(stmt.partner_id) or ""
    return Response(statements.render_pdf(stmt, await statements.entries_of(db, stmt), partner=partner),
                    media_type="application/pdf")


@router.post("/statements/{statement_id}/approve")
async def approve_statement(statement_id: UUID, db: AsyncSession = Depends(get_control_db),
                            user: User = Depends(staff)):
    stmt = await statements.approve(db, await _statement(db, statement_id), actor=user)
    await db.commit()
    return statements.view(stmt)


class PaidBody(BaseModel):
    payout_ref: str = Field(..., min_length=3, max_length=200)


@router.post("/statements/{statement_id}/paid")
async def paid(statement_id: UUID, body: PaidBody, db: AsyncSession = Depends(get_control_db),
               user: User = Depends(staff)):
    stmt = await statements.mark_paid(db, await _statement(db, statement_id), actor=user, payout_ref=body.payout_ref)
    await db.commit()
    return statements.view(stmt)


@router.post("/statements/{statement_id}/reopen")
async def reopen(statement_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    """A dispute settled: the statement is a draft again, to approve."""
    stmt = await _statement(db, statement_id)
    if stmt.status != "disputed":
        raise HTTPException(status_code=409, detail="only a disputed statement is reopened")
    stmt.status = "draft"
    await db.commit()
    return statements.view(stmt)


@router.get("/ledger")
async def ledger(db: AsyncSession = Depends(get_control_db), user: User = Depends(finance)):
    rows = (await db.execute(select(PartnerLedgerEntry.partner_id, PartnerLedgerEntry.currency,
                                    PartnerLedgerEntry.level, PartnerLedgerEntry.status,
                                    func.sum(PartnerLedgerEntry.amount), func.sum(PartnerLedgerEntry.amount_usd))
                             .group_by(PartnerLedgerEntry.partner_id, PartnerLedgerEntry.currency,
                                       PartnerLedgerEntry.level, PartnerLedgerEntry.status))).all()
    named = await names(db, [r[0] for r in rows])
    return [{"partner_id": str(r[0]), "partner": named.get(r[0]), "currency": r[1], "level": r[2], "status": r[3],
             "amount": str(r[4] or 0), "amount_usd": str(r[5] or 0)} for r in rows]


# ── one partner ──────────────────────────────────────────────────────────────

@router.get("/{partner_id}")
async def partner_360(partner_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(money)):
    from src.partners.fees import fee_view
    from src.partners.models import PartnerAgreement

    profile = await _profile(db, partner_id)
    agreements = (await db.execute(select(PartnerAgreement).where(PartnerAgreement.partner_id == partner_id)
                                   .order_by(PartnerAgreement.version.desc()))).scalars().all()
    tenants = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.partner_id == partner_id)
                                .order_by(PartnerAssignment.since.desc()))).scalars().all()
    network = (await db.execute(select(PartnerProfile).where(PartnerProfile.recruiter_partner_id == partner_id))
               ).scalars().all()
    grants = (await db.execute(select(PartnerAccessGrant).where(PartnerAccessGrant.partner_id == partner_id)
                               .order_by(PartnerAccessGrant.created_at.desc()))).scalars().all()
    stmts = (await db.execute(select(PartnerStatement).where(PartnerStatement.partner_id == partner_id)
                              .order_by(PartnerStatement.period.desc()))).scalars().all()
    totals = dict((await db.execute(select(PartnerLedgerEntry.status, func.sum(PartnerLedgerEntry.amount)).where(
        PartnerLedgerEntry.partner_id == partner_id).group_by(PartnerLedgerEntry.status))).all())
    named = await names(db, [partner_id, profile.recruiter_partner_id, *(t.tenant_id for t in tenants),
                             *(n.company_id for n in network), *(g.tenant_id for g in grants)])
    return {"profile": _profile_view(profile, name=named.get(partner_id),
                                     recruiter=named.get(profile.recruiter_partner_id)),
            "fee": await fee_view(db, profile),
            "agreements": [{"id": str(a.id), "version": a.version, "terms": a.terms, "signed_at": iso(a.signed_at),
                            "effective_from": iso(a.effective_from), "effective_to": iso(a.effective_to)}
                           for a in agreements],
            "assignments": [assignments.view(t, names=named) for t in tenants],
            "network": [_profile_view(n, name=named.get(n.company_id)) for n in network],
            "grants": [access.view(g, names=named) for g in grants],
            "statements": [statements.view(s) for s in stmts],
            "ledger_totals": {k: str(v or 0) for k, v in totals.items()}}


class KycStatus(BaseModel):
    status: str
    bank_verified: Optional[bool] = None
    reason: Optional[str] = Field(None, max_length=500)


@router.put("/{partner_id}/kyc")
async def set_kyc(partner_id: UUID, body: KycStatus, db: AsyncSession = Depends(get_control_db),
                  user: User = Depends(staff)):
    from src.partners.lifecycle import set_kyc as apply

    profile = await _profile(db, partner_id)
    if body.bank_verified is not None:
        profile.bank_verified = body.bank_verified
    await apply(db, profile, body.status, actor=user, reason=body.reason)
    await db.commit()
    return _profile_view(profile, name=(await names(db, [partner_id])).get(partner_id))


class StatusBody(BaseModel):
    status: str
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/{partner_id}/status")
async def set_status(partner_id: UUID, body: StatusBody, db: AsyncSession = Depends(get_control_db),
                     user: User = Depends(staff)):
    from src.partners.lifecycle import set_status as apply

    profile = await _profile(db, partner_id)
    if body.status == "terminated":
        moved = await assignments.terminate(db, partner_id=partner_id, reason=body.reason, actor=user)
        return {"status": "terminated", **moved}
    if body.status not in ("active", "suspended"):
        raise HTTPException(status_code=422, detail="staff set active, suspended or terminated")
    await apply(db, profile, body.status, actor=user, reason=body.reason)
    await db.commit()
    return {"status": profile.status}


@router.post("/{partner_id}/agreement")
async def new_agreement(partner_id: UUID, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.partners.lifecycle import new_agreement as make

    agreement = await make(db, await _profile(db, partner_id))
    await db.commit()
    return {"id": str(agreement.id), "version": agreement.version, "terms": agreement.terms}


class AdjustmentBody(BaseModel):
    amount: Decimal
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/{partner_id}/adjustment", status_code=201)
async def adjustment(partner_id: UUID, body: AdjustmentBody, db: AsyncSession = Depends(get_control_db),
                     user: User = Depends(staff)):
    from src.billing.currency import current_rate, to_usd
    from src.common.admin_audit import record_admin_change

    profile = await _profile(db, partner_id)
    ccy = profile.billing_currency or "USD"
    entry = PartnerLedgerEntry(partner_id=partner_id, kind="adjustment", amount=body.amount, currency=ccy,
                               amount_usd=to_usd(body.amount, await current_rate(db, ccy)), status="payable",
                               source_type="staff", source_id=str(user.id), reason=body.reason)
    db.add(entry)
    record_admin_change(db, actor=user, action="adjust", object_type="partner_ledger", object_key=str(partner_id),
                        target_company_id=partner_id, new_value={"amount": str(body.amount), "currency": ccy},
                        reason=body.reason)
    await db.commit()
    return statements.entry_view(entry)


