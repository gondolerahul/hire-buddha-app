"""Pollers: events from sources that send no webhooks (Phase 14 WS3 3.13, tech spec §7.6).

A poller asks a connected account for what is new since its cursor and turns
each new item into an event (``email.received`` …) in the business's
database, routed by its triggers like any other. The cursor lives in the
connection's settings (``settings["poll"]``); the first poll of an account
only records where it stands, so connecting a mailbox does not replay its
history as new events.

Polling costs the provider's quota and the business's time, so an account is
polled only while its business has an enabled trigger listening for the
poller's events (``email.*``, or ``*``). ``run_pollers`` is the event worker's
cron (every 2 minutes), once per tenant database.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from sqlalchemy import or_, select

logger = logging.getLogger(__name__)


@dataclass
class Polled:
    """One new item: its event type, dedupe key and data."""
    event_type: str
    dedupe_key: str
    data: Dict[str, Any] = field(default_factory=dict)


class Poller(Protocol):
    name: str
    connectors: Tuple[str, ...]
    event_prefix: str

    async def poll(self, connection: Any, credential: Any, cursor: Optional[Dict[str, Any]]
                   ) -> Tuple[List[Polled], Dict[str, Any]]:
        """``(new items, the new cursor)``; with no cursor, no items and the current position."""


def pollers() -> List[Poller]:
    from src.automation.pollers.mailbox import MailboxPoller

    return [MailboxPoller()]


async def _listening_companies(db: Any, prefix: str) -> set:
    from src.automation.models import Trigger

    rows = (await db.execute(select(Trigger.company_id).where(
        Trigger.enabled.is_(True), Trigger.kind == "event",
        or_(Trigger.event_type == "*", Trigger.event_type.like(f"{prefix}%"))).distinct())).scalars().all()
    return set(rows)


async def poll_scope(scope: Any) -> Dict[str, int]:
    """Every poller over one tenant database's accounts."""
    from src.automation import store
    from src.automation.events import Envelope
    from src.common.tenancy.session import tenant_session
    from src.connections import service
    from src.connections.models import Connection

    counts = {"accounts": 0, "events": 0, "errors": 0}
    for poller in pollers():
        async with tenant_session(scope) as db:
            companies = await _listening_companies(db, poller.event_prefix)
            if not companies:
                continue
            accounts = (await db.execute(select(Connection).where(
                Connection.company_id.in_(companies), Connection.connector_id.in_(poller.connectors),
                Connection.status.in_(("active", "expiring"))))).scalars().all()
        for connection in accounts:
            counts["accounts"] += 1
            try:
                credential = await service.system_credential(connection.company_id, connection.id,
                                                             purpose=f"poll:{poller.name}")
                items, cursor = await poller.poll(connection, credential, (connection.settings or {}).get("poll"))
            except Exception as error:  # noqa: BLE001 - one account does not stop the others
                logger.warning("poller %s: connection %s failed: %s", poller.name, connection.id, error)
                await service.record_health(connection.company_id, connection.id, error=str(error)[:300])
                counts["errors"] += 1
                continue
            stored = []
            async with tenant_session(connection.company_id) as db:
                for item in items:
                    row, created = await store.record(db, connection.company_id, Envelope(
                        type=item.event_type, source=f"poller:{poller.name}", trust="verified",
                        dedupe_key=item.dedupe_key[:512], subject=f"connection:{connection.id}",
                        data={**item.data, "connection_id": str(connection.id),
                              "connector_id": connection.connector_id}))
                    if created:
                        stored.append(row.id)
                fresh = await db.get(Connection, connection.id)
                fresh.settings = {**(fresh.settings or {}), "poll": cursor}
                await db.commit()
            for event_id in stored:
                await store.nudge(connection.company_id, event_id)
            counts["events"] += len(stored)
    return counts


async def run_pollers(ctx: Dict[str, Any]) -> Dict[str, int]:
    from src.common.tenancy.session import tenant_scopes

    totals = {"accounts": 0, "events": 0, "errors": 0}
    for scope in await tenant_scopes():
        try:
            result = await poll_scope(scope)
        except Exception:  # noqa: BLE001
            logger.exception("pollers failed for tenant %s", scope)
            totals["errors"] += 1
            continue
        for key, value in result.items():
            totals[key] += value
    return totals
