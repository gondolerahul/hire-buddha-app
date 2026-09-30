"""
Credit Service — manages credit wallet consumption with priority ordering.

A wallet has four buckets. Consumption draws on every bucket that holds
credit, soonest-expiring first:

  1. Daily credits          — expire at the next 00:00 UTC
  2. Subscription credits   — expire at the end of the paid billing cycle
  3. Subscription bonus     — same expiry as 2
  4. Wallet balance         — top-ups, valid for 365 days

``account_model`` (pay_as_you_go | subscription) labels the account for the
UI; it does not decide which buckets can be spent. Before BC-02 it did, so a
company that subscribed could no longer spend the top-ups it had paid for.

Every change to a wallet's buckets is made under a row lock
(:meth:`CreditService.lock_wallet`), so concurrent runs, top-ups and settlements
cannot overwrite one another's changes.

Raises InsufficientCreditsError if all buckets are zero.
"""
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.billing.billing_models import CreditWallet
from src.billing.billing_service import BillingService


# Minimum credit thresholds by entity type.
# Execution is blocked if the available balance is below this amount.
MINIMUM_EXECUTION_THRESHOLDS = {
    "PROCESS": Decimal("0.50"),   # Deep Research etc. — typically costs $0.50–$2.00
    "AGENT":   Decimal("0.05"),   # Single-agent runs
    "SKILL":   Decimal("0.02"),   # Lightweight skill invocations
    "ACTION":  Decimal("0.01"),   # Atomic actions
}
DEFAULT_MINIMUM_THRESHOLD = Decimal("0.05")

# (deduction key, wallet column), in the order buckets are spent.
SPEND_ORDER = (
    ("daily", "daily_credits"),
    ("subscription", "subscription_credits"),
    ("subscription", "subscription_bonus_credits"),
    ("wallet", "wallet_balance"),
)


class InsufficientCreditsError(Exception):
    """Raised when all credit buckets are exhausted and task execution should be blocked."""
    pass


def _next_midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def available_credit(wallet: CreditWallet) -> Decimal:
    """Sum of the four buckets as stored (call after :meth:`CreditService._expire`)."""
    return sum((_dec(getattr(wallet, column)) for _, column in SPEND_ORDER), Decimal("0"))


def deduct(wallet: CreditWallet, amount: Decimal) -> tuple[dict, Decimal]:
    """Take up to ``amount`` from the buckets in :data:`SPEND_ORDER`.

    Mutates ``wallet`` in place; returns ``(deductions, shortfall)``.
    """
    deductions = {"daily": Decimal("0"), "wallet": Decimal("0"), "subscription": Decimal("0")}
    remaining = amount
    for key, column in SPEND_ORDER:
        if remaining <= 0:
            break
        held = _dec(getattr(wallet, column))
        if held <= 0:
            continue
        take = min(remaining, held)
        setattr(wallet, column, held - take)
        deductions[key] += take
        remaining -= take
    wallet.updated_at = datetime.utcnow()
    return deductions, remaining


class CreditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _daily_amount(self, company_id: UUID) -> Decimal:
        config = await BillingService(self.db).get_billing_config(company_id)
        if config and config.default_daily_credits:
            return _dec(config.default_daily_credits)
        return Decimal("0")

    async def get_or_create_wallet(self, company_id: UUID) -> CreditWallet:
        """Return the company's credit wallet, creating it with a day's credits.

        Creation is an ``INSERT … ON CONFLICT DO NOTHING``, so two requests for a
        new company cannot both insert. A wallet whose daily credits were never
        initialised (``daily_expires_at`` is None) gets its first injection.
        """
        stmt = select(CreditWallet).where(CreditWallet.company_id == company_id)
        wallet = (await self.db.execute(stmt)).scalar_one_or_none()

        if not wallet:
            now = datetime.utcnow()
            await self.db.execute(
                pg_insert(CreditWallet.__table__)
                .values(
                    company_id=company_id,
                    daily_credits=await self._daily_amount(company_id),
                    daily_expires_at=_next_midnight(now),
                )
                .on_conflict_do_nothing(index_elements=["company_id"])
            )
            await self.db.commit()
            wallet = (await self.db.execute(stmt)).scalar_one()
        elif wallet.daily_expires_at is None:
            wallet = await self.flush_and_inject_daily_credits(company_id)

        return wallet

    async def lock_wallet(self, company_id: UUID) -> CreditWallet:
        """The company's wallet, row-locked until the transaction ends.

        Re-read under the lock, so a balance changed by a concurrent
        transaction is not overwritten. The wallet must exist.
        """
        stmt = (
            select(CreditWallet)
            .where(CreditWallet.company_id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one()

    async def _expire(self, wallet: CreditWallet, now: datetime) -> None:
        """Renew expired daily credits and empty the other expired buckets."""
        if wallet.daily_expires_at is None or wallet.daily_expires_at < now:
            wallet.daily_credits = await self._daily_amount(wallet.company_id)
            wallet.daily_expires_at = _next_midnight(now)
        if wallet.wallet_expires_at and wallet.wallet_expires_at < now:
            wallet.wallet_balance = Decimal("0")
        if wallet.sub_credits_expire_at and wallet.sub_credits_expire_at < now:
            wallet.subscription_credits = Decimal("0")
            wallet.subscription_bonus_credits = Decimal("0")

    async def _locked_current_wallet(self, company_id: UUID) -> CreditWallet:
        """The wallet, row-locked, with expired buckets settled."""
        await self.get_or_create_wallet(company_id)
        wallet = await self.lock_wallet(company_id)
        await self._expire(wallet, datetime.utcnow())
        return wallet

    async def get_balance(self, company_id: UUID) -> dict:
        """Return current credit balance across all buckets.

        Expired daily credits are renewed in place (no cron needed); other
        expired buckets read as zero.
        """
        wallet = await self._locked_current_wallet(company_id)
        await self.db.commit()

        daily = _dec(wallet.daily_credits)
        wallet_bal = _dec(wallet.wallet_balance)
        sub_credits = _dec(wallet.subscription_credits)
        sub_bonus = _dec(wallet.subscription_bonus_credits)
        return {
            "account_model": wallet.account_model,
            "daily_credits": float(daily),
            "daily_expires_at": wallet.daily_expires_at.isoformat() if wallet.daily_expires_at else None,
            "wallet_balance": float(wallet_bal),
            "wallet_expires_at": wallet.wallet_expires_at.isoformat() if wallet.wallet_expires_at else None,
            "subscription_credits": float(sub_credits),
            "subscription_bonus_credits": float(sub_bonus),
            "sub_credits_expire_at": wallet.sub_credits_expire_at.isoformat() if wallet.sub_credits_expire_at else None,
            "total_available": float(daily + wallet_bal + sub_credits + sub_bonus),
        }

    async def consume(self, company_id: UUID, amount: Decimal) -> dict:
        """
        Deduct `amount` from credit buckets in priority order.
        Returns dict showing how much was deducted from each bucket.

        Raises InsufficientCreditsError if total available < amount; nothing
        is deducted then.
        """
        wallet = await self._locked_current_wallet(company_id)
        total_available = available_credit(wallet)
        if total_available < amount:
            await self.db.commit()  # keep the renewal, release the lock
            raise InsufficientCreditsError(
                f"Insufficient credits. Required: ${amount}, Available: ${total_available}"
            )
        deductions, _ = deduct(wallet, amount)
        await self.db.commit()
        return deductions

    @staticmethod
    def add_to_wallet_balance(
        wallet: CreditWallet, amount: Decimal, validity_days: int = 365,
    ) -> None:
        """Add a top-up to the balance bucket and restart its validity.

        An expired balance is gone; the top-up does not revive it.
        """
        now = datetime.utcnow()
        current = _dec(wallet.wallet_balance)
        if wallet.wallet_expires_at and wallet.wallet_expires_at < now:
            current = Decimal("0")
        wallet.wallet_balance = current + amount
        wallet.wallet_expires_at = now + timedelta(days=validity_days)
        wallet.updated_at = now

    async def add_wallet_credits(
        self,
        company_id: UUID,
        amount: Decimal,
        validity_days: int = 365,
    ) -> CreditWallet:
        """Credit the wallet balance bucket (PAYG top-up)."""
        await self.get_or_create_wallet(company_id)
        wallet = await self.lock_wallet(company_id)
        self.add_to_wallet_balance(wallet, amount, validity_days)
        await self.db.commit()
        await self.db.refresh(wallet)
        return wallet

    async def inject_subscription_credits(
        self,
        company_id: UUID,
        base_amount: Decimal,
        bonus_pct: Decimal,
        expires_at: Optional[datetime] = None,
    ) -> CreditWallet:
        """Replace subscription credits for a paid billing cycle (no carry-forward).

        ``expires_at`` is the end of the cycle that was paid for; without one
        the credits last a month from now. A cycle that has already ended, or
        ends before the credits the wallet holds (an older payment recorded
        late), grants nothing: it must not replace a newer cycle's credits.
        """
        await self.get_or_create_wallet(company_id)
        wallet = await self.lock_wallet(company_id)
        now = datetime.utcnow()
        expires_at = expires_at or now + timedelta(days=31)
        if expires_at <= now or (
            wallet.sub_credits_expire_at and expires_at < wallet.sub_credits_expire_at
        ):
            await self.db.commit()
            return wallet
        bonus = base_amount * (bonus_pct / Decimal("100"))

        # Flush old credits — strict no carry-forward
        wallet.subscription_credits = base_amount
        wallet.subscription_bonus_credits = bonus
        wallet.account_model = "subscription"
        wallet.sub_credits_expire_at = expires_at
        wallet.updated_at = now

        await self.db.commit()
        await self.db.refresh(wallet)
        return wallet

    async def flush_and_inject_daily_credits(self, company_id: UUID) -> CreditWallet:
        """
        Flush the day's credits and inject a fresh amount from config,
        whether or not they have expired.

        Queries the wallet directly (not get_or_create_wallet) to avoid
        recursion when daily_expires_at is None.
        """
        stmt = select(CreditWallet).where(CreditWallet.company_id == company_id)
        if (await self.db.execute(stmt)).scalar_one_or_none() is None:
            return await self.get_or_create_wallet(company_id)

        wallet = await self.lock_wallet(company_id)
        now = datetime.utcnow()
        wallet.daily_credits = await self._daily_amount(company_id)
        wallet.daily_expires_at = _next_midnight(now)
        wallet.updated_at = now
        await self.db.commit()
        await self.db.refresh(wallet)
        return wallet

    # ── New methods for credit overspend prevention ─────────────────────

    async def check_sufficient_for_execution(
        self,
        company_id: UUID,
        entity_type: str = "AGENT",
    ) -> dict:
        """
        Pre-execution gate: ensure the company has at least the minimum
        threshold for the given entity type.  Returns the balance dict on
        success; raises InsufficientCreditsError if below threshold.
        """
        balance = await self.get_balance(company_id)
        threshold = MINIMUM_EXECUTION_THRESHOLDS.get(
            entity_type.upper(), DEFAULT_MINIMUM_THRESHOLD
        )
        available = Decimal(str(balance["total_available"]))
        if available < threshold:
            raise InsufficientCreditsError(
                f"Cannot start execution: credit balance ${available:.4f} is below "
                f"the minimum ${threshold:.4f} required for entity type '{entity_type}'. "
                f"Please top up your wallet or wait for daily credit refresh."
            )
        return balance

    async def get_effective_balance(
        self,
        company_id: UUID,
        accumulated_cost: Decimal,
    ) -> Decimal:
        """
        Real-time effective balance = total_available − cost already
        incurred in the current run (but not yet formally deducted).
        Used by the periodic circuit-breaker during execution.
        """
        balance = await self.get_balance(company_id)
        total = Decimal(str(balance["total_available"]))
        return total - accumulated_cost

    async def consume_incremental(
        self,
        company_id: UUID,
        amount: Decimal,
    ) -> dict:
        """
        Deduct `amount` from credit buckets, consuming whatever is available.
        Unlike `consume()`, this does NOT raise when the amount exceeds the
        balance — it deducts as much as possible, so the wallet goes to $0
        rather than allowing the balance to stay untouched while costs pile up.

        Returns dict with deduction breakdown and a boolean `exhausted` flag.
        """
        wallet = await self._locked_current_wallet(company_id)
        deductions, shortfall = deduct(wallet, amount)
        await self.db.commit()
        return {
            **deductions,
            "shortfall": shortfall,
            "exhausted": shortfall > 0,
        }

    async def require_credits(self, company_id: UUID, amount: Decimal) -> None:
        """
        Middleware helper — raises HTTP 402 if insufficient credits.
        Use before processing billable tasks.
        """
        balance = await self.get_balance(company_id)
        if balance["total_available"] < float(amount):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Insufficient credits. Required: ${amount:.4f}, "
                    f"Available: ${balance['total_available']:.4f}. "
                    "Please top up your wallet or check your subscription."
                )
            )
