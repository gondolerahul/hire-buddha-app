"""The wallet, for staff and for the company (Phase 15 T4-1, T2-7; tech design §6, §15).

Staff (``app_admin``):

    GET  /api/v1/admin/wallets?state=&q=                    every wallet: currency, state, credit, debt
    GET  /api/v1/admin/wallets/{company_id}                  one wallet: balance, lots, ledger, consistency
    POST /api/v1/admin/wallets/{company_id}/adjust           {amount, reason, expires_in_days?} (W-1)
    POST /api/v1/admin/wallets/{company_id}/currency         {currency, reason}: the conversion tool (T2-7)

The company (any of its users):

    GET  /api/v1/credits/ledger?limit=&before=               its wallet's entries, newest first

No route moves value between companies (W-1, REQ-WL-2). Every staff write is
audited (``admin_audit_log``).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker
from src.auth.models import Company, User
from src.auth.roles import Role
from src.auth.router import get_current_user
from src.billing.billing_models import CreditWallet, WalletEntry, WalletLot
from src.common.tenancy.session import get_control_db

router = APIRouter(tags=["Wallet"])
staff = RoleChecker([Role.APP_ADMIN])


def _entry(e: WalletEntry, *, staff_view: bool) -> dict:
    out = {"id": str(e.id), "kind": e.kind, "amount": str(e.amount), "currency": e.currency,
           "balance_after": str(e.balance_after), "debt_after": str(e.debt_after), "category": e.category,
           "reason": e.reason, "source_type": e.source_type, "run_id": str(e.run_id) if e.run_id else None,
           "created_at": e.created_at.isoformat() if e.created_at else None}
    if staff_view:
        out.update(lot_id=str(e.lot_id) if e.lot_id else None, source_id=e.source_id,
                   actor_id=str(e.actor_id) if e.actor_id else None)
    return out


async def _entries(db: AsyncSession, company_id: UUID, limit: int, before: Optional[datetime], *,
                   staff_view: bool) -> list:
    query = select(WalletEntry).where(WalletEntry.company_id == company_id)
    if before is not None:
        query = query.where(WalletEntry.created_at < before)
    rows = (await db.execute(query.order_by(WalletEntry.created_at.desc(), WalletEntry.id.desc()).limit(limit))
            ).scalars().all()
    return [_entry(e, staff_view=staff_view) for e in rows]


def _wallet_view(balance: dict) -> dict:
    return {**{k: str(v) for k, v in balance.items() if isinstance(v, Decimal)},
            "currency": balance["currency"], "state": balance["state"], "account_model": balance["account_model"],
            "in_debt_since": balance["in_debt_since"].isoformat() if balance["in_debt_since"] else None,
            "over_tolerance_since": (balance["over_tolerance_since"].isoformat()
                                     if balance["over_tolerance_since"] else None),
            "suspended_at": balance["suspended_at"].isoformat() if balance["suspended_at"] else None,
            "by_kind": {k: str(v) for k, v in balance["by_kind"].items()},
            "lots": [{**lot, "original": str(lot["original"]), "remaining": str(lot["remaining"]),
                      "granted_at": lot["granted_at"].isoformat() if lot["granted_at"] else None,
                      "expires_at": lot["expires_at"].isoformat() if lot["expires_at"] else None}
                     for lot in balance["lots"]]}


# ── staff ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/admin/wallets")
async def list_wallets(state: Optional[str] = Query(None, pattern="^(ok|in_debt|over_tolerance|suspended)$"),
                       q: Optional[str] = Query(None, max_length=100), limit: int = Query(100, ge=1, le=500),
                       db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    now = datetime.utcnow()
    live = (select(WalletLot.company_id, func.sum(WalletLot.remaining).label("available"))
            .where(WalletLot.remaining > 0, (WalletLot.expires_at.is_(None)) | (WalletLot.expires_at > now))
            .group_by(WalletLot.company_id).subquery())
    query = (select(CreditWallet, Company.name, Company.type, func.coalesce(live.c.available, 0))
             .join(Company, Company.id == CreditWallet.company_id)
             .outerjoin(live, live.c.company_id == CreditWallet.company_id))
    if state:
        query = query.where(CreditWallet.state == state)
    if q:
        query = query.where(Company.name.ilike(f"%{q}%"))
    rows = (await db.execute(query.order_by(CreditWallet.debt.desc(), Company.name).limit(limit))).all()
    counts = dict((await db.execute(select(CreditWallet.state, func.count()).group_by(CreditWallet.state))).all())
    return {"counts": {s: counts.get(s, 0) for s in ("ok", "in_debt", "over_tolerance", "suspended")},
            "wallets": [{"company_id": str(w.company_id), "company_name": name, "company_type": kind,
                         "currency": w.currency, "state": w.state, "available": str(available),
                         "debt": str(w.debt), "in_debt_since": w.in_debt_since.isoformat() if w.in_debt_since else None}
                        for w, name, kind, available in rows]}


@router.get("/api/v1/admin/wallets/{company_id}")
async def get_wallet(company_id: UUID, limit: int = Query(100, ge=1, le=500), before: Optional[datetime] = None,
                     db: AsyncSession = Depends(get_control_db), user: User = Depends(staff)):
    from src.billing.credit_service import CreditService
    from src.billing.wallet import WalletService

    name = (await db.execute(select(Company.name).where(Company.id == company_id))).scalar_one_or_none()
    if name is None:
        raise HTTPException(status_code=404, detail="no such company")
    balance = await CreditService(db).snapshot(company_id)
    return {"company_id": str(company_id), "company_name": name, "wallet": _wallet_view(balance),
            "entries": await _entries(db, company_id, limit, before, staff_view=True),
            "problems": await WalletService(db).check(company_id)}


class AdjustBody(BaseModel):
    amount: Decimal = Field(..., description="In the wallet's currency: + grants credit, − deducts")
    reason: str = Field(..., min_length=3, max_length=500)
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)


@router.post("/api/v1/admin/wallets/{company_id}/adjust")
async def adjust_wallet(company_id: UUID, body: AdjustBody, db: AsyncSession = Depends(get_control_db),
                        user: User = Depends(staff)):
    """A staff correction (W-1): a ``grant`` lot (it does not repay debt) or a deduction (into debt if need be)."""
    from src.billing.enforcement import wallet_changed
    from src.billing.wallet import WalletService
    from src.common.admin_audit import record_admin_change

    if body.amount == 0:
        raise HTTPException(status_code=422, detail="an adjustment is not zero")
    if (await db.execute(select(Company.id).where(Company.id == company_id))).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="no such company")
    expires = datetime.utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    wallets = WalletService(db)
    change = await wallets.adjust(company_id, body.amount, actor_id=user.id, reason=body.reason, expires_at=expires)
    wallet = await wallets.get(company_id)
    record_admin_change(db, actor=user, action="adjust", object_type="wallet", object_key=str(company_id),
                        target_company_id=company_id, new_value={"amount": str(body.amount), "currency": wallet.currency,
                                                                 "debt_added": str(change.debt_added)},
                        reason=body.reason)
    await db.commit()
    await wallet_changed(db, company_id, change)
    return {"company_id": str(company_id), "amount": str(body.amount), "currency": wallet.currency,
            "state": change.state_after, "debt": str(wallet.debt)}


class CurrencyBody(BaseModel):
    currency: str = Field(..., min_length=3, max_length=3)
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/api/v1/admin/wallets/{company_id}/currency")
async def change_wallet_currency(company_id: UUID, body: CurrencyBody, db: AsyncSession = Depends(get_control_db),
                                 user: User = Depends(staff)):
    from src.billing.currency_change import CurrencyChangeRefused, change_currency

    try:
        result = await change_currency(db, company_id, body.currency, actor=user, reason=body.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="no such company") from None
    except CurrencyChangeRefused as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from None
    await db.commit()
    return result


# ── the company ────────────────────────────────────────────────────────────

@router.get("/api/v1/credits/ledger", summary="The wallet's entries, newest first")
async def my_ledger(limit: int = Query(50, ge=1, le=200), before: Optional[datetime] = None,
                    db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    """What came in and went out of the company's wallet, in its currency — billed
    amounts only (§5.2): an entry has no cost field."""
    return {"entries": await _entries(db, user.company_id, limit, before, staff_view=False)}
