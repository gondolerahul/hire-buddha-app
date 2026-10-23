"""The shadow comparison, for staff (Phase 15 T3-7).

    GET /api/v1/admin/billing-shadow?days=14    the mode, a summary, and the settlements that differ
    PUT /api/v1/admin/billing-shadow/mode       off | shadow ("on" waits for the new settlement, WS15-4)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import User
from src.auth.roles import Role
from src.billing.billing_models import BillingShadowDiff
from src.billing.shadow import v2_mode
from src.common.settings_store import set_platform_setting
from src.common.tenancy.session import get_control_db

router = APIRouter(prefix="/api/v1/admin/billing-shadow", tags=["Billing shadow"])
staff = RoleChecker([Role.APP_ADMIN])
# A difference smaller than this is arithmetic noise at 10 decimals, not a billing difference.
TOLERANCE_USD = Decimal("0.0000001")


def _diff_dict(d: BillingShadowDiff) -> dict:
    return {"id": str(d.id), "company_id": str(d.company_id), "subject_type": d.subject_type,
            "subject_id": str(d.subject_id) if d.subject_id else None, "rows": d.rows,
            "v1_cost_usd": float(d.v1_cost_usd), "v1_billed_usd": float(d.v1_billed_usd),
            "v2_cost_usd": float(d.v2_cost_usd), "v2_billed_usd": float(d.v2_billed_usd),
            "diff_usd": float(d.diff_usd), "formula_ids": d.formula_ids or [],
            "created_at": d.created_at.isoformat() if d.created_at else None}


@router.get("")
async def shadow_summary(days: int = Query(14, ge=1, le=90), company_id: Optional[str] = Query(None),
                         db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    since = datetime.utcnow() - timedelta(days=days)
    where = [BillingShadowDiff.created_at >= since]
    if company_id:
        where.append(BillingShadowDiff.company_id == company_id)
    differs = func.abs(BillingShadowDiff.diff_usd) > TOLERANCE_USD
    count, mismatches, v1, v2, worst = (await db.execute(select(
        func.count(), func.count().filter(differs), func.coalesce(func.sum(BillingShadowDiff.v1_billed_usd), 0),
        func.coalesce(func.sum(BillingShadowDiff.v2_billed_usd), 0),
        func.coalesce(func.max(func.abs(BillingShadowDiff.diff_usd)), 0)).where(*where))).one()
    recent = (await db.execute(select(BillingShadowDiff).where(*where)
                               .order_by(differs.desc(), BillingShadowDiff.created_at.desc()).limit(100))
              ).scalars().all()
    return {"mode": await v2_mode(db), "days": days,
            "summary": {"settlements": count, "differing": mismatches, "v1_billed_usd": float(v1),
                        "v2_billed_usd": float(v2), "max_abs_diff_usd": float(worst)},
            "recent": [_diff_dict(d) for d in recent]}


class ModeBody(BaseModel):
    mode: Literal["off", "shadow", "on"]
    reason: Optional[str] = None


@router.put("/mode")
async def set_mode(body: ModeBody, db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    if body.mode == "on":
        raise HTTPException(status_code=422, detail=(
            "The new settlement (wallet lots and debt, WS15-4) is not built yet: 'on' would charge nothing "
            "differently. Use 'shadow' until it is."))
    await set_platform_setting(db, "billing.v2_mode", body.mode, actor=user, reason=body.reason)
    await db.commit()
    return {"mode": await v2_mode(db)}
