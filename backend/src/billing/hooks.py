"""Billing events other modules act on (Phase 15 T6-6).

The partner programme (WS15-8) claws back the commission earned on a payment
that is refunded, and marks a refunded setup or customisation fee; it
registers with :func:`on_refund` (``src.partners.listeners``, imported at
start-up). A listener's failure is logged and never undoes the refund.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, List

logger = logging.getLogger(__name__)

RefundListener = Callable[[Any, Any, Any], Awaitable[None]]     # (db, payment, refund)
_refund_listeners: List[RefundListener] = []


def on_refund(listener: RefundListener) -> RefundListener:
    """Register a listener for refunds (usable as a decorator)."""
    if listener not in _refund_listeners:
        _refund_listeners.append(listener)
    return listener


async def refunded(db: Any, payment: Any, refund: Any) -> None:
    import src.partners.listeners  # noqa: F401 - registers the programme's listeners

    for listener in list(_refund_listeners):
        try:
            await listener(db, payment, refund)
        except Exception:  # noqa: BLE001
            logger.warning("refund listener %s failed for payment %s", getattr(listener, "__name__", listener),
                           getattr(payment, "id", None), exc_info=True)
