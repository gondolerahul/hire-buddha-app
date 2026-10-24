"""The wallet's jobs (Phase 15 T3-6, T4-4, T4-7…T4-9, T5-5; registered in ``ai/worker.py``).

* every 15 minutes — ``tick``: lots past their expiry expire (W-6); each
  company whose local date has no daily lot gets one (§7.3); enforcement:
  a wallet over its tolerance for ``billing.suspend_after_days`` is
  suspended, a wallet out of ``ok`` for ``billing.app_stop_grace_hours`` has
  its apps stopped; low-balance and expiring-credit notices.
* hourly — ``settle_standalone``: usage with no run, and any row left
  unsettled for more than ten minutes (§6.5).
* nightly — ``check_wallets``: each wallet equals its ledger (W-9).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def expire_due(db: Any, *, now: Optional[datetime] = None) -> dict:
    from src.billing.billing_models import WalletLot
    from src.billing.wallet import WalletService

    now = now or datetime.utcnow()
    ids = list((await db.execute(select(WalletLot.company_id).where(
        WalletLot.remaining > 0, WalletLot.expires_at <= now).distinct())).scalars().all())
    expired = errors = 0
    for company_id in ids:
        try:
            change = await WalletService(db).expire(company_id, now=now)
            await db.commit()
            expired += len(change.entries)
        except Exception as error:  # noqa: BLE001 - one company's failure is its own
            await db.rollback()
            errors += 1
            logger.error("lot expiry for %s failed: %s", company_id, error)
    return {"companies": len(ids), "lots": expired, "errors": errors}


async def enforce(db: Any, *, now: Optional[datetime] = None) -> dict:
    """Suspension after N days over tolerance (T4-8); apps stopped after the grace (T4-7)."""
    from src.billing.billing_models import CreditWallet
    from src.billing.enforcement import wallet_changed
    from src.billing.enforcement_hooks import stop_apps_for_balance
    from src.billing.notices import apps_stopped_notice
    from src.billing.settings_catalogue import value
    from src.billing.wallet import WalletService

    from src.billing import rollout

    now = now or datetime.utcnow()
    out = {"suspended": 0, "apps_stopped": 0, "errors": 0}
    enforcing = await rollout.enabled(db, rollout.ENFORCEMENT)            # T10-3
    stopping = await rollout.enabled(db, rollout.APPS_STOP)
    wallets = (await db.execute(select(CreditWallet.company_id, CreditWallet.state, CreditWallet.in_debt_since,
                                       CreditWallet.over_tolerance_since)
                                .where(CreditWallet.state != "ok"))).all()
    for w in wallets:
        try:
            days = int(await value(db, "billing.suspend_after_days", w.company_id))
            if (enforcing and w.state == "over_tolerance" and w.over_tolerance_since is not None
                    and w.over_tolerance_since <= now - timedelta(days=days)):
                change = await WalletService(db).suspend(w.company_id, now=now)
                await db.commit()
                out["suspended"] += 1
                await wallet_changed(db, w.company_id, change)
            hours = Decimal(str(await value(db, "billing.app_stop_grace_hours", w.company_id)))
            if stopping and w.in_debt_since is not None and w.in_debt_since <= now - timedelta(hours=float(hours)):
                stopped = await stop_apps_for_balance(w.company_id)
                if stopped:
                    out["apps_stopped"] += stopped
                    await apps_stopped_notice(w.company_id, stopped)
        except Exception as error:  # noqa: BLE001
            await db.rollback()
            out["errors"] += 1
            logger.error("wallet enforcement for %s failed: %s", w.company_id, error)
    return out


async def notices(db: Any) -> dict:
    """Low balance and expiring credit, for wallets that are ``ok`` (the others got a state notice)."""
    from src.billing.billing_models import CreditWallet
    from src.billing.notices import expiring_notice, low_balance_notice

    told = 0
    for w in (await db.execute(select(CreditWallet.company_id, CreditWallet.cached_available,
                                      CreditWallet.currency).where(CreditWallet.state == "ok"))).all():
        try:
            told += await low_balance_notice(db, w.company_id, Decimal(str(w.cached_available or 0)), w.currency)
            told += await expiring_notice(db, w.company_id)
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.warning("wallet notices for %s failed", w.company_id, exc_info=True)
    return {"told": told}


async def tick(db: Any, *, now: Optional[datetime] = None) -> dict:
    from src.billing.daily_credits import grant_due

    now = now or datetime.utcnow()
    from src.billing.rentals import hold_for_balance

    return {"expired": await expire_due(db, now=now), "daily_credits": await grant_due(db, now=now),
            "enforcement": await enforce(db, now=now), "numbers": await hold_for_balance(db, now=now),
            "notices": await notices(db)}


async def settle_standalone(db: Any, *, now: Optional[datetime] = None) -> dict:
    from src.billing.enforcement import wallet_changed
    from src.billing.settlement import companies_with_unsettled, settle_unsettled

    out = {"companies": 0, "rows": 0, "billed_usd": "0", "errors": 0}
    billed = Decimal(0)
    for company_id in await companies_with_unsettled(db):
        try:
            settled = await settle_unsettled(db, company_id, now=now)
            await db.commit()
            out["companies"] += 1
            out["rows"] += len(settled.rows)
            billed += settled.billed_usd
            await wallet_changed(db, company_id, settled.change)
        except Exception as error:  # noqa: BLE001
            await db.rollback()
            out["errors"] += 1
            logger.error("standalone settlement for %s failed: %s", company_id, error)
    out["billed_usd"] = str(billed)
    return out


async def check_wallets(db: Any) -> dict:
    """Every wallet against its ledger (W-9); a mismatch is an error event to alert on."""
    from src.ai.core.events import event
    from src.billing.billing_models import CreditWallet
    from src.billing.wallet import WalletService

    problems = {}
    for company_id in (await db.execute(select(CreditWallet.company_id))).scalars().all():
        found = await WalletService(db).check(company_id)
        if found:
            problems[str(company_id)] = found
            logger.error("wallet of %s does not equal its ledger: %s", company_id, found)
            event("billing.wallet_ledger_mismatch", company_id=str(company_id), problems=found[:10],
                  severity="error")
    await db.rollback()
    return {"problems": problems}
