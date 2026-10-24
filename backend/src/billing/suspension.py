"""A suspended account (Phase 15 T4-8, tech design §6.3): read-only until its debt is repaid.

A wallet over its tolerance for ``billing.suspend_after_days`` is suspended by
the wallet job. Then:

* the company's people still sign in and read everything, but any request that
  changes something is refused (402) — except paying: the wallet, top-ups and
  subscriptions (``/api/v1/credits``), signing in and out, and notifications;
* the Data API answers nothing (402 ``account_suspended``): the business's
  apps cannot read or write its records;
* hosted apps are stopped (the apps step of the wallet job); numbers are held.

The state is read per request with a short in-process cache.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Tuple

SUSPENDED_DETAIL = ("This account is suspended for an unpaid balance: it is read-only until the balance is "
                    "repaid. Top up from the Wallet page to open it again.")
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Paying, signing in and out, and reading one's notices stay open while suspended.
ALWAYS_OPEN = ("/api/v1/credits", "/api/v1/auth", "/api/v1/notifications")
CACHE_SECONDS = 15.0

_cache: Dict[str, Tuple[bool, float]] = {}


class AccountSuspended(Exception):
    pass


async def is_suspended(db: Any, company_id: Any) -> bool:
    if company_id is None:
        return False
    key = str(company_id)
    hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    from sqlalchemy import select

    from src.billing.billing_models import CreditWallet

    state = (await db.execute(select(CreditWallet.state).where(CreditWallet.company_id == company_id))
             ).scalar_one_or_none()
    from src.billing import rollout
    suspended = state == "suspended" and await rollout.enabled(db, rollout.ENFORCEMENT)
    _cache[key] = (suspended, time.monotonic() + CACHE_SECONDS)
    return suspended


def forget(company_id: Any = None) -> None:
    if company_id is None:
        _cache.clear()
    else:
        _cache.pop(str(company_id), None)


async def refuse_writes(request: Any, db: Any, user: Any) -> None:
    """402 when ``user``'s company is suspended and ``request`` would change something."""
    from fastapi import HTTPException

    if request is None or request.method not in WRITE_METHODS:
        return
    path = request.url.path
    if any(path.startswith(prefix) for prefix in ALWAYS_OPEN):
        return
    if await is_suspended(db, getattr(user, "company_id", None)):
        raise HTTPException(status_code=402, detail=SUSPENDED_DETAIL)
