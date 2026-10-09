"""live_sessions.py — the live AI sessions a company holds, and the cap on them (GW-02).

A live session — a phone call's media stream, a browser's ``/stream/audio``,
a video call — holds a model connection billed to the company for as long as it
lasts. Nothing limited how many one company could hold at once.

``LIVE_SESSIONS_PER_COMPANY`` caps them. A call is refused at admission
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

__all__ = ["LiveSlot", "acquire", "at_cap", "open_count", "cap_message"]

_open: Counter[str] = Counter()


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


def at_cap(company_id: Any) -> bool:
    return open_count(company_id) >= settings.LIVE_SESSIONS_PER_COMPANY


def cap_message() -> str:
    return (f"The company already has {settings.LIVE_SESSIONS_PER_COMPANY} live calls or sessions, "
            "its limit. Try again when one ends.")


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
