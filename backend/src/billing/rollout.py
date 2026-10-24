"""The rollout switches (Phase 15 T10-3, plan 08 §6), read where they act.

Staff platform settings, on by default (the behaviour as built):

* ``billing.enforcement_enabled`` — a wallet's state stops new work, pauses
  automation, holds numbers and suspends accounts; off, the debt is recorded
  and nothing is blocked (``credit_service.state_refusal`` sees the switch in
  the balance as ``enforced``);
* ``billing.apps_stop_enabled`` — hosted apps stop for balance;
* ``entitlements.enforced`` — plans gate features and limits;
* ``partners.programme_enabled`` — applications open, commissions accrue.

Read often (every balance), so each value is cached for ``CACHE_SECONDS``;
``forget()`` after a change (the settings API does).
"""
from __future__ import annotations

import time
from typing import Any, Dict, Tuple

ENFORCEMENT = "billing.enforcement_enabled"
APPS_STOP = "billing.apps_stop_enabled"
ENTITLEMENTS = "entitlements.enforced"
PARTNERS = "partners.programme_enabled"
SWITCHES = (ENFORCEMENT, APPS_STOP, ENTITLEMENTS, PARTNERS)
CACHE_SECONDS = 30.0

_cache: Dict[str, Tuple[bool, float]] = {}


async def enabled(db: Any, key: str) -> bool:
    """Whether the switch ``key`` is on (unreadable: on, the built behaviour)."""
    hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    try:
        from src.billing.settings_catalogue import value

        on = bool(await value(db, key))
    except Exception:  # noqa: BLE001 — a switch never breaks the path it guards
        on = True
    _cache[key] = (on, time.monotonic() + CACHE_SECONDS)
    return on


def forget() -> None:
    _cache.clear()
