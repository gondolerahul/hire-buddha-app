"""What the wallet tells a business (Phase 15 T4-9, tech design §14).

In-app notifications (and e-mail) to the company's admins through
``src.notifications.service.notify``: a change of wallet state, a low balance,
credit about to expire, apps stopped for balance. Each has a dedupe key, so a
job that runs every quarter hour tells each person once.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select

WALLET_LINK = "/wallet"

STATE_TEXT = {
    "ok": ("Your wallet is back in credit", "Everything that was held for balance runs again.", "info"),
    "in_debt": ("Your wallet is in debt",
                "New runs, calls and automation wait until it is repaid. Top up to continue.", "warning"),
    "over_tolerance": ("Your wallet is over its limit",
                       "Running work has been stopped and live calls end. Top up to continue.", "error"),
    "suspended": ("Your account is suspended for an unpaid balance",
                  "Sign-in is read-only and apps and the Data API are off until the balance is repaid. "
                  "Top up to open the account again.", "error"),
}


async def wallet_state_notice(db: Any, company_id: UUID, before: str, after: str) -> int:
    from src.notifications.service import notify

    title, body, severity = STATE_TEXT.get(after, (f"Wallet {after}", None, "warning"))
    return await notify(company_id, kind=f"wallet.{after}", title=title, body=body, link=WALLET_LINK,
                        severity=severity, dedupe_key=f"wallet:{after}:{datetime.utcnow():%Y-%m-%dT%H}")


async def apps_stopped_notice(company_id: UUID, count: int) -> int:
    from src.notifications.service import notify

    return await notify(company_id, kind="wallet.apps_stopped", severity="error", link=WALLET_LINK,
                        title=f"{count} app{'s' if count != 1 else ''} stopped for an unpaid balance",
                        body="They start again on their own as soon as the balance is repaid.",
                        dedupe_key=f"wallet:apps_stopped:{datetime.utcnow():%Y-%m-%d}")


async def low_balance_threshold(db: Any, company_id: UUID, currency: str) -> Optional[Decimal]:
    """The company's low-balance line in its currency: ``alerts.low_balance_usd`` if set,
    else ``alerts.low_balance_pct`` of its last top-up (§8.4); ``None`` when neither applies."""
    from src.billing.billing_models import WalletLot
    from src.billing.currency import current_rate, to_ccy
    from src.billing.settings_catalogue import value

    usd = await value(db, "alerts.low_balance_usd", company_id)
    if usd is not None:
        return to_ccy(Decimal(str(usd)), await current_rate(db, currency))
    pct = Decimal(str(await value(db, "alerts.low_balance_pct", company_id) or 0))
    last = (await db.execute(select(WalletLot.original).where(
        WalletLot.company_id == company_id, WalletLot.kind == "topup").order_by(WalletLot.granted_at.desc())
        .limit(1))).scalar_one_or_none()
    if not pct or last is None:
        return None
    return Decimal(str(last)) * pct / Decimal(100)


async def low_balance_notice(db: Any, company_id: UUID, available: Decimal, currency: str) -> int:
    from src.billing.wallet import money
    from src.notifications.service import notify

    line = await low_balance_threshold(db, company_id, currency)
    if line is None or available >= line:
        return 0
    return await notify(company_id, kind="wallet.low_balance", severity="warning", link=WALLET_LINK,
                        title=f"Your wallet is low: {money(available, currency)} left",
                        body=f"Below your alert line of {money(line, currency)}. Top up to keep things running.",
                        dedupe_key=f"wallet:low:{datetime.utcnow():%Y-%m-%d}")


async def expiring_notice(db: Any, company_id: UUID, *, within: timedelta = timedelta(days=7)) -> int:
    """Paid credit (top-ups) expiring within a week."""
    from src.billing.billing_models import CreditWallet, WalletLot
    from src.billing.wallet import money
    from src.notifications.service import notify

    now = datetime.utcnow()
    amount, first = (await db.execute(select(func.coalesce(func.sum(WalletLot.remaining), 0),
                                             func.min(WalletLot.expires_at)).where(
        WalletLot.company_id == company_id, WalletLot.kind == "topup", WalletLot.remaining > 0,
        WalletLot.expires_at > now, WalletLot.expires_at <= now + within))).one()
    if not amount or Decimal(str(amount)) <= 0:
        return 0
    currency = (await db.execute(select(CreditWallet.currency).where(CreditWallet.company_id == company_id))
                ).scalar_one_or_none() or "INR"
    return await notify(company_id, kind="wallet.credit_expiring", severity="info", link=WALLET_LINK,
                        title=f"{money(amount, currency)} of credit expires by {first:%d %b}",
                        body="Top-up credit is valid for a limited time; use it before then.",
                        dedupe_key=f"wallet:expiring:{first:%Y-%m-%d}")
