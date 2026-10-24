"""Applying to be a partner, and underwriting (Phase 15 T8-5, tech design §11.3).

* A partner invites (``invite``: a link with a token; the recruiter is fixed
  at that point — it has no say in the type), or anyone applies to BCL.
* Staff review: the underwriting checklist (identity and business KYC, bank,
  sanctions and adverse media, duplicates, territory, Gold capability,
  agreement), then approve with a type — or reject.
* Approval makes the PARTNER company (under its recruiter, or the platform),
  its profile (``approved``, KYC as given), its first agreement (today's rules
  snapshotted) and its admin, who sets a password from an e-mailed link. The
  partnership is ``active`` once the agreement is signed and any fee paid.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from src.partners.models import SILVER, GOLD, PartnerApplication, PartnerProfile

logger = logging.getLogger(__name__)

CHECKLIST = ("identity_kyc", "business_kyc", "bank_verified", "sanctions_check", "no_duplicate", "territory_check",
             "capability_assessment", "agreement_reviewed")
OPEN = ("invited", "applied", "under_review")
PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def view(app: PartnerApplication, *, recruiter: Optional[str] = None) -> Dict[str, Any]:
    return {"id": str(app.id), "status": app.status, "recruiter_partner_id":
            str(app.recruiter_partner_id) if app.recruiter_partner_id else None, "recruiter": recruiter,
            "requested_type": app.requested_type, "approved_type": app.approved_type,
            "company_name": app.company_name, "contact_name": app.contact_name, "email": app.email,
            "phone": app.phone, "country_code": app.country_code, "details": app.details or {},
            "checklist": app.checklist or {}, "review_notes": app.review_notes,
            "company_id": str(app.company_id) if app.company_id else None,
            "created_at": app.created_at.isoformat() if app.created_at else None,
            "reviewed_at": app.reviewed_at.isoformat() if app.reviewed_at else None}


async def invite(db: Any, *, recruiter_id: UUID, email: Optional[str], actor_id: UUID) -> PartnerApplication:
    """A recruiter's invite link (the caller commits). The recruiter must be active and not at the depth limit."""
    from src.billing.settings_catalogue import value
    from src.partners.lifecycle import require_active
    from src.partners.tree import partner_depth

    await require_active(db, recruiter_id, "invite partners")
    limit = int(await value(db, "partners.max_depth"))
    if await partner_depth(db, recruiter_id) + 1 > limit:
        raise HTTPException(status_code=403, detail=f"Partners are at most {limit} levels deep: yours cannot recruit")
    app = PartnerApplication(recruiter_partner_id=recruiter_id, invite_token=secrets.token_urlsafe(24),
                             status="invited", email=(email or "").strip().lower() or None,
                             details={"invited_by": str(actor_id)})
    db.add(app)
    await db.flush()
    return app


async def by_token(db: Any, token: str) -> PartnerApplication:
    app = (await db.execute(select(PartnerApplication).where(PartnerApplication.invite_token == token))
           ).scalar_one_or_none()
    if app is None or app.status != "invited":
        raise HTTPException(status_code=404, detail="That invitation is not valid any more")
    return app


async def apply(db: Any, data: Dict[str, Any], *, token: Optional[str] = None) -> PartnerApplication:
    """An application, through an invite or straight to BCL (the caller commits)."""
    from src.auth.models import User

    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="an e-mail address is needed")
    if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
        raise HTTPException(status_code=409, detail="That e-mail address already has an account: sign in, or use "
                                                    "another")
    duplicate = (await db.execute(select(PartnerApplication.id).where(
        func.lower(PartnerApplication.email) == email, PartnerApplication.status.in_(("applied", "under_review")))
    )).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="An application with that e-mail address is being reviewed")
    pan = (data.get("pan") or "").strip().upper() or None
    if pan and not PAN.match(pan):
        raise HTTPException(status_code=422, detail="a PAN is five letters, four digits and a letter")
    requested = (data.get("requested_type") or "").upper() or None
    if requested not in (None, SILVER, GOLD):
        raise HTTPException(status_code=422, detail="the type is SILVER or GOLD")
    app = await by_token(db, token) if token else PartnerApplication()
    app.status = "applied"
    app.company_name, app.contact_name = data.get("company_name"), data.get("contact_name")
    app.email, app.phone, app.country_code = email, data.get("phone"), (data.get("country_code") or "IN").upper()
    app.requested_type = requested
    app.details = {**(app.details or {}), **{k: v for k, v in data.items() if k in (
        "website", "gstin", "address", "business_type", "team_size", "verticals", "territory", "notes")},
        "pan": pan}
    app.updated_at = datetime.utcnow()
    if app.id is None:
        db.add(app)
    await db.flush()
    return app


async def review(db: Any, app: PartnerApplication, *, checklist: Optional[Dict[str, bool]], notes: Optional[str],
                 actor: Any) -> PartnerApplication:
    if app.status not in ("applied", "under_review"):
        raise HTTPException(status_code=409, detail=f"the application is {app.status}")
    unknown = set(checklist or {}) - set(CHECKLIST)
    if unknown:
        raise HTTPException(status_code=422, detail=f"the checklist has {', '.join(CHECKLIST)}")
    app.status = "under_review"
    app.checklist = {**(app.checklist or {}), **{k: bool(v) for k, v in (checklist or {}).items()}}
    if notes is not None:
        app.review_notes = notes
    app.reviewed_by, app.reviewed_at, app.updated_at = actor.id, datetime.utcnow(), datetime.utcnow()
    return app


async def approve(db: Any, app: PartnerApplication, *, partner_type: str, actor: Any,
                  notes: Optional[str] = None) -> Dict[str, Any]:
    """Make the partner: company, profile, agreement and admin (commits)."""
    from src.auth.geography import set_geography
    from src.auth.models import Company, User
    from src.billing.settings_catalogue import value
    from src.common.admin_audit import record_admin_change
    from src.common.security import get_password_hash
    from src.partners.lifecycle import create_profile, new_agreement
    from src.partners.tree import partner_depth

    if app.status not in ("applied", "under_review"):
        raise HTTPException(status_code=409, detail=f"the application is {app.status}")
    if partner_type not in (SILVER, GOLD):
        raise HTTPException(status_code=422, detail="the type is SILVER or GOLD")
    needed = [k for k in CHECKLIST if k != "capability_assessment" or partner_type == GOLD]
    missing = [k for k in needed if not (app.checklist or {}).get(k)]
    if missing:
        raise HTTPException(status_code=422, detail=f"underwriting is not complete: {', '.join(missing)}")
    pan = (app.details or {}).get("pan")
    gstin = (app.details or {}).get("gstin")
    if pan and (await db.execute(select(PartnerProfile.company_id).where(PartnerProfile.pan == pan))).first():
        raise HTTPException(status_code=409, detail="A partner with that PAN exists")
    if gstin and (await db.execute(select(Company.id).where(Company.gstin == gstin))).first():
        raise HTTPException(status_code=409, detail="A company with that GSTIN exists")
    if (await db.execute(select(User.id).where(func.lower(User.email) == (app.email or "").lower()))).first():
        raise HTTPException(status_code=409, detail="That e-mail address already has an account")
    if app.recruiter_partner_id is not None:
        limit = int(await value(db, "partners.max_depth"))
        if await partner_depth(db, app.recruiter_partner_id) + 1 > limit:
            raise HTTPException(status_code=422, detail=f"partners are at most {limit} levels deep")
    company = Company(name=app.company_name or app.contact_name or app.email, type="PARTNER", status="active",
                      parent_id=app.recruiter_partner_id, legal_name=app.company_name, gstin=gstin,
                      onboarding_status="completed",
                      onboarding_metadata={"created_via": "partner_application", "application_id": str(app.id)})
    await set_geography(db, company, app.country_code)
    db.add(company)
    await db.flush()
    profile = await create_profile(db, company, partner_type=partner_type, status="approved",
                                   recruiter_id=app.recruiter_partner_id, reason="application approved", pan=pan,
                                   gstin=gstin)
    await new_agreement(db, profile)
    user = User(email=app.email, full_name=app.contact_name or app.email, role="partner_admin",
                company_id=company.id, hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                is_active=True, is_verified=True)
    db.add(user)
    app.status, app.approved_type, app.company_id = "approved", partner_type, company.id
    app.reviewed_by, app.reviewed_at, app.updated_at = actor.id, datetime.utcnow(), datetime.utcnow()
    if notes:
        app.review_notes = notes
    record_admin_change(db, actor=actor, action="approve", object_type="partner_application", object_key=str(app.id),
                        target_company_id=company.id, new_value={"type": partner_type, "company": company.name},
                        reason=notes)
    await db.commit()
    try:
        from src.auth.account_emails import send_password_reset_email
        await send_password_reset_email(user.email, user.hashed_password)     # the admin sets a password
    except Exception:  # noqa: BLE001
        logger.warning("partner admin %s was not e-mailed", user.email, exc_info=True)
    return {"application": view(app), "company_id": str(company.id), "user_id": str(user.id)}


async def reject(db: Any, app: PartnerApplication, *, actor: Any, notes: str) -> PartnerApplication:
    from src.common.admin_audit import record_admin_change

    if app.status not in OPEN:
        raise HTTPException(status_code=409, detail=f"the application is {app.status}")
    app.status, app.review_notes = "rejected", notes
    app.reviewed_by, app.reviewed_at, app.updated_at = actor.id, datetime.utcnow(), datetime.utcnow()
    record_admin_change(db, actor=actor, action="reject", object_type="partner_application", object_key=str(app.id),
                        reason=notes)
    return app
