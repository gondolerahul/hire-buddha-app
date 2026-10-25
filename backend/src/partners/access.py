"""A Gold partner working inside a tenant: access grants (Phase 15 T8-4, tech design §11.9).

``X-Company-Id`` from a partner's people is accepted only for a tenant the
partner resells (``scope``) **and** with an active grant: not revoked, not
expired. A grant's scopes decide what the request may do —

* ``read``: look only (GET, HEAD, OPTIONS);
* ``support``: read and change, but not delete, and not billing;
* ``billing``: read, and the tenant's billing (wallet, plan, invoices);
* ``admin``: everything.

A ``partner_user`` never gets more than read and support (07 §6). A tenant the
partner created gets an ``admin`` grant with no expiry; the tenant's admins
see, approve, renew and revoke grants (``/api/v1/settings/partner-access``).
Every request made under a grant is recorded (``partner_access_events``).
A request that names the tenant in its body or query instead of the header
goes through the same check (``check_target``).

A tenant attributed to the partner only through ``parent_id`` — no
assignment and no grant ever (rows made before the programme) — is acted in
as before, with ``admin``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from src.partners.models import GRANT_SCOPES, PartnerAccessEvent, PartnerAccessGrant, PartnerAssignment, PartnerProfile

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BILLING_PATHS = ("/api/v1/credits", "/api/v1/billing", "/api/v1/plans", "/api/v1/charges")
USER_SCOPES = frozenset({"read", "support"})          # the most a partner_user acts with


def _live() -> Any:
    now = datetime.utcnow()
    return and_(PartnerAccessGrant.status == "active", PartnerAccessGrant.revoked_at.is_(None),
                or_(PartnerAccessGrant.expires_at.is_(None), PartnerAccessGrant.expires_at > now))


def clean_scopes(scopes: Iterable[str]) -> List[str]:
    out = sorted({str(s).lower() for s in scopes})
    unknown = [s for s in out if s not in GRANT_SCOPES]
    if not out or unknown:
        raise HTTPException(status_code=422, detail=f"scopes are some of {', '.join(GRANT_SCOPES)}")
    return out


async def active_grant(db: Any, partner_id: UUID, tenant_id: UUID) -> Optional[PartnerAccessGrant]:
    return (await db.execute(select(PartnerAccessGrant).where(
        PartnerAccessGrant.partner_id == partner_id, PartnerAccessGrant.tenant_id == tenant_id, _live())
        .order_by(PartnerAccessGrant.created_at.desc()).limit(1))).scalar_one_or_none()


async def grant_for_created_tenant(db: Any, *, partner_id: UUID, tenant_id: UUID,
                                   actor_id: Optional[UUID] = None) -> PartnerAccessGrant:
    """A Gold partner's ``admin`` grant on a tenant it created (the caller commits)."""
    grant = PartnerAccessGrant(partner_id=partner_id, tenant_id=tenant_id, scopes=["admin"], status="active",
                               reason="the partner created the tenant", granted_by=actor_id, requested_by=actor_id)
    db.add(grant)
    await db.flush()
    return grant


async def _legacy(db: Any, partner_id: UUID, tenant_id: UUID) -> bool:
    """A tenant under the partner with no assignment and no grant ever (made before the programme)."""
    from src.auth.models import Company

    if (await db.execute(select(PartnerAssignment.id).where(PartnerAssignment.tenant_id == tenant_id))).first():
        return False
    if (await db.execute(select(PartnerAccessGrant.id).where(PartnerAccessGrant.tenant_id == tenant_id,
                                                             PartnerAccessGrant.partner_id == partner_id))).first():
        return False
    parent = (await db.execute(select(Company.parent_id).where(Company.id == tenant_id))).scalar_one_or_none()
    return parent == partner_id


def allows(scopes: Iterable[str], method: str, path: str) -> bool:
    """Whether a request ``method path`` fits ``scopes``."""
    scopes = set(scopes)
    if "admin" in scopes:
        return True
    billing = any(path.startswith(prefix) for prefix in BILLING_PATHS)
    if method.upper() in SAFE_METHODS:
        return bool(scopes & {"read", "support", "billing"})
    if billing:
        return "billing" in scopes
    return "support" in scopes and method.upper() != "DELETE"


async def check_acting(db: Any, *, user: Any, tenant_id: UUID, method: str, path: str) -> None:
    """403 unless the partner's person may make this request inside ``tenant_id``; records it when it may."""
    partner_id = user.company_id
    profile = await db.get(PartnerProfile, partner_id)
    if profile is not None and profile.status in ("suspended", "terminated"):
        raise HTTPException(status_code=403, detail={
            "code": "partner_suspended",
            "message": f"Your partnership is {profile.status}: you cannot work in your customers' accounts now."})
    grant = await active_grant(db, partner_id, tenant_id)
    if grant is None:
        if not await _legacy(db, partner_id, tenant_id):
            raise HTTPException(status_code=403, detail={
                "code": "no_access_grant",
                "message": "You have no access to this business's data now: ask its admin for an access grant."})
        scopes: set = {"admin"}
    else:
        scopes = set(grant.scopes or [])
    if str(user.role) == "partner_user":
        scopes = (scopes & USER_SCOPES) or ({"read", "support"} if "admin" in scopes else set())
    if not allows(scopes, method, path):
        raise HTTPException(status_code=403, detail={
            "code": "grant_scope", "message": f"Your access to this business ({', '.join(sorted(scopes)) or 'none'}) "
                                              f"does not allow this."})
    await record(partner_id=partner_id, user_id=user.id, tenant_id=tenant_id, grant_id=grant.id if grant else None,
                 method=method, path=path)


async def check_target(db: Any, *, user: Any, company_id: Optional[UUID], method: str, path: str) -> None:
    """The grant check for a request that names its tenant in the body or query
    rather than ``X-Company-Id`` (an agent created for a tenant, a tenant's
    people): the same rule either way. Nothing for anyone but a partner's
    people, or for the partner's own company."""
    if company_id is None or company_id == user.company_id:
        return
    if str(user.role) not in ("partner_admin", "partner_user"):
        return
    await check_acting(db, user=user, tenant_id=company_id, method=method, path=path)


async def record(*, partner_id: UUID, user_id: UUID, tenant_id: UUID, grant_id: Optional[UUID], method: str,
                 path: str) -> None:
    """One row per request under a grant, in a session of its own (never fails the request)."""
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as session:
            session.add(PartnerAccessEvent(grant_id=grant_id, partner_id=partner_id, user_id=user_id,
                                           tenant_id=tenant_id, method=method.upper()[:8], path=path[:500]))
            await session.commit()
    except Exception:  # noqa: BLE001 - the audit is best-effort; the request goes on
        logger.warning("partner access event not recorded (%s in %s)", partner_id, tenant_id, exc_info=True)


async def request_grant(db: Any, *, partner_id: UUID, tenant_id: UUID, scopes: Iterable[str], reason: str,
                        days: Optional[int], actor_id: UUID) -> PartnerAccessGrant:
    """A partner asks a tenant it resells for access; the tenant's admin approves it (the caller commits)."""
    from src.partners.scope import data_scope

    if tenant_id not in await data_scope(db, partner_id):
        raise HTTPException(status_code=403, detail="Only a business you resell can give you access")
    grant = PartnerAccessGrant(partner_id=partner_id, tenant_id=tenant_id, scopes=clean_scopes(scopes),
                               status="requested", reason=reason, requested_by=actor_id,
                               expires_at=datetime.utcnow() + timedelta(days=days) if days else None)
    db.add(grant)
    await db.flush()
    return grant


async def decide(db: Any, grant: PartnerAccessGrant, *, approve: bool, actor_id: UUID,
                 days: Optional[int] = None) -> PartnerAccessGrant:
    """The tenant's admin approves (or renews) or revokes a grant (the caller commits)."""
    now = datetime.utcnow()
    if approve:
        grant.status, grant.granted_by = "active", actor_id
        if days:
            grant.expires_at = now + timedelta(days=days)
        grant.revoked_at = grant.revoked_by = None
    else:
        grant.status, grant.revoked_at, grant.revoked_by = "revoked", now, actor_id
    return grant


async def revoke_all(db: Any, *, partner_id: UUID, tenant_id: Optional[UUID] = None,
                     actor_id: Optional[UUID] = None) -> int:
    """Revoke a partner's grants (on one tenant, or all): reassignment and termination (T8-11)."""
    query = select(PartnerAccessGrant).where(PartnerAccessGrant.partner_id == partner_id,
                                             PartnerAccessGrant.status != "revoked")
    if tenant_id is not None:
        query = query.where(PartnerAccessGrant.tenant_id == tenant_id)
    rows = (await db.execute(query)).scalars().all()
    for grant in rows:
        await decide(db, grant, approve=False, actor_id=actor_id)
    return len(rows)


def view(grant: PartnerAccessGrant, *, names: Optional[dict] = None) -> dict:
    names = names or {}
    now = datetime.utcnow()
    live = grant.status == "active" and (grant.expires_at is None or grant.expires_at > now)
    return {"id": str(grant.id), "partner_id": str(grant.partner_id), "partner": names.get(grant.partner_id),
            "tenant_id": str(grant.tenant_id), "tenant": names.get(grant.tenant_id), "scopes": grant.scopes,
            "status": grant.status if grant.status != "active" or live else "expired", "reason": grant.reason,
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "created_at": grant.created_at.isoformat() if grant.created_at else None,
            "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None}
