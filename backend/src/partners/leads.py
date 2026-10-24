"""Leads (Phase 15 T8-9, tech design §11.2, §11.8).

A partner registers a prospective customer; it is the partner's alone for
``partners.lead_exclusivity_days`` (90). A lead whose e-mail domain (not a
free mail provider), phone or company name matches an open lead, or a
company already on the platform, is refused — without saying whose it is.
BCL's sales queue accepts, works and converts leads: conversion makes the
tenant and its assignment — ``referred`` for a Silver partner (BCL owns the
customer), ``resold`` for a Gold one (which may convert its own leads) —
with no end to the commission (O-8). An unconverted lead expires.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from src.partners.models import PartnerLead

OPEN = ("registered", "accepted", "in_progress")
FREE_MAIL = frozenset({"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
                       "icloud.com", "rediffmail.com", "proton.me", "protonmail.com", "aol.com", "zoho.com"})
STAFF_MOVES = {"registered": {"accepted", "lost"}, "accepted": {"in_progress", "lost"}, "in_progress": {"lost"}}


def _domain(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return None if domain in FREE_MAIL else domain


def _phone(phone: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 8 else None


def view(lead: PartnerLead, *, partner: Optional[str] = None) -> Dict[str, Any]:
    return {"id": str(lead.id), "partner_id": str(lead.partner_id), "partner": partner,
            "company_name": lead.company_name, "contact_name": lead.contact_name, "email": lead.email,
            "phone": lead.phone, "country_code": lead.country_code, "notes": lead.notes, "status": lead.status,
            "bcl_owner_id": str(lead.bcl_owner_id) if lead.bcl_owner_id else None,
            "exclusive_until": lead.exclusive_until.isoformat() if lead.exclusive_until else None,
            "converted_company_id": str(lead.converted_company_id) if lead.converted_company_id else None,
            "lost_reason": lead.lost_reason, "created_at": lead.created_at.isoformat() if lead.created_at else None}


async def register(db: Any, *, partner_id: UUID, actor_id: UUID, data: Dict[str, Any]) -> PartnerLead:
    """The caller commits. 409 for a duplicate."""
    from src.auth.models import Company
    from src.billing.settings_catalogue import value
    from src.partners.lifecycle import require_active

    await require_active(db, partner_id, "register leads")
    name = (data.get("company_name") or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="the company's name is needed")
    email = (data.get("email") or "").strip().lower() or None
    domain, phone = _domain(email), _phone(data.get("phone"))
    now = datetime.utcnow()
    clauses = [func.lower(PartnerLead.company_name) == name.lower()]
    if domain:
        clauses.append(PartnerLead.email_domain == domain)
    if phone:
        clauses.append(func.right(func.regexp_replace(PartnerLead.phone, "[^0-9]", "", "g"), 10) == phone)
    clash = (await db.execute(select(PartnerLead.id).where(
        PartnerLead.status.in_(OPEN), or_(PartnerLead.exclusive_until.is_(None), PartnerLead.exclusive_until > now),
        or_(*clauses)).limit(1))).first()
    if clash:
        raise HTTPException(status_code=409, detail="This customer is already registered as a lead")
    if (await db.execute(select(Company.id).where(Company.type == "TENANT",
                                                  func.lower(Company.name) == name.lower()).limit(1))).first():
        raise HTTPException(status_code=409, detail="This customer is already on HireBuddha")
    days = int(await value(db, "partners.lead_exclusivity_days"))
    lead = PartnerLead(partner_id=partner_id, company_name=name, contact_name=data.get("contact_name"),
                       email=email, email_domain=domain, phone=data.get("phone"),
                       country_code=(data.get("country_code") or "IN").upper(), notes=data.get("notes"),
                       status="registered", exclusive_until=now + timedelta(days=days), created_by=actor_id)
    db.add(lead)
    await db.flush()
    return lead


async def move(db: Any, lead: PartnerLead, *, status: Optional[str], owner_id: Optional[UUID],
               reason: Optional[str]) -> PartnerLead:
    """Staff work the queue: accept, in progress, lost; an owner."""
    if status and status != lead.status:
        if status not in STAFF_MOVES.get(lead.status, set()):
            raise HTTPException(status_code=409, detail=f"a {lead.status} lead cannot become {status}")
        lead.status = status
        if status == "lost":
            lead.lost_reason = reason
    if owner_id is not None:
        lead.bcl_owner_id = owner_id
    lead.updated_at = datetime.utcnow()
    return lead


async def convert(db: Any, lead: PartnerLead, *, actor: Any, admin_email: Optional[str] = None,
                  country_code: Optional[str] = None) -> Dict[str, Any]:
    """The lead becomes a customer: the tenant, its assignment (and a Gold partner's grant). Commits."""
    from src.auth.geography import set_geography
    from src.auth.models import Company, User
    from src.auth.platform import platform_company_id
    from src.auth.service import _provision_new_tenant, grant_first_daily_credits, request_workspace
    from src.common.security import get_password_hash
    from src.partners.access import grant_for_created_tenant
    from src.partners.lifecycle import require_active
    from src.partners.scope import assign, partner_type_of

    if lead.status not in OPEN:
        raise HTTPException(status_code=409, detail=f"the lead is {lead.status}")
    gold = await partner_type_of(db, lead.partner_id) == "GOLD"
    staff = str(actor.role) == "app_admin"
    if not staff and not (gold and actor.company_id == lead.partner_id):
        raise HTTPException(status_code=403, detail="HireBuddha converts a Silver partner's leads")
    await require_active(db, lead.partner_id, "take on customers")
    tenant = Company(name=lead.company_name, type="TENANT", status="active", onboarding_status="pending",
                     parent_id=lead.partner_id if gold else await platform_company_id(db),
                     onboarding_metadata={"completed_steps": [], "created_via": "partner_lead",
                                          "lead_id": str(lead.id)})
    await set_geography(db, tenant, country_code or lead.country_code)
    db.add(tenant)
    await db.flush()
    await _provision_new_tenant(db, tenant)
    await assign(db, tenant_id=tenant.id, partner_id=lead.partner_id, relationship="resold" if gold else "referred",
                 source="lead", actor_id=actor.id, reason=f"lead {lead.id}")
    if gold:
        await grant_for_created_tenant(db, partner_id=lead.partner_id, tenant_id=tenant.id, actor_id=actor.id)
    user_id = None
    email = (admin_email or lead.email or "").strip().lower()
    if email and not (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
        user = User(email=email, full_name=lead.contact_name or email, role="tenant_admin", company_id=tenant.id,
                    hashed_password=get_password_hash(secrets.token_urlsafe(32)), is_active=True, is_verified=True)
        db.add(user)
        await db.flush()
        user_id = user.id
    lead.status, lead.converted_company_id, lead.updated_at = "converted", tenant.id, datetime.utcnow()
    await db.commit()
    await grant_first_daily_credits(db, tenant.id)
    await request_workspace(tenant.id)
    if user_id is not None:
        from src.auth.account_emails import send_password_reset_email
        user = await db.get(User, user_id)
        try:
            await send_password_reset_email(user.email, user.hashed_password)
        except Exception:  # noqa: BLE001
            pass
    return {"lead": view(lead), "tenant_id": str(tenant.id), "user_id": str(user_id) if user_id else None}


async def expire(db: Any, *, now: Optional[datetime] = None) -> int:
    from sqlalchemy import update

    now = now or datetime.utcnow()
    result = await db.execute(update(PartnerLead).where(PartnerLead.status.in_(OPEN),
                                                        PartnerLead.exclusive_until <= now)
                              .values(status="expired", updated_at=now))
    return result.rowcount or 0
