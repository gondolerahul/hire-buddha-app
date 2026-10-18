"""Automation's notifications (functional spec §3.6; plan WS3 3.11).

| What | Who | How often |
|------|-----|-----------|
| An event failed five times | owners, admins, operators | once per event |
| A trigger keeps being refused (3 problems in 24 h) | owners, admins, operators | once a day per trigger |
| A loop was stopped (the loop limit) | owners, admins, operators | once a day per trigger |
| An automated run was blocked by the wallet | owners, admins | once a day per trigger |
| Schedule times were missed (catch-up said skip) | owners, admins | once a day per trigger |

Each also stays in the event log and the Control Room; a notification is
best effort and never stops routing or scheduling.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from src.automation import guards
from src.automation.models import TriggerFiring

logger = logging.getLogger(__name__)

FAILING_AFTER = 3
CONTROL_ROOM = "/automation"


def _day() -> str:
    return f"{datetime.utcnow():%Y-%m-%d}"


async def _send(company_id: Any, **kwargs: Any) -> None:
    from src.notifications.service import notify

    try:
        await notify(company_id, **kwargs)
    except Exception:  # noqa: BLE001 - never in the way of routing
        logger.exception("automation notification failed")


async def event_dead(company_id: Any, event_id: Any, event_type: str, error: str) -> None:
    await _send(company_id, kind="automation.event_dead", audience="operators", severity="error",
                dedupe_key=f"automation.event_dead:{event_id}",
                title=f"An event failed five times: {event_type}",
                body=f"It was not handled ({error[:300]}). Retry it from the Control Room's event log.",
                link=CONTROL_ROOM)


async def after_decision(db: Any, company_id: Any, trigger: Any, decision: guards.Decision) -> None:
    """The notifications one trigger's decision calls for, if any."""
    name, trigger_id = trigger.name, trigger.id
    if decision.outcome == guards.SKIPPED_CHAIN_DEPTH:
        await _send(company_id, kind="automation.loop_stopped", audience="operators", severity="warning",
                    dedupe_key=f"automation.loop_stopped:{trigger_id}:{_day()}",
                    title=f"A loop was stopped: {name}", body=decision.reason, link=CONTROL_ROOM)
    if decision.outcome == guards.BLOCKED_BUDGET:
        await _send(company_id, kind="automation.blocked_budget", audience="admins", severity="error",
                    dedupe_key=f"automation.blocked_budget:{trigger_id}:{_day()}",
                    title=f"An automated run was blocked by the wallet: {name}",
                    body=f"{decision.reason}. Top up the wallet so automated work can run.", link="/wallet")
    if decision.outcome in (guards.BLOCKED_BUDGET, guards.BLOCKED_POLICY, guards.FAILED):
        problems = (await db.execute(select(func.count()).select_from(TriggerFiring).where(
            TriggerFiring.trigger_id == trigger_id,
            TriggerFiring.outcome.in_((guards.BLOCKED_BUDGET, guards.BLOCKED_POLICY, guards.FAILED)),
            TriggerFiring.decided_at >= datetime.utcnow() - timedelta(hours=24)))).scalar() or 0
        if problems >= FAILING_AFTER:
            await _send(company_id, kind="automation.trigger_failing", audience="operators", severity="warning",
                        dedupe_key=f"automation.trigger_failing:{trigger_id}:{_day()}",
                        title=f"A trigger keeps failing: {name}",
                        body=f"{problems} of its runs were not started in the last 24 hours; the last: "
                             f"{decision.reason}", link=CONTROL_ROOM)


async def missed_schedule(company_id: Any, trigger: Any, start: datetime, end: datetime) -> None:
    await _send(company_id, kind="automation.missed_schedule", audience="admins", severity="warning",
                dedupe_key=f"automation.missed_schedule:{trigger.id}:{_day()}",
                title=f"Schedule times were missed: {trigger.name}",
                body=f"Automation was not running from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC; "
                     "its catch-up rule skipped those times.", link=CONTROL_ROOM)
