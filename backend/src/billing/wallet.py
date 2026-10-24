"""The wallet: lots, debt, an append-only ledger and a state (Phase 15 T4-1, tech design §6, Q1, Q3).

All amounts here are in the company's billing currency (Q3); callers convert
USD with a locked rate (``src.billing.currency``). Rules (§6.2):

* W-3 spend order: daily → subscription → subscription bonus → top-up and
  grant lots by earliest ``expires_at`` → debt.
* W-7 paid credit (a top-up, a subscription payment) repays debt first;
  daily credits and staff grants do not.
* W-8 ``available`` = Σ remaining of live lots; the wallet is negative when
  ``debt > 0``.
* W-9 every change takes the wallet row lock and writes ``wallet_entries`` in
  the same transaction, each with the balance and debt after it; ``check``
  proves the wallet equals its ledger.

State (§6.3): ``ok`` → ``in_debt`` (debt > 0) → ``over_tolerance`` (debt ≥ the
tolerance, ``wallet.negative_tolerance_usd``) → ``suspended`` (over tolerance
for ``billing.suspend_after_days``, set by the job); back to ``ok`` when the
debt is repaid. A change of state is announced (``wallet_state_changed``) for
enforcement and notifications.

Every method here is called inside the caller's transaction and does not commit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.billing.billing_models import CreditWallet, WalletEntry, WalletLot

logger = logging.getLogger(__name__)

OK, IN_DEBT, OVER_TOLERANCE, SUSPENDED = "ok", "in_debt", "over_tolerance", "suspended"
STATES = (OK, IN_DEBT, OVER_TOLERANCE, SUSPENDED)
KINDS = ("daily", "subscription", "subscription_bonus", "topup", "grant")
_ORDER = {"daily": 0, "subscription": 1, "subscription_bonus": 2, "topup": 3, "grant": 3}
ZERO = Decimal(0)


def _d(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def money(amount: Any, currency: str) -> str:
    """An amount for a message: ``INR 1,234.50`` (two places; the stored amount is exact)."""
    return f"{currency} {_d(amount):,.2f}"


@dataclass
class Change:
    """What one wallet operation did."""
    amount: Decimal = ZERO          # deducted / granted / expired
    debt_added: Decimal = ZERO
    debt_repaid: Decimal = ZERO
    lot_id: Optional[UUID] = None
    state_before: str = OK
    state_after: str = OK
    entries: list = field(default_factory=list)


class WalletService:
    def __init__(self, db: Any):
        self.db = db
        self._last_entry_at: Optional[datetime] = None

    # ── the row ────────────────────────────────────────────────────────────

    async def ensure(self, company_id: UUID) -> None:
        """Create the company's wallet, in its billing currency, if it has none."""
        from src.auth.models import Company

        currency = (await self.db.execute(select(Company.billing_currency).where(Company.id == company_id))
                    ).scalar_one_or_none() or "INR"
        await self.db.execute(pg_insert(CreditWallet.__table__)
                              .values(company_id=company_id, currency=currency)
                              .on_conflict_do_nothing(index_elements=["company_id"]))

    async def lock(self, company_id: UUID) -> CreditWallet:
        """The wallet, row-locked until the transaction ends (created if missing)."""
        await self.ensure(company_id)
        return (await self.db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                                      .with_for_update().execution_options(populate_existing=True))).scalar_one()

    async def get(self, company_id: UUID) -> CreditWallet:
        await self.ensure(company_id)
        return (await self.db.execute(select(CreditWallet).where(CreditWallet.company_id == company_id)
                                      .execution_options(populate_existing=True))).scalar_one()

    # ── lots ───────────────────────────────────────────────────────────────

    async def live_lots(self, company_id: UUID, *, now: Optional[datetime] = None, lock: bool = False) -> list:
        """Lots with credit left and not expired, in spend order (W-3)."""
        now = now or datetime.utcnow()
        order = case(*[(WalletLot.kind == k, v) for k, v in _ORDER.items()], else_=9)
        query = (select(WalletLot).where(WalletLot.company_id == company_id, WalletLot.remaining > 0,
                                         (WalletLot.expires_at.is_(None)) | (WalletLot.expires_at > now))
                 .order_by(order, WalletLot.expires_at.asc().nulls_last(), WalletLot.granted_at))
        if lock:
            query = query.with_for_update()
        return list((await self.db.execute(query.execution_options(populate_existing=True))).scalars().all())

    async def _available(self, company_id: UUID, now: datetime) -> Decimal:
        return _d((await self.db.execute(select(func.coalesce(func.sum(WalletLot.remaining), 0)).where(
            WalletLot.company_id == company_id, WalletLot.remaining > 0,
            (WalletLot.expires_at.is_(None)) | (WalletLot.expires_at > now)))).scalar())

    def _entry(self, wallet: CreditWallet, kind: str, amount: Decimal, available: Decimal, **fields: Any) -> WalletEntry:
        # Entries of one operation keep their order on the ledger: each is a microsecond after the last.
        at = datetime.utcnow()
        if self._last_entry_at is not None and at <= self._last_entry_at:
            at = self._last_entry_at + timedelta(microseconds=1)
        self._last_entry_at = at
        entry = WalletEntry(company_id=wallet.company_id, kind=kind, amount=amount, currency=wallet.currency,
                            balance_after=available, debt_after=_d(wallet.debt), created_at=at, **fields)
        self.db.add(entry)
        return entry

    # ── operations ─────────────────────────────────────────────────────────

    async def expire(self, company_id: UUID, *, now: Optional[datetime] = None) -> Change:
        """Lots past their expiry lose what they hold (W-6)."""
        now = now or datetime.utcnow()
        wallet = await self.lock(company_id)
        lots = (await self.db.execute(select(WalletLot).where(
            WalletLot.company_id == company_id, WalletLot.remaining > 0, WalletLot.expires_at <= now)
            .with_for_update())).scalars().all()
        change = Change(state_before=wallet.state, state_after=wallet.state)
        available = await self._available(company_id, now)
        for lot in lots:
            gone = _d(lot.remaining)
            lot.remaining = ZERO
            change.amount += gone
            change.entries.append(self._entry(wallet, "expire", -gone, available, lot_id=lot.id,
                                              reason=f"{lot.kind} credit expired", source_type=lot.source_type,
                                              source_id=lot.source_id))
        wallet.cached_available = available
        return change

    async def expire_lots(self, company_id: UUID, lots: list, *, reason: str,
                          now: Optional[datetime] = None) -> Change:
        """End ``lots`` now, whatever their expiry (a subscription cycle replaced,
        a daily lot renewed): each loses what it holds, with an ``expire`` entry."""
        now = now or datetime.utcnow()
        wallet = await self.lock(company_id)
        change = Change(state_before=wallet.state, state_after=wallet.state)
        available = await self._available(company_id, now)
        for lot in lots:
            gone = _d(lot.remaining)
            lot.remaining = ZERO
            lot.expires_at = min(lot.expires_at, now) if lot.expires_at else now
            if gone <= 0:
                continue
            available -= gone
            change.amount += gone
            change.entries.append(self._entry(wallet, "expire", -gone, available, lot_id=lot.id, reason=reason,
                                              source_type=lot.source_type, source_id=lot.source_id))
        wallet.cached_available = available
        await self.db.flush()
        return change

    async def grant(self, company_id: UUID, kind: str, amount: Decimal, *, expires_at: Optional[datetime],
                    paid: bool, source_type: str, source_id: Optional[str] = None, repay_debt: Optional[bool] = None,
                    reason: Optional[str] = None, actor_id: Optional[UUID] = None, fx_rate_id: Optional[UUID] = None,
                    policy_id: Optional[UUID] = None, local_date: Any = None,
                    now: Optional[datetime] = None) -> Change:
        """Add credit. Paid credit repays debt first (W-7); the rest becomes a lot."""
        if kind not in KINDS:
            raise ValueError(f"unknown lot kind {kind!r}")
        amount = _d(amount)
        if amount < 0:
            raise ValueError("a grant is not negative")
        now = now or datetime.utcnow()
        repay = paid if repay_debt is None else repay_debt
        wallet = await self.lock(company_id)
        change = Change(state_before=wallet.state)
        available = await self._available(company_id, now)
        to_lot = amount
        if repay and _d(wallet.debt) > 0 and amount > 0:
            repaid = min(_d(wallet.debt), amount)
            wallet.debt = _d(wallet.debt) - repaid
            to_lot -= repaid
            change.debt_repaid = repaid
            change.entries.append(self._entry(wallet, "debt_repay", repaid, available, reason=reason or "debt repaid",
                                              source_type=source_type, source_id=source_id, actor_id=actor_id,
                                              fx_rate_id=fx_rate_id))
        lot = WalletLot(company_id=company_id, kind=kind, currency=wallet.currency, original=to_lot, remaining=to_lot,
                        granted_at=now, expires_at=expires_at, paid=paid, source_type=source_type, source_id=source_id,
                        fx_rate_id=fx_rate_id, policy_id=policy_id, local_date=local_date)
        self.db.add(lot)
        await self.db.flush()
        available += to_lot
        change.amount, change.lot_id = to_lot, lot.id
        change.entries.append(self._entry(wallet, "grant", to_lot, available, lot_id=lot.id,
                                          reason=reason or f"{kind} credit", source_type=source_type,
                                          source_id=source_id, actor_id=actor_id, fx_rate_id=fx_rate_id))
        wallet.cached_available = available
        await self._settle_state(wallet, now, change)
        return change

    async def deduct(self, company_id: UUID, amount: Decimal, *, source_type: str, source_id: Optional[str] = None,
                     reason: Optional[str] = None, category: Optional[str] = None, run_id: Optional[UUID] = None,
                     user_id: Optional[UUID] = None, actor_id: Optional[UUID] = None, fx_rate_id: Optional[UUID] = None,
                     allow_debt: bool = True, now: Optional[datetime] = None) -> Change:
        """Spend ``amount`` from the lots in order; what they cannot cover becomes debt (§6.5).

        ``allow_debt=False`` takes only what the lots hold and reports the rest
        as not taken (``amount`` is what was deducted).
        """
        amount = _d(amount)
        if amount < 0:
            raise ValueError("a deduction is not negative")
        now = now or datetime.utcnow()
        wallet = await self.lock(company_id)
        change = Change(state_before=wallet.state)
        available = await self._available(company_id, now)
        left = amount
        for lot in await self.live_lots(company_id, now=now, lock=True):
            if left <= 0:
                break
            take = min(_d(lot.remaining), left)
            lot.remaining = _d(lot.remaining) - take
            left -= take
            available -= take
            change.amount += take
            change.entries.append(self._entry(wallet, "deduct", -take, available, lot_id=lot.id, reason=reason,
                                              category=category, source_type=source_type, source_id=source_id,
                                              run_id=run_id, user_id=user_id, actor_id=actor_id,
                                              fx_rate_id=fx_rate_id))
        if left > 0 and allow_debt:
            wallet.debt = _d(wallet.debt) + left
            change.debt_added = left
            change.amount += left
            change.entries.append(self._entry(wallet, "debt_add", -left, available, reason=reason, category=category,
                                              source_type=source_type, source_id=source_id, run_id=run_id,
                                              user_id=user_id, actor_id=actor_id, fx_rate_id=fx_rate_id))
        wallet.cached_available = available
        await self._settle_state(wallet, now, change)
        return change

    async def adjust(self, company_id: UUID, amount: Decimal, *, actor_id: UUID, reason: str,
                     expires_at: Optional[datetime] = None) -> Change:
        """A staff correction (W-1): + grants a ``grant`` lot (not paid; it does not repay debt),
        − deducts like usage, into debt if need be. Always with a reason."""
        if not reason or not reason.strip():
            raise ValueError("an adjustment needs a reason")
        amount = _d(amount)
        if amount >= 0:
            return await self.grant(company_id, "grant", amount, expires_at=expires_at, paid=False, source_type="staff",
                                    reason=reason, actor_id=actor_id)
        return await self.deduct(company_id, -amount, source_type="staff", reason=reason, actor_id=actor_id)

    # ── state ──────────────────────────────────────────────────────────────

    async def tolerance(self, company_id: UUID, currency: str) -> Decimal:
        """``wallet.negative_tolerance_usd`` for the company, in its currency (§6.3)."""
        from src.billing.currency import current_rate, to_ccy
        from src.billing.settings_catalogue import value

        usd = await value(self.db, "wallet.negative_tolerance_usd", company_id)
        return to_ccy(usd, await current_rate(self.db, currency))

    async def _settle_state(self, wallet: CreditWallet, now: datetime, change: Change) -> None:
        debt = _d(wallet.debt)
        old = wallet.state
        if debt <= 0:
            new = OK
        elif old == SUSPENDED:
            new = SUSPENDED                      # stays until the debt is repaid
        elif debt >= await self.tolerance(wallet.company_id, wallet.currency):
            new = OVER_TOLERANCE
        else:
            new = IN_DEBT
        if new != old:
            wallet.state = new
            if new == OK:
                wallet.in_debt_since = wallet.over_tolerance_since = wallet.suspended_at = None
            if new in (IN_DEBT, OVER_TOLERANCE) and wallet.in_debt_since is None:
                wallet.in_debt_since = now
            if new == OVER_TOLERANCE and wallet.over_tolerance_since is None:
                wallet.over_tolerance_since = now
            if new == IN_DEBT:
                wallet.over_tolerance_since = None
        wallet.updated_at = now
        change.state_before, change.state_after = old, new

    async def suspend(self, company_id: UUID, *, now: Optional[datetime] = None) -> Change:
        """Over the tolerance too long (§6.3, T4-8): read-only until the debt is repaid."""
        now = now or datetime.utcnow()
        wallet = await self.lock(company_id)
        change = Change(state_before=wallet.state, state_after=wallet.state)
        if wallet.state == OVER_TOLERANCE:
            wallet.state, wallet.suspended_at = SUSPENDED, now
            change.state_after = SUSPENDED
        return change

    # ── reading ────────────────────────────────────────────────────────────

    async def check(self, company_id: UUID) -> list[str]:
        """Problems where the wallet does not equal its ledger (W-9) — the nightly check."""
        wallet = await self.get(company_id)
        problems = []
        lots = (await self.db.execute(select(WalletLot).where(WalletLot.company_id == company_id))).scalars().all()
        for lot in lots:
            booked = _d((await self.db.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
                WalletEntry.lot_id == lot.id, WalletEntry.kind.in_(("grant", "deduct", "expire", "convert"))))).scalar())
            if booked != _d(lot.remaining):
                problems.append(f"lot {lot.id}: remaining {lot.remaining}, entries say {booked}")
        added = _d((await self.db.execute(select(func.coalesce(func.sum(-WalletEntry.amount), 0)).where(
            WalletEntry.company_id == company_id, WalletEntry.kind == "debt_add"))).scalar())
        repaid = _d((await self.db.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
            WalletEntry.company_id == company_id, WalletEntry.kind.in_(("debt_repay", "convert")),
            WalletEntry.lot_id.is_(None)))).scalar())
        if added - repaid != _d(wallet.debt):
            problems.append(f"debt {wallet.debt}, entries say {added - repaid}")
        return problems

    async def balance(self, company_id: UUID, *, held: Decimal = ZERO) -> dict:
        """The wallet as screens show it: available, held, free, debt, state, lots."""
        now = datetime.utcnow()
        wallet = await self.get(company_id)
        lots = await self.live_lots(company_id, now=now)
        available = sum((_d(lot.remaining) for lot in lots), ZERO)
        by_kind = {kind: sum((_d(lot.remaining) for lot in lots if lot.kind == kind), ZERO) for kind in KINDS}
        tolerance = await self.tolerance(company_id, wallet.currency)
        return {
            "currency": wallet.currency, "state": wallet.state,
            "available": available, "held": held, "free": available - held, "debt": _d(wallet.debt),
            "tolerance": tolerance, "by_kind": by_kind,
            "in_debt_since": wallet.in_debt_since, "over_tolerance_since": wallet.over_tolerance_since,
            "suspended_at": wallet.suspended_at, "account_model": wallet.account_model,
            "lots": [{"id": str(lot.id), "kind": lot.kind, "original": _d(lot.original),
                      "remaining": _d(lot.remaining), "granted_at": lot.granted_at, "expires_at": lot.expires_at,
                      "paid": lot.paid} for lot in lots],
        }


async def summaries(db: Any, company_ids: list) -> dict:
    """``{company_id: {currency, state, available, debt, available_usd}}`` for many wallets in
    two queries (reports, health scores): ``available`` is what live lots hold, in the
    wallet's currency; ``available_usd`` the same at today's rate."""
    from src.billing.currency import UnknownCurrency, current_rate, to_usd

    ids = list(company_ids)
    if not ids:
        return {}
    now = datetime.utcnow()
    live = dict((await db.execute(
        select(WalletLot.company_id, func.coalesce(func.sum(WalletLot.remaining), 0))
        .where(WalletLot.company_id.in_(ids), WalletLot.remaining > 0,
               (WalletLot.expires_at.is_(None)) | (WalletLot.expires_at > now))
        .group_by(WalletLot.company_id))).all())
    rates: dict = {}
    out = {}
    for w in (await db.execute(select(CreditWallet.company_id, CreditWallet.currency, CreditWallet.state,
                                      CreditWallet.debt).where(CreditWallet.company_id.in_(ids)))).all():
        if w.currency not in rates:
            try:
                rates[w.currency] = await current_rate(db, w.currency)
            except UnknownCurrency:
                rates[w.currency] = None
        available = _d(live.get(w.company_id))
        rate = rates[w.currency]
        out[w.company_id] = {"currency": w.currency, "state": w.state, "available": available, "debt": _d(w.debt),
                             "available_usd": to_usd(available, rate) if rate else ZERO}
    return out
