"""Moving a tenant between partners, and ending a partnership (Phase 15 T8-11, tech design §11.3, §11.8).

* Staff reassign a tenant with an effective date: the current assignment ends
  then and the new one (another partner, or none — BCL direct) starts; a
  payment is attributed to the assignment in force when it was made, so a
  month split across the move is split too. The old partner's access grants
  on the tenant are revoked; a Gold partner taking a resold tenant gets one.
* Termination: the partner's tenants go to BCL direct (notified), its grants
  are revoked, and its unpaid accrued and held earnings are forfeited; what is
  already payable is paid at the next statement, less clawbacks.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from src.partners.models import PartnerAssignment, PartnerProfile


def view(row: PartnerAssignment, *, names: Optional[dict] = None) -> Dict[str, Any]:
    names = names or {}
    return {"id": str(row.id), "tenant_id": str(row.tenant_id), "tenant": names.get(row.tenant_id),
            "partner_id": str(row.partner_id), "partner": names.get(row.partner_id),
            "relationship": row.relationship, "since": row.since.isoformat() if row.since else None,
            "until": row.until.isoformat() if row.until else None,
            "commission_until": row.commission_until.isoformat() if row.commission_until else None,
            "source": row.source, "reason": row.reason}


async def history(db: Any, tenant_id: UUID) -> list:
    return list((await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == tenant_id)
                                  .order_by(PartnerAssignment.since))).scalars().all())


async def reassign(db: Any, *, tenant_id: UUID, partner_id: Optional[UUID], relationship: str,
                   effective_from: Optional[datetime], reason: str, actor: Any,
                   commission_until: Optional[datetime] = None) -> Optional[PartnerAssignment]:
    """Staff move a tenant (the caller commits); ``partner_id`` None makes it BCL direct."""
    from src.auth.models import Company
    from src.auth.platform import platform_company_id
    from src.common.admin_audit import record_admin_change
    from src.partners.access import grant_for_created_tenant, revoke_all
    from src.partners.scope import assign

    tenant = await db.get(Company, tenant_id)
    if tenant is None or tenant.type != "TENANT":
        raise HTTPException(status_code=404, detail="No such business")
    if relationship not in ("referred", "resold"):
        raise HTTPException(status_code=422, detail="the relationship is referred or resold")
    when = effective_from or datetime.utcnow()
    current = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == tenant_id,
                                                                PartnerAssignment.until.is_(None))
                                .with_for_update())).scalar_one_or_none()
    if current is not None and when < current.since:
        raise HTTPException(status_code=422, detail="the move cannot be before the current assignment began")
    new_profile = None
    if partner_id is not None:
        new_profile = await db.get(PartnerProfile, partner_id)
        if new_profile is None:
            raise HTTPException(status_code=404, detail="No such partner")
        if new_profile.status in ("suspended", "terminated"):
            raise HTTPException(status_code=409, detail=f"that partner is {new_profile.status}")
        if relationship == "resold" and new_profile.partner_type != "GOLD":
            raise HTTPException(status_code=422, detail="a Silver partner refers; it does not resell")
    old = current.partner_id if current else None
    if current is not None:
        current.until = when
        await db.flush()
        await revoke_all(db, partner_id=current.partner_id, tenant_id=tenant_id, actor_id=actor.id)
    row = None
    if partner_id is not None:
        row = await assign(db, tenant_id=tenant_id, partner_id=partner_id, relationship=relationship,
                           source="staff", actor_id=actor.id, reason=reason, since=when)
        row.commission_until = commission_until
        if relationship == "resold":
            await grant_for_created_tenant(db, partner_id=partner_id, tenant_id=tenant_id, actor_id=actor.id)
    tenant.parent_id = partner_id if relationship == "resold" and partner_id else await platform_company_id(db)
    record_admin_change(db, actor=actor, action="reassign", object_type="partner_assignment",
                        object_key=str(tenant_id), target_company_id=tenant_id,
                        old_value={"partner_id": str(old) if old else None},
                        new_value={"partner_id": str(partner_id) if partner_id else None,
                                   "relationship": relationship, "effective_from": when.isoformat()}, reason=reason)
    return row


async def terminate(db: Any, *, partner_id: UUID, reason: str, actor: Any) -> Dict[str, int]:
    """End the partnership (commits)."""
    from src.auth.models import Company
    from src.auth.platform import platform_company_id
    from src.notifications.service import notify
    from src.partners.access import revoke_all
    from src.partners.lifecycle import set_status

    profile = await db.get(PartnerProfile, partner_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No such partner")
    now = datetime.utcnow()
    platform = await platform_company_id(db)
    moved = []
    for row in (await db.execute(select(PartnerAssignment).where(PartnerAssignment.partner_id == partner_id,
                                                                 PartnerAssignment.until.is_(None)))).scalars().all():
        row.until = now
        tenant = await db.get(Company, row.tenant_id)
        if tenant is not None and tenant.parent_id == partner_id:
            tenant.parent_id = platform
        moved.append(row.tenant_id)
    grants = await revoke_all(db, partner_id=partner_id, actor_id=actor.id)
    await set_status(db, profile, "terminated", actor=actor, reason=reason)
    await db.commit()
    for tenant_id in moved:
        await notify(tenant_id, kind="partner.ended", title="Your partner has left the HireBuddha programme",
                     body="HireBuddha looks after your account directly from now on.", link="/settings/partner-access",
                     severity="info", dedupe_key=f"partner.ended:{partner_id}:{tenant_id}")
    return {"tenants": len(moved), "grants": grants}
