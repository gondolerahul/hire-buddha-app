"""Funding a test company's wallet (Phase 15 M15.2: the wallet is lots and a ledger).

``await fund(db, company_id, "100")`` grants a top-up lot worth USD 100 in the
company's billing currency (₹10,000 for an INR company at the seeded rate), as
a real top-up would — through ``WalletService.grant``, so the ledger agrees —
expiring in a day. The caller commits (or its transaction rolls back).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional


async def fund(db: Any, company_id: Any, usd: Any, *, kind: str = "topup", paid: Optional[bool] = None,
               expires_in: Optional[timedelta] = timedelta(days=1), currency: Optional[str] = None) -> Any:
    """Grant ``usd`` (converted to the wallet's currency) as a lot; returns the wallet change."""
    from src.billing.currency import current_rate, to_ccy
    from src.billing.wallet import WalletService

    wallets = WalletService(db)
    wallet = await wallets.lock(company_id)
    if currency and wallet.currency != currency:
        wallet.currency = currency
        await db.flush()
    amount = to_ccy(Decimal(str(usd)), await current_rate(db, wallet.currency))
    expires_at = datetime.utcnow() + expires_in if expires_in is not None else None
    return await wallets.grant(company_id, kind, amount, expires_at=expires_at,
                               paid=kind in ("topup", "subscription") if paid is None else paid,
                               source_type="test", reason="test funding")


async def available(db: Any, company_id: Any) -> Decimal:
    """What the wallet's live lots hold now, in its currency."""
    from src.billing.wallet import WalletService

    return (await WalletService(db).balance(company_id))["available"]


async def undo_entries(db: Any, company_id: Any, *, run_id: Any = None, source_type: Optional[str] = None) -> None:
    """Take back what a committed test did to a shared wallet: each matching
    entry's effect on its lot and on the debt is reversed and the entry
    deleted (the caller commits). Only for tests on shared dev databases."""
    from sqlalchemy import delete, select

    from src.billing.billing_models import CreditWallet, WalletEntry, WalletLot

    query = select(WalletEntry).where(WalletEntry.company_id == company_id)
    if run_id is not None:
        query = query.where(WalletEntry.run_id == run_id)
    if source_type is not None:
        query = query.where(WalletEntry.source_type == source_type)
    entries = (await db.execute(query)).scalars().all()
    wallet = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                               .with_for_update())).scalar_one()
    granted = set()
    for entry in entries:
        amount = Decimal(str(entry.amount))
        if entry.kind == "debt_add":
            wallet.debt = Decimal(str(wallet.debt)) + amount          # amount is negative
        elif entry.kind == "debt_repay":
            wallet.debt = Decimal(str(wallet.debt)) + amount
        elif entry.lot_id is not None:
            lot = await db.get(WalletLot, entry.lot_id)
            if lot is not None:
                lot.remaining = Decimal(str(lot.remaining)) - amount
                if entry.kind == "grant":
                    granted.add(lot.id)
    await db.execute(delete(WalletEntry).where(WalletEntry.id.in_([e.id for e in entries])))
    for lot_id in granted:                      # a lot whose grant is taken back goes too
        await db.execute(delete(WalletEntry).where(WalletEntry.lot_id == lot_id))
        await db.execute(delete(WalletLot).where(WalletLot.id == lot_id))
    if Decimal(str(wallet.debt)) <= 0:
        wallet.debt, wallet.state = Decimal(0), "ok"
        wallet.in_debt_since = wallet.over_tolerance_since = wallet.suspended_at = None
    await db.flush()
    wallet.cached_available = await available(db, company_id)
