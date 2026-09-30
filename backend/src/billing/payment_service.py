"""
Payment Service — turns a verified Razorpay payment into credits, exactly once.

The browser callback (``POST /credits/topup/verify``) and the server-to-server
webhook both land here, so a payment is credited by whichever arrives first and
ignored by the other. The amount credited is always the one stored when the
order was created — never one supplied by the caller (BC-01).
"""
import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing.billing_models import CreditWallet, PaymentTransaction
from src.billing.credit_service import CreditService

logger = logging.getLogger(__name__)


class PaymentNotFound(LookupError):
    """No pending transaction matches the payment."""


def razorpay_signature_valid(secret: str, message: str, signature: str) -> bool:
    """HMAC-SHA256 of ``message`` under ``secret``, compared in constant time."""
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.credits = CreditService(db)

    async def credit_topup(
        self,
        *,
        order_id: str,
        payment_id: str,
        signature: Optional[str] = None,
        company_id: Optional[UUID] = None,
    ) -> tuple[PaymentTransaction, CreditWallet, bool]:
        """Credit the wallet for a paid top-up order.

        Returns ``(transaction, wallet, credited)``; ``credited`` is False when
        the order had already been credited (a replay, or the webhook and the
        browser callback both arriving). ``company_id`` confines the lookup to
        the caller's company. Raises :class:`PaymentNotFound` when no top-up
        order matches.
        """
        txn = await self._topup(order_id, company_id)
        if txn is None:
            raise PaymentNotFound(order_id)
        # Create the wallet first: creating one commits, which would release
        # the row lock taken below.
        await self.credits.get_or_create_wallet(txn.company_id)

        txn = await self._topup(order_id, company_id, lock=True)
        if txn is None:                                                     # pragma: no cover
            raise PaymentNotFound(order_id)
        wallet = await self.credits.lock_wallet(txn.company_id)
        if txn.status == "success":
            await self.db.commit()  # release the locks
            return txn, wallet, False

        amount = Decimal(str(txn.amount))
        txn.razorpay_payment_id = payment_id
        if signature:
            txn.razorpay_signature = signature
        txn.status = "success"
        txn.credits_awarded = amount
        self.credits.add_to_wallet_balance(wallet, amount)
        await self.db.commit()
        await self.db.refresh(wallet)
        logger.info("Top-up %s credited %s to company %s", order_id, amount, txn.company_id)
        return txn, wallet, True

    # ── Webhook ────────────────────────────────────────────────────────

    async def handle_webhook_event(self, event: dict) -> str:
        """Apply one Razorpay webhook event; returns what was done.

        Unknown events and payments that are not ours are ``"ignored"`` (still
        a 200, so Razorpay does not retry them).
        """
        kind = event.get("event") or ""
        payload = event.get("payload") or {}
        payment = (payload.get("payment") or {}).get("entity") or {}
        if kind == "payment.captured":
            return await self._on_payment_captured(payment)
        if kind == "payment.failed":
            return await self._on_payment_failed(payment)
        return "ignored"

    async def _on_payment_captured(self, payment: dict) -> str:
        order_id, payment_id = payment.get("order_id"), payment.get("id")
        if not order_id or not payment_id:
            return "ignored"
        txn = await self._topup(order_id, None)
        if txn is None:
            return "ignored"  # not a top-up order (e.g. a subscription invoice)
        paid = Decimal(str(payment.get("amount") or 0)) / 100
        if paid != Decimal(str(txn.amount)) or (payment.get("currency") or "USD") != txn.currency:
            logger.error(
                "Razorpay payment %s for order %s paid %s %s; the order is for %s %s — not credited",
                payment_id, order_id, paid, payment.get("currency"), txn.amount, txn.currency,
            )
            return "amount_mismatch"
        _, _, credited = await self.credit_topup(order_id=order_id, payment_id=payment_id)
        return "credited" if credited else "already_credited"

    async def _on_payment_failed(self, payment: dict) -> str:
        """Record a failed attempt. The order stays payable: a later
        successful payment on it is still credited."""
        order_id = payment.get("order_id")
        txn = await self._topup(order_id, None, lock=True) if order_id else None
        if txn is None:
            return "ignored"
        if txn.status == "success":
            await self.db.commit()
            return "already_credited"
        txn.status = "failed"
        txn.transaction_metadata = {
            **(txn.transaction_metadata or {}),
            "failed_payment_id": payment.get("id"),
            "error_code": payment.get("error_code"),
            "error_description": payment.get("error_description"),
        }
        await self.db.commit()
        return "recorded_failure"

    async def _topup(
        self, order_id: str, company_id: Optional[UUID], *, lock: bool = False,
    ) -> Optional[PaymentTransaction]:
        stmt = select(PaymentTransaction).where(
            PaymentTransaction.razorpay_order_id == order_id,
            PaymentTransaction.transaction_type == "topup",
        )
        if company_id is not None:
            stmt = stmt.where(PaymentTransaction.company_id == company_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()
