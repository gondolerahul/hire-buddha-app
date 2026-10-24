"""The parts of the platform a wallet state switches off and on (Phase 15 T4-6, T4-7; tech design §6.3).

* Automation: a wallet leaving ``ok`` pauses the business's automation with
  ``paused_reason='negative_balance'`` — events are held, not lost, and run in
  order when it resumes; back to ``ok`` resumes it, but only a pause the
  system made (a pause the business made stays).
* Hosted apps: once the wallet has been out of ``ok`` for
  ``billing.app_stop_grace_hours`` (the wallet job), each published app is
  stopped and marked ``settings.stopped_for_balance``; back to ``ok`` starts
  exactly those again.

Each function is best-effort and idempotent: the wallet job calls the stop
again every tick, and a start finds nothing to do when nothing was stopped.
"""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

logger = logging.getLogger(__name__)

NEGATIVE_BALANCE = "negative_balance"
STOPPED_FOR_BALANCE = "stopped_for_balance"


async def pause_automation(company_id: UUID) -> bool:
    """Pause the business's automation for balance, unless it is paused already. True when it paused it."""
    from src.automation.limits import forget_state
    from src.automation.models import AutomationLimitsRow
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        row = (await db.execute(select(AutomationLimitsRow).where(AutomationLimitsRow.company_id == company_id))
               ).scalar_one_or_none()
        if row is None:
            row = AutomationLimitsRow(company_id=company_id, limits={})
            db.add(row)
        elif row.automation_state == "paused":
            return False
        row.automation_state, row.paused_reason, row.updated_at = "paused", NEGATIVE_BALANCE, datetime.utcnow()
        entry = await db.get(TenantDirectoryEntry, company_id)
        if entry is not None:
            entry.automation_state = "paused"
        await db.commit()
    forget_state(company_id)
    return True


async def resume_automation(company_id: UUID) -> bool:
    """Resume automation the system paused for balance. True when it resumed it."""
    from src.automation.limits import forget_state
    from src.automation.models import AutomationLimitsRow
    from src.common.tenancy.models import TenantDirectoryEntry
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        row = (await db.execute(select(AutomationLimitsRow).where(AutomationLimitsRow.company_id == company_id))
               ).scalar_one_or_none()
        if row is None or row.automation_state != "paused" or row.paused_reason != NEGATIVE_BALANCE:
            return False
        row.automation_state, row.paused_reason, row.updated_at = "running", None, datetime.utcnow()
        entry = await db.get(TenantDirectoryEntry, company_id)
        if entry is not None:
            entry.automation_state = "running"
        await db.commit()
    forget_state(company_id)
    return True


async def _published_apps(company_id: UUID, *, stopped_for_balance: bool) -> list:
    from src.apps.db import app_session
    from src.apps.models import App

    try:
        async with app_session(company_id) as db:
            if stopped_for_balance:
                rows = (await db.execute(select(App).where(App.company_id == company_id,
                                                           App.status == "stopped"))).scalars().all()
                return [a.id for a in rows if (a.settings or {}).get(STOPPED_FOR_BALANCE)]
            rows = (await db.execute(select(App).where(App.company_id == company_id,
                                                       App.status == "published"))).scalars().all()
            return [a.id for a in rows]
    except Exception:  # noqa: BLE001 - a business with no workspace has no apps
        logger.debug("no apps read for %s", company_id, exc_info=True)
        return []


async def _mark(company_id: UUID, app_id: UUID, stopped: bool) -> None:
    from src.apps.db import app_session
    from src.apps.models import App

    async with app_session(company_id) as db:
        app = await db.get(App, app_id)
        if app is None:
            return
        settings = dict(app.settings or {})
        if stopped:
            settings[STOPPED_FOR_BALANCE] = datetime.utcnow().isoformat()
        else:
            settings.pop(STOPPED_FOR_BALANCE, None)
        app.settings = settings
        await db.commit()


async def stop_apps_for_balance(company_id: UUID) -> int:
    """Stop the business's published apps (T4-7); returns how many were stopped."""
    from src.apps.service import operate

    stopped = 0
    for app_id in await _published_apps(company_id, stopped_for_balance=False):
        try:
            await operate(company_id, app_id, "stop")
            await _mark(company_id, app_id, True)
            stopped += 1
        except Exception:  # noqa: BLE001 - one app does not stop the rest
            logger.warning("app %s of %s not stopped for balance", app_id, company_id, exc_info=True)
    return stopped


async def start_apps_for_balance(company_id: UUID) -> int:
    """Start the apps stopped for balance again; returns how many were started."""
    from src.apps.service import operate

    started = 0
    for app_id in await _published_apps(company_id, stopped_for_balance=True):
        try:
            await operate(company_id, app_id, "start")
            await _mark(company_id, app_id, False)
            started += 1
        except Exception:  # noqa: BLE001
            logger.warning("app %s of %s not restarted after repayment", app_id, company_id, exc_info=True)
    return started
