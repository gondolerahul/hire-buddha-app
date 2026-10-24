"""A partner's life: approved → active → renewal_due → lapsed → suspended → terminated (Phase 15 T8-5, T8-6, §11.3).

* ``approved``: underwriting passed, type set by staff; becomes ``active``
  when the agreement is signed and — if the type has an annual fee — the fee
  is paid. A new partner is on probation (``partners.probation_days``), with a
  longer commission holdback.
* With a fee, ``renewal_due`` 30 days before it runs out, ``lapsed`` when it
  does (no new tenants; earnings held), ``suspended`` after the grace
  (``partners.fee_grace_days``; held earnings forfeited to the platform).
* Staff suspend for a compliance breach, reactivate, or terminate
  (``assignments.terminate``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, update

from src.partners.models import EARNING_STATUSES, PartnerAgreement, PartnerLedgerEntry, PartnerProfile, PartnerType

logger = logging.getLogger(__name__)

TRANSITIONS = {
    "approved": {"active", "suspended", "terminated"},
    "active": {"renewal_due", "lapsed", "suspended", "terminated"},
    "renewal_due": {"active", "lapsed", "suspended", "terminated"},
    "lapsed": {"active", "suspended", "terminated"},
    "suspended": {"active", "terminated"},
    "terminated": set(),
}


async def create_profile(db: Any, company: Any, *, partner_type: str, status: str = "approved",
                         recruiter_id: Optional[UUID] = None, reason: Optional[str] = None,
                         pan: Optional[str] = None, gstin: Optional[str] = None) -> PartnerProfile:
    """The profile of a partner company just made (the caller commits)."""
    from src.partners.tree import partner_depth

    if (await db.get(PartnerType, partner_type)) is None:
        raise HTTPException(status_code=422, detail="the partner type is SILVER or GOLD")
    depth = 1
    recruiter = None
    if recruiter_id is not None:
        kind = (await db.execute(select(company.__class__.type).where(company.__class__.id == recruiter_id))
                ).scalar_one_or_none()
        if kind == "PARTNER":
            recruiter = recruiter_id
            depth = await partner_depth(db, recruiter_id) + 1
    now = datetime.utcnow()
    profile = PartnerProfile(company_id=company.id, partner_type=partner_type, status=status,
                             legal_name=company.legal_name or company.name, country_code=company.country_code,
                             billing_currency=company.billing_currency, gstin=gstin or company.gstin, pan=pan,
                             recruiter_partner_id=recruiter, depth=depth, status_reason=reason)
    if status == "active":
        profile.activated_at = now
        profile.probation_until = now + timedelta(days=await _probation_days(db))
    db.add(profile)
    await db.flush()
    return profile


async def _probation_days(db: Any) -> int:
    from src.billing.settings_catalogue import value
    return int(await value(db, "partners.probation_days"))


async def type_of(db: Any, partner_id: UUID) -> Optional[PartnerType]:
    profile = await db.get(PartnerProfile, partner_id)
    return await db.get(PartnerType, profile.partner_type) if profile else None


async def require_may_create_tenants(db: Any, partner_id: UUID) -> None:
    """A partner creates tenants when its type does (Gold) and it is active (§11.1, §11.3)."""
    profile = await db.get(PartnerProfile, partner_id)
    if profile is None:
        return                                  # a partner from before the programme (treated as Gold)
    kind = await db.get(PartnerType, profile.partner_type)
    if kind is None or not kind.can_create_tenants:
        raise HTTPException(status_code=403, detail="A Silver partner refers customers as leads; HireBuddha "
                                                    "creates their workspace")
    if profile.status not in EARNING_STATUSES:
        raise HTTPException(status_code=403, detail=f"The partnership is {profile.status}: no new customers "
                                                    "until it is active again")


async def require_active(db: Any, partner_id: UUID, what: str = "do this") -> PartnerProfile:
    profile = await db.get(PartnerProfile, partner_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Not a partner of the programme")
    if profile.status not in EARNING_STATUSES:
        raise HTTPException(status_code=403, detail=f"The partnership is {profile.status}: it cannot {what}")
    return profile


async def set_status(db: Any, profile: PartnerProfile, status: str, *, actor: Any = None,
                     reason: Optional[str] = None) -> PartnerProfile:
    """Move the profile (audited; the caller commits). Held and accrued earnings follow (§11.3)."""
    from src.common.admin_audit import record_admin_change

    before = profile.status
    if status == before:
        return profile
    if status not in TRANSITIONS.get(before, set()):
        raise HTTPException(status_code=409, detail=f"a {before} partner cannot become {status}")
    now = datetime.utcnow()
    profile.status, profile.status_reason, profile.updated_at = status, reason, now
    if status == "active":
        if profile.activated_at is None:
            profile.activated_at = now
            profile.probation_until = now + timedelta(days=await _probation_days(db))
        await release_held(db, profile.company_id, "lapsed")
    if status in ("suspended", "terminated"):
        await forfeit_held(db, profile.company_id, reason=f"partner {status}")
    if actor is not None:
        record_admin_change(db, actor=actor, action="set", object_type="partner_status",
                            object_key=str(profile.company_id), target_company_id=profile.company_id,
                            old_value={"status": before}, new_value={"status": status}, reason=reason)
    await notify_partner(profile.company_id, kind=f"partner.{status}",
                         title=f"Your partnership is {status.replace('_', ' ')}", body=reason)
    return profile


async def release_held(db: Any, partner_id: UUID, reason: str) -> int:
    """Earnings held for ``reason`` (lapsed, kyc) become accrued again."""
    result = await db.execute(update(PartnerLedgerEntry).where(
        PartnerLedgerEntry.partner_id == partner_id, PartnerLedgerEntry.status == "held",
        PartnerLedgerEntry.hold_reason == reason).values(status="accrued", hold_reason=None,
                                                         updated_at=datetime.utcnow()))
    return result.rowcount or 0


async def forfeit_held(db: Any, partner_id: UUID, *, reason: str) -> int:
    """Held and not yet payable earnings go back to the platform (suspension, termination)."""
    result = await db.execute(update(PartnerLedgerEntry).where(
        PartnerLedgerEntry.partner_id == partner_id, PartnerLedgerEntry.status.in_(("held", "accrued")))
        .values(status="reversed", reason=func.concat(func.coalesce(PartnerLedgerEntry.reason, ""), f" — forfeited ({reason})"),
                updated_at=datetime.utcnow()))
    return result.rowcount or 0


async def set_kyc(db: Any, profile: PartnerProfile, status: str, *, actor: Any, reason: Optional[str]) -> None:
    from src.common.admin_audit import record_admin_change

    if status not in ("pending", "verified", "rejected"):
        raise HTTPException(status_code=422, detail="KYC is pending, verified or rejected")
    before = profile.kyc_status
    profile.kyc_status, profile.updated_at = status, datetime.utcnow()
    if status == "verified":
        await release_held(db, profile.company_id, "kyc")
    record_admin_change(db, actor=actor, action="set", object_type="partner_kyc", object_key=str(profile.company_id),
                        target_company_id=profile.company_id, old_value={"kyc": before}, new_value={"kyc": status},
                        reason=reason)


async def latest_agreement(db: Any, partner_id: UUID) -> Optional[PartnerAgreement]:
    return (await db.execute(select(PartnerAgreement).where(PartnerAgreement.partner_id == partner_id)
                             .order_by(PartnerAgreement.version.desc()).limit(1))).scalar_one_or_none()


async def new_agreement(db: Any, profile: PartnerProfile) -> PartnerAgreement:
    """A new agreement version with today's rules snapshotted (the caller commits)."""
    from src.partners.rules import snapshot

    last = await latest_agreement(db, profile.company_id)
    now = datetime.utcnow()
    if last is not None and last.effective_to is None:
        last.effective_to = now
    agreement = PartnerAgreement(partner_id=profile.company_id, version=(last.version + 1) if last else 1,
                                 terms=await snapshot(db, profile.partner_type), effective_from=now)
    db.add(agreement)
    await db.flush()
    profile.agreement_id = agreement.id
    return agreement


async def sign(db: Any, profile: PartnerProfile, user: Any) -> PartnerAgreement:
    """The partner's admin signs its agreement; with no fee due, the partnership starts."""
    from src.partners.fees import fee_due

    agreement = await latest_agreement(db, profile.company_id) or await new_agreement(db, profile)
    if agreement.signed_at is None:
        agreement.signed_at, agreement.signed_by = datetime.utcnow(), user.id
    if profile.status == "approved" and (await fee_due(db, profile)) is None:
        await set_status(db, profile, "active", reason="agreement signed")
    return agreement


async def notify_partner(partner_id: UUID, *, kind: str, title: str, body: Optional[str] = None,
                         link: str = "/partner/partnership", dedupe: Optional[str] = None) -> None:
    from src.notifications.service import notify

    try:
        await notify(partner_id, kind=kind, title=title, body=body, link=link, severity="info",
                     dedupe_key=dedupe or f"{kind}:{datetime.utcnow():%Y-%m-%dT%H}")
    except Exception:  # noqa: BLE001
        logger.warning("partner notice %s not sent", kind, exc_info=True)
