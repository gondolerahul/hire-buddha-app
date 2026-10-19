"""Events the tenant runtime emits (Phase 14 WS6; Appendix B).

``app.build.succeeded|failed``, ``app.deployed``, ``app.unhealthy`` (the App
Controller's), and the code lanes' ``code.review.opened``,
``code.checks.completed``, ``code.promoted``, ``code.rejected``. Stored in the
business's event log like any other, so a trigger can start an agent on them.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def emit(company_id: Any, event_type: str, subject: str, data: Dict[str, Any], *,
               source: str = "apps") -> None:
    """Store the event (and nudge the router). Best-effort: the change it reports stands without it."""
    from src.automation import store
    from src.automation.events import Envelope
    from src.common.tenancy.session import tenant_session

    try:
        async with tenant_session(company_id) as db:
            await store.emit(db, company_id, Envelope(
                type=event_type, source=source, trust="internal", subject=subject,
                dedupe_key=f"{event_type}:{subject}:{datetime.utcnow().isoformat()}", data=data))
    except Exception:  # noqa: BLE001
        logger.warning("event %s for %s not stored", event_type, subject, exc_info=True)
