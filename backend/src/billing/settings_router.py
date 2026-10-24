"""Money settings, for staff (Phase 15 T5-1; tech design §8.4, §15).

    GET    /api/v1/admin/billing-settings?company_id=      every setting, its value and where it comes from
    GET    /api/v1/admin/billing-settings/{key}/history    who changed it, when, from what
    PUT    /api/v1/admin/billing-settings/{key}            {value, scope, scope_id, reason}
    DELETE /api/v1/admin/billing-settings/{key}?scope=&scope_id=   the next scope's value applies again

Only ``app_admin`` (§8.4: every money setting's editor); each change is audited.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import Company, User
from src.auth.roles import Role
from src.billing.settings_catalogue import (
    COMPANY, PARTNER, PLAN, PLATFORM, InvalidSetting, UnknownSetting, coerce, explain, spec_for,
)
from src.common.settings_store import delete_setting, set_setting
from src.common.tenancy.session import get_control_db

router = APIRouter(prefix="/api/v1/admin/billing-settings", tags=["Money settings"])
staff = RoleChecker([Role.APP_ADMIN])


def _spec(key: str):
    try:
        return spec_for(key)
    except UnknownSetting:
        raise HTTPException(status_code=404, detail=f"unknown setting {key!r}") from None


async def _check_scope(db: AsyncSession, spec: Any, scope: str, scope_id: Optional[UUID]) -> None:
    if scope not in spec.scopes:
        raise HTTPException(status_code=422, detail=f"{spec.key} can be set at {', '.join(spec.scopes)} only")
    if scope == PLATFORM:
        if scope_id is not None:
            raise HTTPException(status_code=422, detail="the platform scope takes no scope_id")
        return
    if scope_id is None:
        raise HTTPException(status_code=422, detail=f"scope {scope} needs a scope_id")
    if scope in (COMPANY, PARTNER):
        kind = (await db.execute(select(Company.type).where(Company.id == scope_id))).scalar_one_or_none()
        if kind is None:
            raise HTTPException(status_code=404, detail="no such company")
        if scope == PARTNER and kind != "PARTNER":
            raise HTTPException(status_code=422, detail="that company is not a partner")
    if scope == PLAN:
        from src.billing.billing_models import Plan
        if (await db.execute(select(Plan.id).where(Plan.id == scope_id))).scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="no such plan")


@router.get("")
async def list_settings(company_id: Optional[UUID] = Query(None, description="Resolve for this company"),
                        db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    return {"company_id": str(company_id) if company_id else None, "settings": await explain(db, company_id)}


@router.get("/{key}/history")
async def setting_history(key: str, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    _spec(key)
    rows = (await db.execute(text(
        "SELECT at, action, actor_user_id, scope, old_value, new_value, reason FROM admin_audit_log "
        "WHERE object_type = 'setting' AND object_key = :k ORDER BY at DESC LIMIT 100"), {"k": key})).all()
    return [{"at": r.at.isoformat() if r.at else None, "action": r.action,
             "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None, "scope": r.scope,
             "old_value": r.old_value, "new_value": r.new_value, "reason": r.reason} for r in rows]


class SettingBody(BaseModel):
    value: Any = None
    scope: str = PLATFORM
    scope_id: Optional[UUID] = None
    reason: Optional[str] = None


@router.put("/{key}")
async def put_setting(key: str, body: SettingBody, db: AsyncSession = Depends(get_control_db),
                      user: User = Depends(staff)):
    spec = _spec(key)
    await _check_scope(db, spec, body.scope, body.scope_id)
    try:
        stored = coerce(spec, body.value)
    except InvalidSetting as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if key == "billing.v2_mode" and stored == "on":
        # The switch-on (T10-3): only when the cutover readiness report has no blockers.
        from src.billing import cutover
        await cutover.require_ready(db)
    await set_setting(db, key, stored, scope=body.scope, scope_id=body.scope_id, actor=user, reason=body.reason)
    await db.commit()
    from src.billing import rollout
    rollout.forget()
    return {"key": key, "scope": body.scope, "scope_id": str(body.scope_id) if body.scope_id else None,
            "value": stored}


@router.delete("/{key}")
async def remove_setting(key: str, scope: str = Query(PLATFORM), scope_id: Optional[UUID] = Query(None),
                         reason: Optional[str] = Query(None), db: AsyncSession = Depends(get_control_db),
                         user: User = Depends(staff)):
    spec = _spec(key)
    await _check_scope(db, spec, scope, scope_id)
    removed = await delete_setting(db, key, scope=scope, scope_id=scope_id, actor=user, reason=reason)
    await db.commit()
    return {"key": key, "removed": removed}
