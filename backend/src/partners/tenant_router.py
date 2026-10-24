"""A business's side of the programme, and applying to it (Phase 15 T8-4, T8-5, T8-8).

The business:

    GET  /api/v1/charges                                its setup and customisation fees
    POST /api/v1/charges/{id}/order | /verify           pay one (its admins): net + GST, invoiced
    GET  /api/v1/settings/partner-access                its partner, the grants, what was done under them
    POST /api/v1/settings/partner-access/{grant}/approve | /revoke      (its admins)

Anyone (no sign-in):

    GET  /api/v1/partners/invites/{token}               who is inviting
    POST /api/v1/partners/apply                         an application (with an invite's token, or to BCL)
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.common.tenancy.session import get_control_db
from src.partners import access, applications, charges
from src.partners.common import gateway, iso, names
from src.partners.models import OneTimeCharge, PartnerAccessEvent, PartnerAccessGrant

router = APIRouter(prefix="/api/v1", tags=["Partner programme: businesses"])
BILLING_ADMINS = ("tenant_admin", "app_admin")


def _admin(user: User) -> None:
    if str(user.role) not in BILLING_ADMINS:
        raise HTTPException(status_code=403, detail="Only the business's admins")


@router.get("/charges")
async def my_charges(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    rows = await charges.for_tenant(db, user.company_id)
    named = await names(db, [r.partner_id for r in rows])
    return [charges.view(r, names=named) for r in rows]


async def _my_charge(db: AsyncSession, user: User, charge_id: UUID) -> OneTimeCharge:
    _admin(user)
    charge = await db.get(OneTimeCharge, charge_id)
    if charge is None or charge.tenant_id != user.company_id:
        raise HTTPException(status_code=404, detail="No such charge")
    return charge


@router.post("/charges/{charge_id}/order")
async def charge_order(charge_id: UUID, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(get_current_user)):
    charge = await _my_charge(db, user, charge_id)
    return await charges.start_payment(db, await gateway(db), charge)


class PaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/charges/{charge_id}/verify")
async def charge_verify(charge_id: UUID, body: PaymentVerify, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(get_current_user)):
    from src.partners.payments import record_paid

    charge = await _my_charge(db, user, charge_id)
    gw = await gateway(db)
    if not gw.payment_signature_valid(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    payment, recorded = await record_paid(db, order_id=body.razorpay_order_id, payment_id=body.razorpay_payment_id,
                                          signature=body.razorpay_signature, company_id=user.company_id)
    await db.refresh(charge)
    return {"recorded": recorded, "charge": charges.view(charge),
            "invoice_id": str(payment.invoice_id) if payment.invoice_id else None}


@router.get("/settings/partner-access")
async def partner_access(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.partners.scope import assignment_of, partner_type_of

    assignment = await assignment_of(db, user.company_id)
    grants = (await db.execute(select(PartnerAccessGrant).where(PartnerAccessGrant.tenant_id == user.company_id)
                               .order_by(PartnerAccessGrant.created_at.desc()))).scalars().all()
    events = (await db.execute(select(PartnerAccessEvent).where(PartnerAccessEvent.tenant_id == user.company_id)
                               .order_by(PartnerAccessEvent.at.desc()).limit(50))).scalars().all()
    named = await names(db, [*(g.partner_id for g in grants), assignment.partner_id if assignment else None])
    users = dict((await db.execute(select(User.id, User.email).where(User.id.in_({e.user_id for e in events}))
                                   )).all()) if events else {}
    partner = None
    if assignment is not None:
        partner = {"id": str(assignment.partner_id), "name": named.get(assignment.partner_id),
                   "type": await partner_type_of(db, assignment.partner_id),
                   "relationship": assignment.relationship, "since": iso(assignment.since)}
    return {"partner": partner, "grants": [access.view(g, names=named) for g in grants],
            "events": [{"at": iso(e.at), "user": users.get(e.user_id), "partner": named.get(e.partner_id),
                        "method": e.method, "path": e.path} for e in events]}


class Decision(BaseModel):
    days: Optional[int] = Field(None, ge=1, le=365)


async def _my_grant(db: AsyncSession, user: User, grant_id: UUID) -> PartnerAccessGrant:
    _admin(user)
    grant = await db.get(PartnerAccessGrant, grant_id)
    if grant is None or (grant.tenant_id != user.company_id and str(user.role) != "app_admin"):
        raise HTTPException(status_code=404, detail="No such grant")
    return grant


@router.post("/settings/partner-access/{grant_id}/approve")
async def approve_grant(grant_id: UUID, body: Decision, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(get_current_user)):
    grant = await _my_grant(db, user, grant_id)
    await access.decide(db, grant, approve=True, actor_id=user.id, days=body.days)
    await db.commit()
    return access.view(grant)


@router.post("/settings/partner-access/{grant_id}/revoke")
async def revoke_grant(grant_id: UUID, db: AsyncSession = Depends(get_control_db),
                       user: User = Depends(get_current_user)):
    grant = await _my_grant(db, user, grant_id)
    await access.decide(db, grant, approve=False, actor_id=user.id)
    await db.commit()
    return access.view(grant)


# ── applying (no sign-in) ────────────────────────────────────────────────────

@router.get("/partners/invites/{token}")
async def invite_details(token: str, db: AsyncSession = Depends(get_control_db)):
    app = await applications.by_token(db, token)
    recruiter = (await names(db, [app.recruiter_partner_id])).get(app.recruiter_partner_id)
    return {"recruiter": recruiter, "email": app.email}


class Apply(BaseModel):
    token: Optional[str] = Field(None, max_length=64)
    company_name: str = Field(..., min_length=2, max_length=200)
    contact_name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    requested_type: Optional[str] = None
    pan: Optional[str] = Field(None, max_length=10)
    gstin: Optional[str] = Field(None, max_length=15)
    website: Optional[str] = Field(None, max_length=300)
    address: Optional[str] = Field(None, max_length=500)
    business_type: Optional[str] = Field(None, max_length=60)
    team_size: Optional[int] = Field(None, ge=1, le=100000)
    verticals: Optional[str] = Field(None, max_length=300)
    territory: Optional[str] = Field(None, max_length=300)
    notes: Optional[str] = Field(None, max_length=2000)


@router.post("/partners/apply", status_code=201)
async def apply(body: Apply, request: Request, db: AsyncSession = Depends(get_control_db)):
    from src.auth.throttle import Throttle

    throttle = Throttle("partner-apply", limit=5, window_seconds=3600)    # five an hour from one address
    client = request.client.host if request.client else "unknown"
    if await throttle.retry_after(client):
        raise HTTPException(status_code=429, detail="Too many applications from here; try again later")
    await throttle.hit(client)
    app = await applications.apply(db, body.model_dump(exclude={"token"}), token=body.token)
    await db.commit()
    return {"id": str(app.id), "status": app.status,
            "message": "Thank you. HireBuddha reviews every application and will e-mail you."}
