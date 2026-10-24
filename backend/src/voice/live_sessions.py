"""live_sessions.py — the live AI sessions a company holds, and the cap on them (GW-02).

A live session — a phone call's media stream, a browser's ``/stream/audio``,
a video call — holds a model connection billed to the company for as long as it
lasts. Nothing limited how many one company could hold at once.

The company's plan caps them (``limit.live_sessions``, Phase 15 T6-2; its
default is ``LIVE_SESSIONS_PER_COMPANY``). A call is refused at admission
(``call_admission.call_refusal``: the provider's webhook, a campaign's dial,
the media socket) when the company is at the cap, and a session takes its place
with :func:`acquire` as it connects and gives it back when it ends — so two
calls admitted together cannot both pass the last place.

The count is this process's: the API runs as one instance (HD12, GW-21). A
second instance needs a shared count.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Optional

from src.common.config import settings

logger = logging.getLogger(__name__)

__all__ = ["LiveSlot", "acquire", "at_cap", "open_count", "total_open", "cap_message", "load_limit"]

_open: Counter[str] = Counter()
# Each company's plan limit, read at admission (``load_limit``) for the sync checks below.
_limits: dict[str, Optional[int]] = {}


async def load_limit(db: Any, company_id: Any) -> Optional[int]:
    """Read the company's ``limit.live_sessions`` (its plan's) for :func:`at_cap` and :func:`acquire`."""
    from src.billing.features import limit_of

    try:
        limit = await limit_of(db, company_id, "limit.live_sessions")
    except Exception:  # noqa: BLE001 - the platform default stands
        limit = settings.LIVE_SESSIONS_PER_COMPANY
    _limits[str(company_id)] = limit
    return limit


def limit_for(company_id: Any) -> Optional[int]:
    return _limits.get(str(company_id), settings.LIVE_SESSIONS_PER_COMPANY)


class LiveSlot:
    """One of a company's places; :meth:`release` gives it back, once."""

    def __init__(self, company: str) -> None:
        self.company = company
        self._held = True

    def release(self) -> None:
        if self._held:
            self._held = False
            _open[self.company] -= 1
            if _open[self.company] <= 0:
                del _open[self.company]


def open_count(company_id: Any) -> int:
    return _open.get(str(company_id), 0)


def total_open() -> int:
    """Every company's live sessions in this process."""
    return sum(_open.values())


def at_cap(company_id: Any) -> bool:
    limit = limit_for(company_id)
    return limit is not None and open_count(company_id) >= limit


def cap_message(company_id: Any = None) -> str:
    return (f"The company already has {limit_for(company_id)} live calls or sessions, "
            "its plan's limit. Try again when one ends.")


def acquire(company_id: Any, *, kind: str) -> Optional[LiveSlot]:
    """A place for one more live session, or ``None`` at the cap."""
    from src.ai.core.events import event

    company = str(company_id)
    if at_cap(company):
        logger.warning("Live session refused for company %s: %d open", company, open_count(company))
        event("voice.live_session.refused", company_id=company, kind=kind, open=open_count(company))
        return None
    _open[company] += 1
    return LiveSlot(company)
