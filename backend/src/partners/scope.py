"""Which tenants a partner has (Phase 15 T8-3, tech design §11.9).

``partner_assignments`` says which partner a tenant is attributed to, over
time; the current one has no ``until``. A partner's **data** scope is its own
company and the tenants it currently resells (``relationship='resold'``) —
Gold only; a Silver partner (``tenant_data_access='none'``) sees no tenant's
data, and nobody sees a sub-partner's tenants.

A tenant under a partner (``parent_id``) with no assignment at all is
counted as resold by that partner: rows made before the programme (the
migration gives every such tenant an assignment, so this is only data made
since without one, e.g. by hand). A partner company without a profile is
treated as Gold for the same reason.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy import and_, exists, or_, select

from src.partners.models import GOLD, PartnerAssignment, PartnerProfile, PartnerType


async def profile_of(db: Any, partner_id: UUID) -> Optional[PartnerProfile]:
    return await db.get(PartnerProfile, partner_id)


async def partner_type_of(db: Any, partner_id: UUID) -> str:
    kind = (await db.execute(select(PartnerProfile.partner_type).where(PartnerProfile.company_id == partner_id))
            ).scalar_one_or_none()
    return kind or GOLD


async def sees_tenant_data(db: Any, partner_id: UUID) -> bool:
    """Gold sees its resold tenants' data (through grants); Silver none (§11.1)."""
    access = (await db.execute(select(PartnerType.tenant_data_access).where(
        PartnerType.code == await partner_type_of(db, partner_id)))).scalar_one_or_none()
    return access != "none"


def _current(at: Optional[datetime] = None) -> Any:
    if at is None:
        return PartnerAssignment.until.is_(None)
    return and_(PartnerAssignment.since <= at, or_(PartnerAssignment.until.is_(None), PartnerAssignment.until > at))


async def tenant_ids(db: Any, partner_id: UUID, *, relationship: Optional[str] = None) -> List[UUID]:
    """The tenants currently attributed to the partner (``relationship``: resold or referred; both when None)."""
    from src.auth.models import Company

    query = select(PartnerAssignment.tenant_id).where(PartnerAssignment.partner_id == partner_id, _current())
    if relationship:
        query = query.where(PartnerAssignment.relationship == relationship)
    ids = set((await db.execute(query)).scalars().all())
    if relationship in (None, "resold"):
        legacy = select(Company.id).where(
            Company.type == "TENANT", Company.parent_id == partner_id,
            ~exists().where(PartnerAssignment.tenant_id == Company.id))
        ids.update((await db.execute(legacy)).scalars().all())
    return sorted(ids, key=str)


async def assignment_of(db: Any, tenant_id: UUID, at: Optional[datetime] = None) -> Optional[PartnerAssignment]:
    """The tenant's assignment in force at ``at`` (now)."""
    return (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == tenant_id, _current(at))
                             .order_by(PartnerAssignment.since.desc()).limit(1))).scalar_one_or_none()


async def partner_of(db: Any, tenant_id: UUID, at: Optional[datetime] = None) -> Optional[UUID]:
    """The partner a tenant is attributed to (its assignment, else a partner parent with none)."""
    from src.auth.models import Company

    assignment = await assignment_of(db, tenant_id, at)
    if assignment is not None:
        return assignment.partner_id
    if (await db.execute(select(PartnerAssignment.id).where(PartnerAssignment.tenant_id == tenant_id))).first():
        return None                                     # it had assignments, none in force: platform direct
    parent = (await db.execute(select(Company.parent_id).where(Company.id == tenant_id))).scalar_one_or_none()
    if parent is None:
        return None
    kind = (await db.execute(select(Company.type).where(Company.id == parent))).scalar_one_or_none()
    return parent if kind == "PARTNER" else None


async def data_scope(db: Any, partner_id: UUID) -> frozenset:
    """The companies a partner's people may see: its own, and — Gold — its resold tenants."""
    if not await sees_tenant_data(db, partner_id):
        return frozenset({partner_id})
    return frozenset({partner_id, *await tenant_ids(db, partner_id, relationship="resold")})


async def assign(db: Any, *, tenant_id: UUID, partner_id: UUID, relationship: str, source: str,
                 actor_id: Optional[UUID] = None, reason: Optional[str] = None,
                 since: Optional[datetime] = None) -> PartnerAssignment:
    """Open the tenant's assignment to ``partner_id`` (the caller closes any current one; commits not)."""
    row = PartnerAssignment(tenant_id=tenant_id, partner_id=partner_id, relationship=relationship,
                            since=since or datetime.utcnow(), source=source, created_by=actor_id, reason=reason)
    db.add(row)
    await db.flush()
    return row
