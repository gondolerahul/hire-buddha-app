"""
Credit Service — admission, holds, top-ups and grants on the company's wallet.

Since Phase 15 M15.2 the wallet is lots and a ledger (``src.billing.wallet``,
tech design §6): this class keeps the interface the rest of the platform
calls — balance, admission, holds, the spend cap, top-ups and subscription
credits — and does each through :class:`WalletService`. Usage is charged by
``src.billing.settlement``, never here.

Amounts: the wallet, holds and every amount returned are in the company's
billing currency (Q3). Policy amounts — minimum balances, plan estimates, the
spend cap — are USD (K-16) and converted at the rate in effect now.

Admission (§6.3, §6.4): new work starts only when the wallet is ``ok`` (no
debt) and at least the level's minimum is free — the available credit minus
what running work holds.
"""
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update

from src.ai.orm.execution import ExecutionRun
from src.billing.billing_models import CreditHold, CreditWallet
from src.billing.wallet import OK, WalletService, money

# A hold on a run in one of these statuses no longer reserves anything.
TERMINAL_RUN_STATUSES = ("COMPLETED", "FAILED", "PARTIAL_COMPLETE", "CANCELLED")
ZERO = Decimal("0")


class InsufficientCreditsError(Exception):
    """Raised when the wallet cannot admit new work (too little free credit, or in debt)."""
    pass


class SpendCapReached(InsufficientCreditsError):
    """The company has been billed its ``monthly_spend_cap_usd`` this month
    (GH-18): nothing new starts, and a running run stops at the breaker."""


class WalletBlocked(InsufficientCreditsError):
    """The wallet is in debt, over its tolerance or suspended (§6.3): new work does not start."""


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def state_refusal(balance: dict) -> Optional[str]:
    """Why a wallet in this state admits nothing new, or ``None`` when it is ``ok`` (§6.3)."""
    state = balance["state"]
    if state == OK:
        return None
    owed = money(balance["debt"], balance["currency"])
    if state == "suspended":
        return (f"The account is suspended: {owed} has been owed for too long. Top up to repay it; "
                f"the account opens again as soon as it is repaid.")
    if state == "over_tolerance":
        return (f"The wallet owes {owed}, over its limit: nothing runs until it is repaid. "
                f"Top up to continue.")
    return f"The wallet owes {owed}: new work does not start until it is repaid. Top up to continue."


class CreditService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet = WalletService(db)

    # ── the wallet ───────────────────────────────────────────────────────

    async def get_or_create_wallet(self, company_id: UUID) -> CreditWallet:
        """The company's wallet, created (in its billing currency) if it has none; commits."""
        wallet = await self.wallet.get(company_id)
        await self.db.commit()
        return wallet

    async def lock_wallet(self, company_id: UUID) -> CreditWallet:
        """The company's wallet, row-locked until the transaction ends."""
        return await self.wallet.lock(company_id)

    async def renew_expired_credits(self, company_id: UUID) -> CreditWallet:
        """Expire the company's lots that are past their expiry (W-6); what the
        expiry job runs. Daily credits are granted by ``src.billing.daily_credits``."""
        await self.wallet.expire(company_id)
        await self.db.commit()
        return await self.wallet.get(company_id)

    async def rate(self, company_id: UUID):
        """The company's wallet currency and the rate in effect now."""
        from src.billing.currency import current_rate
        currency = (await self.wallet.get(company_id)).currency
        return await current_rate(self.db, currency)

    async def to_ccy(self, company_id: UUID, usd: Decimal) -> Decimal:
        from src.billing.currency import to_ccy
        return to_ccy(_dec(usd), await self.rate(company_id))

    async def snapshot(self, company_id: UUID, run_id: Optional[UUID] = None) -> dict:
        """The wallet with exact amounts (Decimals): ``free`` leaves out the
        holds of running work other than ``run_id``."""
        await self.wallet.expire(company_id)
        await self.db.commit()
        held = await self.held_by_others(company_id, run_id)
        return await self.wallet.balance(company_id, held=held)

    async def get_balance(self, company_id: UUID) -> dict:
        """The wallet as screens show it, in the company's currency.

        ``available`` is what the live lots hold, ``held`` what running work
        has reserved (BC-06), ``free`` what new work can start with, ``debt``
        what the company owes. The bucket keys of the old wallet
        (``daily_credits``, ``subscription_credits``, ``wallet_balance``, …)
        stay as sums of the lots of each kind.
        """
        b = await self.snapshot(company_id)
        kinds = b["by_kind"]
        earliest = {}
        for lot in b["lots"]:
            if lot["expires_at"] and (lot["kind"] not in earliest or lot["expires_at"] < earliest[lot["kind"]]):
                earliest[lot["kind"]] = lot["expires_at"]

        def iso(kind: str) -> Optional[str]:
            return earliest[kind].isoformat() if kind in earliest else None

        return {
            "currency": b["currency"], "state": b["state"], "account_model": b["account_model"],
            "available": str(b["available"]), "held": float(b["held"]), "free": float(b["free"]),
            "debt": str(b["debt"]), "tolerance": str(b["tolerance"]),
            "in_debt_since": b["in_debt_since"].isoformat() if b["in_debt_since"] else None,
            "suspended_at": b["suspended_at"].isoformat() if b["suspended_at"] else None,
            "daily_credits": float(kinds["daily"]), "daily_expires_at": iso("daily"),
            "subscription_credits": float(kinds["subscription"]),
            "subscription_bonus_credits": float(kinds["subscription_bonus"]),
            "sub_credits_expire_at": iso("subscription"),
            "wallet_balance": float(kinds["topup"] + kinds["grant"]),
            "wallet_expires_at": min(filter(None, (iso("topup"), iso("grant"))), default=None),
            "total_available": float(b["available"]),
            "lots": [{**lot, "original": str(lot["original"]), "remaining": str(lot["remaining"]),
                      "granted_at": lot["granted_at"].isoformat() if lot["granted_at"] else None,
                      "expires_at": lot["expires_at"].isoformat() if lot["expires_at"] else None}
                     for lot in b["lots"]],
        }

    # ── credit in ────────────────────────────────────────────────────────

    async def topup_validity_days(self, company_id: UUID) -> int:
        from src.billing.settings_catalogue import value
        return int(await value(self.db, "wallet.topup_validity_days", company_id))

    async def add_wallet_credits(self, company_id: UUID, amount: Decimal, *, source_type: str = "payment",
                                 source_id: Optional[str] = None, validity_days: Optional[int] = None,
                                 commit: bool = True):
        """A paid top-up of ``amount`` (the wallet's currency): repays debt first,
        the rest a ``topup`` lot valid ``wallet.topup_validity_days`` (W-4, W-7)."""
        from src.billing.enforcement import wallet_changed

        days = validity_days if validity_days is not None else await self.topup_validity_days(company_id)
        rate = await self.rate(company_id)
        change = await self.wallet.grant(company_id, "topup", _dec(amount),
                                         expires_at=datetime.utcnow() + timedelta(days=days), paid=True,
                                         source_type=source_type, source_id=source_id, reason="top-up",
                                         fx_rate_id=rate.id)
        if commit:
            await self.db.commit()
            await wallet_changed(self.db, company_id, change)
        return change

    async def inject_subscription_credits(
        self,
        company_id: UUID,
        base_amount: Decimal,
        bonus_pct: Decimal,
        expires_at: Optional[datetime] = None,
        *,
        source_id: Optional[str] = None,
    ):
        """A paid billing cycle's credits given in USD (``base_amount``): converted at
        today's rate, then :meth:`grant_cycle`. Commits."""
        from src.billing.currency import to_ccy

        rate = await self.rate(company_id)
        return await self.grant_cycle(company_id, to_ccy(_dec(base_amount), rate), bonus_pct, expires_at,
                                      source_id=source_id, fx_rate_id=rate.id)

    async def grant_cycle(
        self,
        company_id: UUID,
        amount: Decimal,
        bonus_pct: Decimal,
        expires_at: Optional[datetime] = None,
        *,
        source_id: Optional[str] = None,
        fx_rate_id: Optional[UUID] = None,
    ):
        """A subscription payment's credits in the wallet's currency (SB-3): ``amount`` as a
        paid subscription lot, ``amount × bonus_pct`` as a bonus lot, both ending with the
        cycle (``expires_at``).

        A payment for a **new** cycle replaces the live subscription lots — no
        carry-forward (W-5); one for the cycle already held (a mid-cycle upgrade's
        prorated charge) adds to it. The subscription credit is paid, so it repays
        debt first (W-7); the bonus does not. A cycle that has ended, or ends
        before the one the wallet holds (an older payment recorded late), grants
        nothing. Commits.
        """
        from src.billing.enforcement import wallet_changed

        await self.wallet.lock(company_id)
        now = datetime.utcnow()
        expires_at = expires_at or now + timedelta(days=31)
        live = [lot for lot in await self.wallet.live_lots(company_id, now=now, lock=True)
                if lot.kind in ("subscription", "subscription_bonus")]
        if expires_at <= now or any(lot.expires_at and expires_at < lot.expires_at - timedelta(minutes=5)
                                    for lot in live):
            await self.db.commit()
            return None
        same_cycle = any(lot.expires_at and abs(lot.expires_at - expires_at) <= timedelta(minutes=5) for lot in live)
        amount = _dec(amount)
        bonus = amount * (_dec(bonus_pct) / Decimal("100"))
        if not same_cycle:
            await self.wallet.expire_lots(company_id, live, reason="replaced by the next billing cycle", now=now)
        change = await self.wallet.grant(company_id, "subscription", amount, expires_at=expires_at, paid=True,
                                         source_type="subscription", source_id=source_id,
                                         reason="subscription credits" if not same_cycle
                                         else "subscription credits for the upgraded plan",
                                         fx_rate_id=fx_rate_id, now=now)
        if bonus > 0:
            await self.wallet.grant(company_id, "subscription_bonus", bonus, expires_at=expires_at, paid=False,
                                    source_type="subscription", source_id=source_id,
                                    reason="subscription bonus", fx_rate_id=fx_rate_id, now=now)
        wallet = await self.wallet.lock(company_id)
        wallet.account_model = "subscription"
        await self.db.commit()
        await wallet_changed(self.db, company_id, change)
        return change

    # ── Holds (BC-06, §6.4) ──────────────────────────────────────────────

    async def held_by_others(self, company_id: UUID, run_id: Optional[UUID] = None) -> Decimal:
        """Credit held by the company's unfinished work other than ``run_id``.

        A hold whose run has already finished no longer counts even before it
        is released, so a worker that died mid-run cannot pin the wallet; nor
        does one whose run is gone. Holds are control rows and runs tenant
        rows, so this is two reads, not a join (Phase 14 WS2).
        """
        stmt = select(CreditHold.run_id, CreditHold.amount).where(
            CreditHold.company_id == company_id,
            CreditHold.released_at.is_(None),
        )
        if run_id is not None:
            stmt = stmt.where(CreditHold.run_id != run_id)
        holds = (await self.db.execute(stmt)).all()
        if not holds:
            return ZERO
        unfinished = await self._unfinished_runs(company_id, [hold.run_id for hold in holds])
        return sum((_dec(hold.amount) for hold in holds if hold.run_id in unfinished), ZERO)

    async def _unfinished_runs(self, company_id: UUID, run_ids: list[UUID]) -> set[UUID]:
        """Which of ``run_ids`` are runs that have not finished: read in the
        company's tenant database (this session, if it is that one)."""
        from src.common.tenancy.session import is_split, tenant_session

        stmt = select(ExecutionRun.id).where(
            ExecutionRun.id.in_(run_ids),
            ExecutionRun.status.notin_(TERMINAL_RUN_STATUSES),
        )
        if not is_split() or str(self.db.info.get("company_id")) == str(company_id):
            return set((await self.db.execute(stmt)).scalars())
        async with tenant_session(company_id) as tenant:
            return set((await tenant.execute(stmt)).scalars())

    async def place_hold(
        self, company_id: UUID, run_id: UUID, estimate_usd: Decimal, floor_usd: Decimal,
    ) -> Decimal:
        """Admit a run: hold up to its estimated bill of what the wallet can spare (§6.4).

        ``estimate_usd`` and ``floor_usd`` (the level's minimum balance) are
        converted to the wallet's currency. A wallet that is not ``ok`` is
        refused (``WalletBlocked``); so is one with less than the floor free
        (InsufficientCreditsError). Otherwise the run holds
        ``max(estimate, floor)``, capped at what can be spared. Runs under the
        wallet lock, so two runs cannot be admitted on the same credit. Returns
        the amount held, in the wallet's currency.
        """
        from src.billing.currency import to_ccy

        wallet = await self.wallet.lock(company_id)
        rate = await self.rate(company_id)
        estimate, floor = to_ccy(_dec(estimate_usd), rate), to_ccy(_dec(floor_usd), rate)
        b = await self.wallet.balance(company_id)
        refusal = state_refusal(b)
        if refusal:
            await self.db.commit()
            raise WalletBlocked(f"Cannot start execution: {refusal}")
        spare = b["available"] - await self.held_by_others(company_id, run_id)
        if spare < floor:
            await self.db.commit()
            raise InsufficientCreditsError(
                f"Cannot start execution: {money(max(spare, ZERO), wallet.currency)} of credit is free "
                f"(balance {money(b['available'], wallet.currency)}, the rest held by running executions); "
                f"at least {money(floor, wallet.currency)} is required. Please top up your wallet or wait "
                f"for running executions to finish."
            )
        amount = min(max(estimate, floor), spare)
        await self.db.execute(
            pg_insert(CreditHold.__table__)
            .values(company_id=company_id, run_id=run_id, amount=amount, currency=wallet.currency)
            .on_conflict_do_update(index_elements=["run_id"],
                                   set_={"amount": amount, "currency": wallet.currency, "released_at": None})
        )
        await self.db.commit()
        return amount

    async def release_hold(self, run_id: UUID) -> None:
        await self.db.execute(
            update(CreditHold)
            .where(CreditHold.run_id == run_id, CreditHold.released_at.is_(None))
            .values(released_at=datetime.utcnow())
        )
        await self.db.commit()

    async def claim_settlement(self, company_id: UUID, run_id: UUID, billed_amount: Decimal,
                               billed_ccy: Optional[Decimal] = None) -> bool:
        """Record ``run_id`` as settled — ``billed_amount`` USD, ``billed_ccy`` in
        the wallet's currency — on its hold, which this releases, or on a row of
        its own when it has none, unless it already is (WS2 2.6). True when this
        call claimed the settlement.

        Not committed: the caller commits it with the deduction, so a run is
        charged at most once.
        """
        now = datetime.utcnow()
        holds = CreditHold.__table__
        claim = (
            pg_insert(holds)
            .values(company_id=company_id, run_id=run_id, amount=0, released_at=now,
                    settled_at=now, billed_amount=billed_amount, billed_ccy=billed_ccy)
            .on_conflict_do_update(
                index_elements=["run_id"],
                set_={"settled_at": now, "billed_amount": billed_amount, "billed_ccy": billed_ccy,
                      "released_at": func.coalesce(holds.c.released_at, now)},
                where=holds.c.settled_at.is_(None),
            )
            .returning(holds.c.run_id)
        )
        return (await self.db.execute(claim)).first() is not None

    # ── The company's monthly spend cap (GH-18, HD8) ────────────────────

    async def month_spend(self, company_id: UUID) -> Decimal:
        """What the company has been billed this calendar month (UTC), USD: its
        billing lines — every settlement (Phase 15 T3-4)."""
        from datetime import date
        from src.billing.billing_models import BillingLine
        today = datetime.utcnow().date()
        return _dec((await self.db.execute(
            select(func.coalesce(func.sum(BillingLine.billed_usd), 0))
            .where(BillingLine.company_id == company_id,
                   BillingLine.period_day >= date(today.year, today.month, 1))
        )).scalar())

    async def spend_cap_refusal(self, company_id: UUID, pending: Decimal = ZERO) -> Optional[str]:
        """Why the company may not spend more this month, or ``None``. No cap
        set means none. ``pending`` is a running run's bill so far (USD), which
        is not settled yet."""
        from src.auth.models import Company
        cap = (await self.db.execute(
            select(Company.monthly_spend_cap_usd).where(Company.id == company_id)
        )).scalar_one_or_none()
        if cap is None:
            return None
        cap = _dec(cap)
        spent = await self.month_spend(company_id) + _dec(pending)
        if spent < cap:
            return None
        return (f"The company's monthly spend cap of ${cap:.2f} is reached: ${spent:.2f} billed this month. "
                f"Raise the cap in the company's settings to spend more.")

    async def check_spend_cap(self, company_id: UUID, pending: Decimal = ZERO) -> None:
        """Raise ``SpendCapReached`` when the company is at its monthly cap."""
        refusal = await self.spend_cap_refusal(company_id, pending)
        if refusal:
            raise SpendCapReached(refusal)

    # ── Admission ────────────────────────────────────────────────────────

    async def admission_refusal(self, company_id: UUID, floor_usd: Decimal, what: str = "execution") -> Optional[str]:
        """Why new work may not start, or ``None``: the spend cap, the wallet's
        state, then less than ``floor_usd`` free (§6.3, §6.4)."""
        capped = await self.spend_cap_refusal(company_id)
        if capped:
            return capped
        b = await self.snapshot(company_id)
        refusal = state_refusal(b)
        if refusal:
            return refusal
        floor = await self.to_ccy(company_id, floor_usd)
        if b["free"] < floor:
            return (f"Cannot start {what}: {money(max(b['free'], ZERO), b['currency'])} of credit is free; "
                    f"at least {money(floor, b['currency'])} is required. Please top up your wallet or wait "
                    f"for daily credit refresh.")
        return None

    async def check_sufficient_for_execution(
        self,
        company_id: UUID,
        entity_type: str = "AGENT",
        *,
        floor_key: Optional[str] = None,
    ) -> dict:
        """Pre-execution gate: the wallet is ``ok`` and at least the level's
        minimum (``admission.min_balance.<LEVEL>``, or ``floor_key``) is free.
        Returns the balance on success; raises InsufficientCreditsError (or
        ``SpendCapReached`` / ``WalletBlocked``) otherwise."""
        from src.billing.settings_catalogue import min_balance, value

        await self.check_spend_cap(company_id)  # GH-18: before the wallet
        floor = (_dec(await value(self.db, floor_key, company_id)) if floor_key
                 else await min_balance(self.db, company_id, entity_type))
        b = await self.snapshot(company_id)
        refusal = state_refusal(b)
        if refusal:
            raise WalletBlocked(f"Cannot start: {refusal}")
        floor_ccy = await self.to_ccy(company_id, floor)
        if b["free"] < floor_ccy:
            raise InsufficientCreditsError(
                f"Cannot start execution: free credit {money(b['free'], b['currency'])} is below "
                f"the minimum {money(floor_ccy, b['currency'])} required for '{entity_type}'. "
                f"Please top up your wallet or wait for daily credit refresh."
            )
        return b

    async def headroom(self, company_id: UUID, run_id: Optional[UUID], billed_usd: Decimal) -> tuple[Decimal, dict]:
        """What running work may still spend (§6.3 breaker): free + tolerance −
        debt − ``billed_usd`` (its bill so far) in the wallet's currency. A
        wallet over its tolerance or suspended has none."""
        b = await self.snapshot(company_id, run_id)
        if b["state"] in ("over_tolerance", "suspended"):
            return ZERO - await self.to_ccy(company_id, billed_usd), b
        billed = await self.to_ccy(company_id, billed_usd)
        return b["free"] + b["tolerance"] - b["debt"] - billed, b

    async def require_credits(self, company_id: UUID, amount_usd: Decimal) -> None:
        """Raises HTTP 402 unless the wallet is ``ok`` and ``amount_usd`` of credit
        is free (not held by running work). Used before an execution is queued."""
        refusal = await self.admission_refusal(company_id, amount_usd)
        if refusal:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=refusal)
