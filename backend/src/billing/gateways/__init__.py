"""Payment gateways behind one interface (Phase 15 T6-3, tech design §12.2).

The billing code talks to a :class:`PaymentGateway`; Razorpay (INR and USD,
``razorpay.py``) is the one there is. Amounts are exact ``Decimal`` in the
currency's major unit; the adapter converts them to the gateway's minor units
(paise, cents) with :func:`src.billing.currency.gateway_minor_units` — the only
rounding of a payment (K-1).

``await get_gateway(db)`` is the configured gateway, or raises
:class:`GatewayUnavailable` (the routes answer 503).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class GatewayUnavailable(RuntimeError):
    """No gateway is configured (no keys)."""


class GatewayError(RuntimeError):
    """The gateway refused or failed a request."""


@runtime_checkable
class PaymentGateway(Protocol):
    name: str
    key_id: str
    webhook_secret: Optional[str]

    async def create_order(self, amount: Decimal, currency: str, *, receipt: str, notes: Dict[str, str]) -> Dict[str, Any]:
        """A one-time order; ``{"id", "amount_minor"}``."""

    async def create_plan(self, *, name: str, amount: Decimal, currency: str, description: str,
                          notes: Dict[str, str]) -> str:
        """A monthly plan charging ``amount`` each cycle; its id."""

    async def create_subscription(self, *, plan_id: str, total_count: int, notes: Dict[str, str]) -> Dict[str, Any]:
        """A subscription on ``plan_id``; the gateway's record (``id``)."""

    async def change_subscription_plan(self, subscription_id: str, *, plan_id: str, at_cycle_end: bool) -> Dict[str, Any]:
        """Move a subscription to another plan, now (the gateway prorates) or at the cycle's end."""

    async def cancel_subscription(self, subscription_id: str, *, at_cycle_end: bool) -> Dict[str, Any]:
        """Stop the mandate: at the cycle's end, or now."""

    async def fetch_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """The gateway's subscription (``status``, ``current_start``, ``current_end``, ``plan_id``)."""

    async def subscription_invoices(self, subscription_id: str) -> List[Dict[str, Any]]:
        """The subscription's invoices (``status``, ``payment_id``, ``amount``)."""

    async def refund(self, payment_id: str, amount: Decimal, currency: str, *, notes: Dict[str, str]) -> Dict[str, Any]:
        """Refund ``amount`` of a captured payment; ``{"id", "amount_minor"}``."""

    def payment_signature_valid(self, order_id: str, payment_id: str, signature: str) -> bool:
        ...

    def subscription_signature_valid(self, payment_id: str, subscription_id: str, signature: str) -> bool:
        ...


async def get_gateway(db: Any) -> PaymentGateway:
    """The configured gateway (Razorpay), or :class:`GatewayUnavailable`."""
    from src.billing.gateways.razorpay import RazorpayGateway

    return await RazorpayGateway.from_registry(db)


async def minor(db: Any, amount: Decimal, currency: str) -> int:
    from src.billing.currency import gateway_minor_units, minor_units

    return gateway_minor_units(amount, await minor_units(db, currency))
