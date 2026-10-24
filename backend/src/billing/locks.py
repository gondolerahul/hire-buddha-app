"""Company locks (Phase 15 T5-4, tech design §8.5, Q5).

A company's spend cap or plan can be locked, so the tenant (or its partner)
cannot change it: a lock set by a partner blocks the tenant; one set by
app_admin blocks the tenant and the partner. Staff are never blocked.

    GET    /api/v1/companies/{company_id}/locks          the company's locks
    PUT    /api/v1/companies/{company_id}/locks/{key}    {reason}: app_admin (any company) or the owning partner_admin
    DELETE /api/v1/companies/{company_id}/locks/{key}    whoever may set it, and only a lock of their own level

Each change is audited (``admin_audit_log``, object type ``company_lock``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Company, User
from src.auth.roles import Role
from src.auth.router import get_current_user
from src.billing.billing_models import CompanyLock
from src.common.tenancy.session import get_control_db

KEYS = ("spend_cap", "plan")
LABELS = {"spend_cap": "the monthly spend cap", "plan": "the plan"}
PARTNER_ROLES = (Role.PARTNER_ADMIN, Role.PARTNER_USER)

router = APIRouter(prefix="/api/v1/companies", tags=["Company locks"])


def _role(user: Any) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "value", role) or "")


def blocks(lock: CompanyLock, user: Any) -> bool:
    """Whether ``lock`` stops ``user`` changing the value."""
    role = _role(user)
    if role in (Role.APP_ADMIN.value, Role.APP_USER.value):
        return False
    if role in (r.value for r in PARTNER_ROLES):
        return lock.locked_by_role == "app_admin"
    return True                                   # tenant roles: any lock


async def require_unlocked(db: AsyncSession, company_id: UUID, key: str, user: Any) -> None:
    """403 when ``key`` of the company is locked against ``user``."""
    lock = await db.get(CompanyLock, (company_id, key))
    if lock is not None and blocks(lock, user):
        who = "HireBuddha" if lock.locked_by_role == "app_admin" else "your partner"
        raise HTTPException(status_code=403, detail=(
            f"{LABELS[key].capitalize()} is locked by {who}" + (f": {lock.reason}" if lock.reason else "")
            + ". Ask them to change it."))


def _view(lock: CompanyLock) -> dict:
    return {"key": lock.key, "locked_by_role": lock.locked_by_role,
            "locked_by": str(lock.locked_by) if lock.locked_by else None, "reason": lock.reason,
            "at": lock.at.isoformat() if lock.at else None}


async def _resells(db: AsyncSession, partner_id: UUID, tenant_id: UUID) -> bool:
    """Whether the partner currently resells the tenant (Phase 15 T8-3)."""
    from src.partners.scope import tenant_ids
    return tenant_id in await tenant_ids(db, partner_id, relationship="resold")


async def _may_lock(db: AsyncSession, company_id: UUID, user: User) -> str:
    """The level ``user`` locks at for this company (``app_admin`` | ``partner``), or 403/404."""
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if user.role == Role.APP_ADMIN:
        return "app_admin"
    if user.role == Role.PARTNER_ADMIN and await _resells(db, user.company_id, company.id):
        return "partner"
    raise HTTPException(status_code=403, detail="Only HireBuddha staff or the company's partner set its locks")


@router.get("/{company_id}/locks")
async def list_locks(company_id: UUID, db: AsyncSession = Depends(get_control_db),
                     user: User = Depends(get_current_user)):
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if not (user.role == Role.APP_ADMIN or company.id == user.company_id
            or (user.role in PARTNER_ROLES and await _resells(db, user.company_id, company.id))):
        raise HTTPException(status_code=403, detail="Not your company")
    rows = (await db.execute(select(CompanyLock).where(CompanyLock.company_id == company_id))).scalars().all()
    return [_view(lock) for lock in rows]


class LockBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


@router.put("/{company_id}/locks/{key}")
async def set_lock(company_id: UUID, key: str, body: LockBody, db: AsyncSession = Depends(get_control_db),
                   user: User = Depends(get_current_user)):
    from src.common.admin_audit import record_admin_change

    if key not in KEYS:
        raise HTTPException(status_code=404, detail=f"no lock {key!r} (one of {', '.join(KEYS)})")
    level = await _may_lock(db, company_id, user)
    lock = await db.get(CompanyLock, (company_id, key))
    if lock is not None and lock.locked_by_role == "app_admin" and level != "app_admin":
        raise HTTPException(status_code=403, detail="HireBuddha holds this lock")
    old = _view(lock) if lock else None
    if lock is None:
        lock = CompanyLock(company_id=company_id, key=key, locked_by_role=level)
        db.add(lock)
    lock.locked_by_role, lock.locked_by, lock.reason, lock.at = level, user.id, body.reason, datetime.utcnow()
    await db.flush()
    record_admin_change(db, actor=user, action="lock", object_type="company_lock", object_key=key,
                        target_company_id=company_id, old_value=old, new_value=_view(lock), reason=body.reason)
    await db.commit()
    return _view(lock)


@router.delete("/{company_id}/locks/{key}")
async def remove_lock(company_id: UUID, key: str, reason: Optional[str] = None,
                      db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    from src.common.admin_audit import record_admin_change

    level = await _may_lock(db, company_id, user)
    lock = await db.get(CompanyLock, (company_id, key))
    if lock is None:
        return {"key": key, "removed": False}
    if lock.locked_by_role == "app_admin" and level != "app_admin":
        raise HTTPException(status_code=403, detail="HireBuddha holds this lock")
    old = _view(lock)
    await db.delete(lock)
    record_admin_change(db, actor=user, action="unlock", object_type="company_lock", object_key=key,
                        target_company_id=company_id, old_value=old, reason=reason)
    await db.commit()
    return {"key": key, "removed": True}
