"""What follows a change of wallet state (Phase 15 T4-6…T4-9, tech design §6.3).

The wallet (``src.billing.wallet``) moves between ``ok``, ``in_debt``,
``over_tolerance`` and ``suspended``; the gates that read the state — run and
call admission, the breaker, campaigns, the mobile dialer, sandbox sessions,
the Data API — need nothing more. What does need doing when the state changes
is here, called after the change has committed:

* leaving ``ok``: automation the system paused for balance; hosted apps stop
  after ``billing.app_stop_grace_hours`` (the apps job, T4-7);
* back to ``ok``: automation paused for balance resumes, apps stopped for
  balance start again (campaigns stay paused: their owner resumes them);
* every change: the company's admins are told (T4-9).

Best-effort: a failure is logged and never undoes the wallet change.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

NEGATIVE_BALANCE = "negative_balance"


async def wallet_changed(db: Any, company_id: UUID, change: Optional[Any]) -> None:
    """React to ``change`` (a ``wallet.Change``) when it moved the wallet's state."""
    if change is None or change.state_before == change.state_after:
        return
    before, after = change.state_before, change.state_after
    logger.info("wallet of %s: %s -> %s", company_id, before, after)
    from src.billing.suspension import forget
    forget(company_id)                       # read-only (or not) from the next request
    for step in (_automation, _apps, _numbers, _notify):
        try:
            await step(db, company_id, before, after)
        except Exception:  # noqa: BLE001 - enforcement must not undo the wallet change
            logger.warning("wallet state %s -> %s for %s: %s failed", before, after, company_id, step.__name__,
                           exc_info=True)


async def _automation(db: Any, company_id: UUID, before: str, after: str) -> None:
    from src.billing.enforcement_hooks import pause_automation, resume_automation

    from src.billing import rollout

    if before == "ok":
        if await rollout.enabled(db, rollout.ENFORCEMENT):              # T10-3
            await pause_automation(company_id)
    elif after == "ok":
        await resume_automation(company_id)


async def _apps(db: Any, company_id: UUID, before: str, after: str) -> None:
    from src.billing.enforcement_hooks import start_apps_for_balance

    if after == "ok":
        await start_apps_for_balance(company_id)
    # Stopping waits for the grace period: the apps job (``billing_enforce_wallets``) stops them.


async def _numbers(db: Any, company_id: UUID, before: str, after: str) -> None:
    """Numbers held for the balance take calls again as soon as it is repaid (NR-4)."""
    if after != "ok":
        return
    from sqlalchemy import update

    from src.billing.billing_models import NumberRental
    from src.common.tenancy.session import control_session

    async with control_session() as session:
        await session.execute(update(NumberRental).where(NumberRental.company_id == company_id,
                                                         NumberRental.status == "held")
                              .values(status="active", held_at=None))
        await session.commit()


async def _notify(db: Any, company_id: UUID, before: str, after: str) -> None:
    from src.billing.notices import wallet_state_notice

    await wallet_state_notice(db, company_id, before, after)
