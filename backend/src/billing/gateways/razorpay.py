"""Razorpay as a :class:`~src.billing.gateways.PaymentGateway` (Phase 15 T6-3).

Keys come from the ``razorpay_keys`` registry row (``src.billing.razorpay_gateway``,
T0-2). Amounts are sent in minor units of the order's currency (INR paise,
USD cents): ``gateway_minor_units`` with the currency's ``minor_units`` — the
one rounding of a payment.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.billing.gateways import GatewayError, GatewayUnavailable
from src.billing.razorpay_gateway import get_razorpay_creds, razorpay_client


def _minor(amount: Decimal, digits: int) -> int:
    from src.billing.currency import gateway_minor_units

    return gateway_minor_units(amount, digits)


class RazorpayGateway:
    name = "razorpay"

    def __init__(self, client: Any, creds: Dict[str, Any], digits: Optional[Dict[str, int]] = None):
        self.client = client
        self.key_id = creds["key_id"]
        self.key_secret = creds["key_secret"]
        self.webhook_secret = creds.get("webhook_secret")
        self._digits = digits or {}

    @classmethod
    async def from_registry(cls, db: Any) -> "RazorpayGateway":
        from sqlalchemy import select

        from src.billing.billing_models import Currency

        creds = await get_razorpay_creds(db)
        client = razorpay_client(creds)
        if client is None or not creds:
            raise GatewayUnavailable("Payment gateway not configured. Add Razorpay keys to the Integration "
                                     "Registry with SKU 'razorpay_keys'.")
        digits = dict((await db.execute(select(Currency.code, Currency.minor_units))).all())
        return cls(client, creds, {k: int(v) for k, v in digits.items()})

    def _amount(self, amount: Decimal, currency: str) -> int:
        return _minor(Decimal(str(amount)), self._digits.get(currency.upper(), 2))

    @staticmethod
    def _call(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except Exception as error:  # noqa: BLE001 - the SDK raises many kinds
            raise GatewayError(str(error)) from error

    async def create_order(self, amount: Decimal, currency: str, *, receipt: str, notes: Dict[str, str]) -> Dict[str, Any]:
        minor = self._amount(amount, currency)
        order = self._call(self.client.order.create,
                           {"amount": minor, "currency": currency.upper(), "receipt": receipt[:40], "notes": notes})
        return {"id": order["id"], "amount_minor": minor}

    async def create_plan(self, *, name: str, amount: Decimal, currency: str, description: str,
                          notes: Dict[str, str]) -> str:
        plan = self._call(self.client.plan.create, {
            "period": "monthly", "interval": 1,
            "item": {"name": name, "amount": self._amount(amount, currency), "currency": currency.upper(),
                     "description": description},
            "notes": notes,
        })
        return plan["id"]

    async def create_subscription(self, *, plan_id: str, total_count: int, notes: Dict[str, str]) -> Dict[str, Any]:
        return self._call(self.client.subscription.create, {"plan_id": plan_id, "total_count": total_count,
                                                            "customer_notify": 1, "notes": notes})

    async def change_subscription_plan(self, subscription_id: str, *, plan_id: str, at_cycle_end: bool) -> Dict[str, Any]:
        # PATCH /subscriptions/:id — "now" prorates the difference in this cycle (spike SP-15-2).
        return self._call(self.client.subscription.edit, subscription_id, {
            "plan_id": plan_id, "schedule_change_at": "cycle_end" if at_cycle_end else "now",
            "customer_notify": 1})

    async def cancel_subscription(self, subscription_id: str, *, at_cycle_end: bool) -> Dict[str, Any]:
        return self._call(self.client.subscription.cancel, subscription_id,
                          {"cancel_at_cycle_end": 1 if at_cycle_end else 0})

    async def fetch_subscription(self, subscription_id: str) -> Dict[str, Any]:
        return self._call(self.client.subscription.fetch, subscription_id)

    async def subscription_invoices(self, subscription_id: str) -> List[Dict[str, Any]]:
        return (self._call(self.client.invoice.all, {"subscription_id": subscription_id}) or {}).get("items") or []

    async def refund(self, payment_id: str, amount: Decimal, currency: str, *, notes: Dict[str, str]) -> Dict[str, Any]:
        minor = self._amount(amount, currency)
        refund = self._call(self.client.payment.refund, payment_id, {"amount": minor, "notes": notes})
        return {"id": refund["id"], "amount_minor": minor}

    def payment_signature_valid(self, order_id: str, payment_id: str, signature: str) -> bool:
        from src.billing.payment_service import razorpay_signature_valid

        return razorpay_signature_valid(self.key_secret, f"{order_id}|{payment_id}", signature)

    def subscription_signature_valid(self, payment_id: str, subscription_id: str, signature: str) -> bool:
        from src.billing.payment_service import razorpay_signature_valid

        return razorpay_signature_valid(self.key_secret, f"{payment_id}|{subscription_id}", signature)
