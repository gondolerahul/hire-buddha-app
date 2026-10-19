"""Connection crons on the event worker (Phase 14 WS5 5.3, 5.5).

* ``connection_refresh`` — every 10 minutes, once per tenant database: tokens
  about to expire are refreshed; expiries that cannot be refreshed are warned
  about; a failed refresh marks the connection ``needs_reconnect``.
* ``prune_unrouted_events`` — daily: unrouted provider deliveries older than 7 days go.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def connection_refresh(ctx: Dict[str, Any]) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_scopes
    from src.connections.service import refresh_due

    totals = {"refreshed": 0, "failed": 0, "warned": 0, "errors": 0}
    for scope in await tenant_scopes():
        try:
            result = await refresh_due(scope)
        except Exception:  # noqa: BLE001 - one tenant does not stop the rest
            logger.exception("connection refresh failed for tenant %s", scope)
            totals["errors"] += 1
            continue
        for key, value in result.items():
            totals[key] += value
    return totals


async def prune_unrouted_events(ctx: Dict[str, Any]) -> Dict[str, int]:
    from src.connections.webhooks import prune_unrouted

    return {"deleted": await prune_unrouted()}
