"""The Partner Portal's API (Phase 15 T8-14 backend; 07 §4.3, §4.4, §5.8, §5.9).

    GET  /api/v1/partner/me                      the partnership: type, status, agreement, fee, KYC, probation
    PUT  /api/v1/partner/me/kyc                  legal name, PAN, GSTIN, bank (admin)
    POST /api/v1/partner/me/agreement/sign       (admin)
    POST /api/v1/partner/me/fee/order|verify     the annual fee (admin)
    GET  /api/v1/partner/overview                tiles for the home page
    GET  /api/v1/partner/customers               referred and resold customers: billed, commission (no data)
    GET|POST /api/v1/partner/leads, POST …/{id}/convert (Gold, own leads)
    GET|POST /api/v1/partner/charges, GET …/preview, POST …/{id}/cancel (Gold admin)
    GET  /api/v1/partner/network, GET|POST …/invites   sub-partners and override earnings — never their tenants
    GET  /api/v1/partner/earnings                the ledger with totals (admin)
    GET  /api/v1/partner/statements[/{id}[/pdf]], POST …/{id}/dispute, POST …/{id}/gst-invoice (admin)
    GET|POST /api/v1/partner/access              access grants; ask a tenant for one (Gold)
    GET  /api/v1/partner/guide                   the programme's rules for this partner

Amounts are the partner's own (its ledger, in its currency) or its customers'
**billed** amounts — never cost.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import Company, User
from src.common.tenancy.session import get_control_db
from src.partners import access, applications, charges, leads, statements
from src.partners.common import billed_mtd_usd, gateway, in_currency, iso, names, require_partner
from src.partners.models import (
    OneTimeCharge, PartnerAccessGrant, PartnerApplication, PartnerAssignment, PartnerLead, PartnerLedgerEntry,
    PartnerProfile, PartnerStatement, PartnerType,
)

router = APIRouter(prefix="/api/v1/partner", tags=["Partner Portal"])


async def _profile(db: AsyncSession, user: User, *, admin: bool = False) -> PartnerProfile:
    partner_id = require_partner(user, admin=admin)
    profile = await db.get(PartnerProfile, partner_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="This company is not in the partner programme")
    return profile


# ── the partnership ──────────────────────────────────────────────────────────

@router.get("/me")
async def me(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.partners.fees import fee_view
    from src.partners.lifecycle import latest_agreement

    profile = await _profile(db, user)
    kind = await db.get(PartnerType, profile.partner_type)
    agreement = await latest_agreement(db, profile.company_id)
    recruiter = (await names(db, [profile.recruiter_partner_id])).get(profile.recruiter_partner_id)
    return {"company_id": str(profile.company_id), "partner_type": profile.partner_type, "type_name": kind.name,
            "can_create_tenants": kind.can_create_tenants, "tenant_data_access": kind.tenant_data_access,
            "status": profile.status, "status_reason": profile.status_reason, "legal_name": profile.legal_name,
            "country_code": profile.country_code, "currency": profile.billing_currency, "pan": profile.pan,
            "gstin": profile.gstin, "kyc_status": profile.kyc_status, "bank_last4": profile.bank_last4,
            "bank_verified": profile.bank_verified, "recruiter": recruiter, "depth": profile.depth,
            "activated_at": iso(profile.activated_at), "probation_until": iso(profile.probation_until),
            "fee": await fee_view(db, profile),
            "agreement": {"id": str(agreement.id), "version": agreement.version, "terms": agreement.terms,
                          "signed_at": iso(agreement.signed_at), "effective_from": iso(agreement.effective_from)}
            if agreement else None}


class Bank(BaseModel):
    account_name: str = Field(..., min_length=2, max_length=120)
    account_number: str = Field(..., pattern=r"^[0-9]{6,20}$")
    ifsc: str = Field(..., pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")


class KycBody(BaseModel):
    legal_name: Optional[str] = Field(None, max_length=200)
    pan: Optional[str] = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    gstin: Optional[str] = Field(None, max_length=15)
    bank: Optional[Bank] = None


@router.put("/me/kyc")
async def put_kyc(body: KycBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    """The partner's KYC details; a change goes back to staff for verification."""
    import json

    from src.auth.geography import valid_gstin
    from src.common.security import encrypt_api_key

    profile = await _profile(db, user, admin=True)
    changed = False
    if body.legal_name is not None and body.legal_name != profile.legal_name:
        profile.legal_name, changed = body.legal_name, True
    if body.pan is not None and body.pan != profile.pan:
        profile.pan, changed = body.pan, True
    if body.gstin is not None and body.gstin != profile.gstin:
        try:
            profile.gstin = valid_gstin(body.gstin)
        except ValueError as bad:
            raise HTTPException(status_code=422, detail=str(bad)) from None
        changed = True
    if body.bank is not None:
        profile.bank_encrypted = encrypt_api_key(json.dumps(body.bank.model_dump()))
        profile.bank_last4, profile.bank_verified, changed = body.bank.account_number[-4:], False, True
    if changed:
        profile.kyc_status, profile.updated_at = "pending", datetime.utcnow()
    await db.commit()
    return {"kyc_status": profile.kyc_status, "bank_last4": profile.bank_last4}


@router.post("/me/agreement/sign")
async def sign_agreement(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.partners.lifecycle import sign

    profile = await _profile(db, user, admin=True)
    agreement = await sign(db, profile, user)
    await db.commit()
    return {"version": agreement.version, "signed_at": iso(agreement.signed_at), "status": profile.status}


class PaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/me/fee/order")
async def fee_order(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.partners.fees import start

    profile = await _profile(db, user, admin=True)
    return await start(db, await gateway(db), profile)


@router.post("/me/fee/verify")
async def fee_verify(body: PaymentVerify, db: AsyncSession = Depends(get_control_db),
                     user: User = Depends(get_current_user)):
    from src.partners.payments import record_paid

    profile = await _profile(db, user, admin=True)
    gw = await gateway(db)
    if not gw.payment_signature_valid(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    payment, recorded = await record_paid(db, order_id=body.razorpay_order_id, payment_id=body.razorpay_payment_id,
                                          signature=body.razorpay_signature, company_id=profile.company_id)
    await db.refresh(profile)
    return {"recorded": recorded, "status": profile.status, "fee_paid_until": iso(profile.fee_paid_until),
            "invoice_id": str(payment.invoice_id) if payment.invoice_id else None}


# ── home ─────────────────────────────────────────────────────────────────────

async def _totals_by_status(db: AsyncSession, partner_id: UUID) -> Dict[str, str]:
    rows = (await db.execute(select(PartnerLedgerEntry.status, func.coalesce(func.sum(PartnerLedgerEntry.amount), 0))
                             .where(PartnerLedgerEntry.partner_id == partner_id,
                                    PartnerLedgerEntry.kind.in_(("commission", "override", "fee_share", "clawback",
                                                                 "adjustment")))
                             .group_by(PartnerLedgerEntry.status))).all()
    return {status: str(total) for status, total in rows}


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.partners.fees import fee_view
    from src.partners.scope import tenant_ids

    profile = await _profile(db, user)
    pid, ccy = profile.company_id, profile.billing_currency or "USD"
    resold = await tenant_ids(db, pid, relationship="resold")
    referred = await tenant_ids(db, pid, relationship="referred")
    billed = await billed_mtd_usd(db, [*resold, *referred])
    month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    earned_mtd = (await db.execute(select(func.coalesce(func.sum(PartnerLedgerEntry.amount), 0)).where(
        PartnerLedgerEntry.partner_id == pid, PartnerLedgerEntry.created_at >= month,
        PartnerLedgerEntry.kind.in_(("commission", "override", "fee_share", "clawback"))))).scalar()
    lead_counts = dict((await db.execute(select(PartnerLead.status, func.count()).where(PartnerLead.partner_id == pid)
                                         .group_by(PartnerLead.status))).all())
    next_statement = (await db.execute(select(PartnerStatement).where(
        PartnerStatement.partner_id == pid, PartnerStatement.status.in_(("draft", "approved")))
        .order_by(PartnerStatement.period.desc()).limit(1))).scalar_one_or_none()
    open_charges = (await db.execute(select(func.count()).select_from(OneTimeCharge).where(
        OneTimeCharge.partner_id == pid, OneTimeCharge.status == "sent"))).scalar()
    show_money = str(user.role) == "partner_admin"
    return {"partner_type": profile.partner_type, "status": profile.status, "currency": ccy,
            "tenants": len(resold), "referred_customers": len(referred),
            "customers_billed_mtd": str(await in_currency(db, sum(billed.values(), Decimal(0)), ccy)),
            "earnings_mtd": str(earned_mtd) if show_money else None,
            "earnings_by_status": await _totals_by_status(db, pid) if show_money else None,
            "next_statement": statements.view(next_statement) if next_statement and show_money else None,
            "fee": await fee_view(db, profile), "leads": lead_counts, "open_charges": open_charges}


@router.get("/customers")
async def customers(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    """The partner's customers — billed amounts and its commission, no data (Silver: its referrals)."""
    from src.billing.plans import plan_of

    profile = await _profile(db, user)
    pid, ccy = profile.company_id, profile.billing_currency or "USD"
    rows = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.partner_id == pid,
                                                             PartnerAssignment.until.is_(None)))).scalars().all()
    ids = [r.tenant_id for r in rows]
    billed = await billed_mtd_usd(db, ids)
    commission = dict((await db.execute(select(PartnerLedgerEntry.tenant_id, func.sum(PartnerLedgerEntry.amount))
                                        .where(PartnerLedgerEntry.partner_id == pid, PartnerLedgerEntry.level == 0,
                                               PartnerLedgerEntry.tenant_id.in_(ids),
                                               PartnerLedgerEntry.status != "reversed")
                                        .group_by(PartnerLedgerEntry.tenant_id))).all()) if ids else {}
    companies = {c.id: c for c in (await db.execute(select(Company).where(Company.id.in_(ids)))).scalars().all()}
    out = []
    for row in rows:
        company = companies.get(row.tenant_id)
        plan = await plan_of(db, row.tenant_id)
        out.append({"tenant_id": str(row.tenant_id), "name": company.name if company else None,
                    "relationship": row.relationship, "status": company.status if company else None,
                    "since": iso(row.since), "plan": plan.name if plan else None,
                    "billed_mtd": str(await in_currency(db, billed.get(row.tenant_id, Decimal(0)), ccy)),
                    "lifetime_commission": str(commission.get(row.tenant_id) or 0)
                    if str(user.role) == "partner_admin" else None})
    return {"currency": ccy, "customers": out}


# ── leads ────────────────────────────────────────────────────────────────────

class LeadBody(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=200)
    contact_name: Optional[str] = Field(None, max_length=120)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    notes: Optional[str] = Field(None, max_length=2000)


@router.get("/leads")
async def list_leads(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    pid = require_partner(user)
    rows = (await db.execute(select(PartnerLead).where(PartnerLead.partner_id == pid)
                             .order_by(PartnerLead.created_at.desc()))).scalars().all()
    return [leads.view(r) for r in rows]


@router.post("/leads", status_code=201)
async def register_lead(body: LeadBody, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(get_current_user)):
    pid = require_partner(user)
    lead = await leads.register(db, partner_id=pid, actor_id=user.id, data=body.model_dump())
    await db.commit()
    return leads.view(lead)


class ConvertBody(BaseModel):
    admin_email: Optional[str] = Field(None, max_length=200)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)


@router.post("/leads/{lead_id}/convert")
async def convert_lead(lead_id: UUID, body: ConvertBody, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(get_current_user)):
    pid = require_partner(user, admin=True)
    lead = await db.get(PartnerLead, lead_id)
    if lead is None or lead.partner_id != pid:
        raise HTTPException(status_code=404, detail="No such lead")
    return await leads.convert(db, lead, actor=user, admin_email=body.admin_email, country_code=body.country_code)


# ── setup and customisation fees ─────────────────────────────────────────────

class ChargeBody(BaseModel):
    tenant_id: UUID
    fee_kind: str
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    description: Optional[str] = Field(None, max_length=300)


@router.get("/charges")
async def list_charges(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    pid = require_partner(user, admin=True)
    rows = (await db.execute(select(OneTimeCharge).where(OneTimeCharge.partner_id == pid)
                             .order_by(OneTimeCharge.created_at.desc()))).scalars().all()
    named = await names(db, [r.tenant_id for r in rows])
    return [charges.view(r, names=named) for r in rows]


@router.get("/charges/preview")
async def charge_preview(tenant_id: UUID, fee_kind: str = Query(...), db: AsyncSession = Depends(get_control_db),
                         user: User = Depends(get_current_user)):
    from src.partners.scope import tenant_ids

    pid = require_partner(user, admin=True)
    if tenant_id not in await tenant_ids(db, pid, relationship="resold"):
        raise HTTPException(status_code=403, detail="Only a business you resell")
    return await charges.preview(db, partner_id=pid, tenant_id=tenant_id, fee_kind=fee_kind)


@router.post("/charges", status_code=201)
async def raise_charge(body: ChargeBody, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(get_current_user)):
    require_partner(user, admin=True)
    charge = await charges.raise_charge(db, actor=user, tenant_id=body.tenant_id, fee_kind=body.fee_kind,
                                        amount=body.amount, description=body.description)
    await db.commit()
    return charges.view(charge, names=await names(db, [charge.tenant_id]))


@router.post("/charges/{charge_id}/cancel")
async def cancel_charge(charge_id: UUID, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(get_current_user)):
    require_partner(user, admin=True)
    charge = await db.get(OneTimeCharge, charge_id)
    if charge is None:
        raise HTTPException(status_code=404, detail="No such charge")
    await charges.cancel(db, charge, actor=user)
    await db.commit()
    return charges.view(charge)


# ── network ──────────────────────────────────────────────────────────────────

@router.get("/network")
async def network(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    """The partners this one recruited (and theirs): names, type, status, level, its overrides — no tenants."""
    pid = require_partner(user)
    first = (await db.execute(select(PartnerProfile).where(PartnerProfile.recruiter_partner_id == pid))
             ).scalars().all()
    second = (await db.execute(select(PartnerProfile).where(PartnerProfile.recruiter_partner_id.in_(
        [p.company_id for p in first])))).scalars().all() if first else []
    named = await names(db, [p.company_id for p in [*first, *second]])
    earned = dict((await db.execute(select(PartnerLedgerEntry.origin_partner_id, func.sum(PartnerLedgerEntry.amount))
                                    .where(PartnerLedgerEntry.partner_id == pid, PartnerLedgerEntry.level >= 1,
                                           PartnerLedgerEntry.status != "reversed")
                                    .group_by(PartnerLedgerEntry.origin_partner_id))).all())
    show = str(user.role) == "partner_admin"
    out = [{"partner_id": str(p.company_id), "name": named.get(p.company_id), "type": p.partner_type,
            "status": p.status, "level": 1 if p in first else 2,
            "recruited_by": str(p.recruiter_partner_id) if p.recruiter_partner_id else None,
            "joined": iso(p.activated_at), "override_earnings": str(earned.get(p.company_id) or 0) if show else None}
           for p in [*first, *second]]
    return {"partners": out}


class InviteBody(BaseModel):
    email: Optional[str] = Field(None, max_length=200)


@router.get("/network/invites")
async def invites(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    pid = require_partner(user, admin=True)
    rows = (await db.execute(select(PartnerApplication).where(PartnerApplication.recruiter_partner_id == pid)
                             .order_by(PartnerApplication.created_at.desc()))).scalars().all()
    return [{"id": str(a.id), "email": a.email, "status": a.status, "company_name": a.company_name,
             "token": a.invite_token if a.status == "invited" else None, "created_at": iso(a.created_at)}
            for a in rows]


@router.post("/network/invites", status_code=201)
async def invite(body: InviteBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.auth.account_emails import frontend_link

    pid = require_partner(user, admin=True)
    app = await applications.invite(db, recruiter_id=pid, email=body.email, actor_id=user.id)
    await db.commit()
    return {"id": str(app.id), "token": app.invite_token, "link": frontend_link("/partners/apply", app.invite_token)}


# ── earnings and statements ──────────────────────────────────────────────────

@router.get("/earnings")
async def earnings(status: Optional[str] = None, revenue_kind: Optional[str] = None, level: Optional[int] = None,
                   since: Optional[datetime] = None, until: Optional[datetime] = None,
                   limit: int = Query(200, ge=1, le=1000), db: AsyncSession = Depends(get_control_db),
                   user: User = Depends(get_current_user)):
    profile = await _profile(db, user, admin=True)
    query = select(PartnerLedgerEntry).where(PartnerLedgerEntry.partner_id == profile.company_id)
    if status:
        query = query.where(PartnerLedgerEntry.status == status)
    if revenue_kind:
        query = query.where(PartnerLedgerEntry.revenue_kind == revenue_kind)
    if level is not None:
        query = query.where(PartnerLedgerEntry.level == level)
    if since:
        query = query.where(PartnerLedgerEntry.created_at >= since)
    if until:
        query = query.where(PartnerLedgerEntry.created_at < until)
    rows = (await db.execute(query.order_by(PartnerLedgerEntry.created_at.desc()).limit(limit))).scalars().all()
    # Its own customers by name; a sub-partner's customer is shown as that sub-partner's (never named).
    own = {r.tenant_id for r in rows if r.level == 0}
    named = await names(db, [*own, *{r.origin_partner_id for r in rows if r.level > 0}])
    entries = []
    for r in rows:
        label = named.get(r.tenant_id) if r.level == 0 else f"via {named.get(r.origin_partner_id, 'a partner')}"
        view = statements.entry_view(r, tenant=label)
        if r.level > 0:
            view["tenant_id"] = None
        entries.append(view)
    return {"currency": profile.billing_currency, "entries": entries,
            "totals": await _totals_by_status(db, profile.company_id)}


@router.get("/statements")
async def my_statements(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    profile = await _profile(db, user, admin=True)
    rows = (await db.execute(select(PartnerStatement).where(PartnerStatement.partner_id == profile.company_id)
                             .order_by(PartnerStatement.period.desc()))).scalars().all()
    return [statements.view(r) for r in rows]


async def _my_statement(db: AsyncSession, user: User, statement_id: UUID) -> PartnerStatement:
    profile = await _profile(db, user, admin=True)
    stmt = await db.get(PartnerStatement, statement_id)
    if stmt is None or stmt.partner_id != profile.company_id:
        raise HTTPException(status_code=404, detail="No such statement")
    return stmt


@router.get("/statements/{statement_id}")
async def my_statement(statement_id: UUID, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(get_current_user)):
    stmt = await _my_statement(db, user, statement_id)
    rows = await statements.entries_of(db, stmt)
    named = await names(db, [r.tenant_id for r in rows if r.level == 0])
    return {**statements.view(stmt), "entries": [statements.entry_view(r, tenant=named.get(r.tenant_id))
                                                 for r in rows]}


@router.get("/statements/{statement_id}/pdf")
async def my_statement_pdf(statement_id: UUID, db: AsyncSession = Depends(get_control_db),
                           user: User = Depends(get_current_user)):
    stmt = await _my_statement(db, user, statement_id)
    partner = (await names(db, [stmt.partner_id])).get(stmt.partner_id) or ""
    pdf = statements.render_pdf(stmt, await statements.entries_of(db, stmt), partner=partner)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="statement-{stmt.period:%Y-%m}.pdf"'})


class DisputeBody(BaseModel):
    reason: str = Field(..., min_length=5, max_length=1000)


@router.post("/statements/{statement_id}/dispute")
async def dispute(statement_id: UUID, body: DisputeBody, db: AsyncSession = Depends(get_control_db),
                  user: User = Depends(get_current_user)):
    stmt = await _my_statement(db, user, statement_id)
    await statements.dispute(db, stmt, reason=body.reason)
    await db.commit()
    return statements.view(stmt)


@router.post("/statements/{statement_id}/gst-invoice")
async def upload_gst_invoice(statement_id: UUID, file: UploadFile = File(...),
                             db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    """A GST-registered partner's tax invoice to BCL against the statement (§11.7)."""
    from src.common.platform.storage import company_namespace, get_storage

    stmt = await _my_statement(db, user, statement_id)
    data = await file.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="a file of up to 5 MB")
    if not (file.content_type or "").startswith(("application/pdf", "image/")):
        raise HTTPException(status_code=422, detail="a PDF or an image")
    key = f"{company_namespace(stmt.partner_id)}/partner/statements/{stmt.id}/gst-invoice"
    await get_storage().put(key, data, content_type=file.content_type)
    stmt.gst_invoice_ref = key
    await db.commit()
    return statements.view(stmt)


# ── access grants ────────────────────────────────────────────────────────────

class GrantRequest(BaseModel):
    tenant_id: UUID
    scopes: List[str] = Field(..., min_length=1)
    reason: str = Field(..., min_length=3, max_length=500)
    days: Optional[int] = Field(None, ge=1, le=365)


@router.get("/access")
async def my_grants(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    pid = require_partner(user)
    rows = (await db.execute(select(PartnerAccessGrant).where(PartnerAccessGrant.partner_id == pid)
                             .order_by(PartnerAccessGrant.created_at.desc()))).scalars().all()
    named = await names(db, [r.tenant_id for r in rows])
    return [access.view(r, names=named) for r in rows]


@router.post("/access", status_code=201)
async def ask_for_access(body: GrantRequest, db: AsyncSession = Depends(get_control_db),
                         user: User = Depends(get_current_user)):
    from src.notifications.service import notify

    pid = require_partner(user, admin=True)
    grant = await access.request_grant(db, partner_id=pid, tenant_id=body.tenant_id, scopes=body.scopes,
                                       reason=body.reason, days=body.days, actor_id=user.id)
    await db.commit()
    partner = (await names(db, [pid])).get(pid)
    await notify(body.tenant_id, kind="partner.access_requested", title=f"{partner} asks for access to your account",
                 body=f"{', '.join(grant.scopes)}: {body.reason}", link="/settings/partner-access", severity="info",
                 dedupe_key=f"partner.access:{grant.id}")
    return access.view(grant, names=await names(db, [body.tenant_id]))


@router.get("/guide")
async def guide(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.partners.rules import snapshot

    profile = await _profile(db, user)
    return await snapshot(db, profile.partner_type)
