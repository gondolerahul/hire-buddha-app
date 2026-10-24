"""
Payment Service — turns a verified Razorpay payment into credits, exactly once.

The browser callbacks (``POST /credits/topup/verify``,
``POST /credits/subscriptions/verify``), the server-to-server webhook and the
subscription reconciliation job all land here, so a payment is credited by
whichever arrives first and ignored by the others. A top-up credits the amount
stored when the order was created — never one supplied by the caller (BC-01).
A subscription grants a cycle's credits only for a Razorpay payment on it
(BC-03, BC-04), once per payment id.
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing.billing_models import CreditWallet, PaymentTransaction, Subscription
from src.billing.credit_service import CreditService

logger = logging.getLogger(__name__)


class PaymentNotFound(LookupError):
    """No pending transaction matches the payment."""


# Razorpay subscription status -> ours. Unlisted statuses leave ours unchanged.
RAZORPAY_SUBSCRIPTION_STATUS = {
    "authenticated": "active",
    "active": "active",
    "pending": "past_due",    # a charge failed; Razorpay is retrying
    "halted": "past_due",     # every retry failed
    "paused": "paused",
    "cancelled": "cancelled",
    "completed": "cancelled",
    "expired": "cancelled",
}
LIVE_SUBSCRIPTION_STATUSES = ("active", "past_due", "paused")


def razorpay_time(value) -> Optional[datetime]:
    """A Razorpay unix timestamp as a naive UTC datetime (the columns are naive)."""
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)


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
        from src.billing.enforcement import wallet_changed

        txn = await self._topup(order_id, company_id, lock=True)
        if txn is None:                                                     # pragma: no cover
            raise PaymentNotFound(order_id)
        wallet = await self.credits.lock_wallet(txn.company_id)
        if txn.status == "success":
            await self.db.commit()  # release the locks
            return txn, wallet, False

        # The credit is what was paid net of GST (T6-5), in the wallet's
        # currency: the order's own currency (an order placed before the wallet
        # cutover was in USD) converted at the rate in effect now. An order
        # placed before GST carried none: all of it is credit, and it has no invoice.
        net = Decimal(str(txn.net_amount if txn.net_amount is not None else txn.amount))
        amount = await self._in_wallet_currency(net, txn.currency, wallet.currency)
        txn.razorpay_payment_id = payment_id
        if signature:
            txn.razorpay_signature = signature
        txn.status = "success"
        txn.credits_awarded = amount
        change = await self.credits.add_wallet_credits(txn.company_id, amount, source_type="payment",
                                                       source_id=order_id, commit=False)
        invoice_id = await self._invoice_topup(txn)
        await self.db.commit()
        await self.db.refresh(wallet)
        if invoice_id is not None:
            from src.billing.invoices import store_pdf
            await store_pdf(self.db, invoice_id)
            await self.db.refresh(wallet)
        logger.info("Top-up %s credited %s %s to company %s (debt repaid %s)", order_id, amount, wallet.currency,
                    txn.company_id, change.debt_repaid)
        await wallet_changed(self.db, txn.company_id, change)
        # The tenant's partners earn on the cash it paid (Phase 15 T8-7); never fails the top-up.
        from src.partners.commission import on_payment
        await on_payment(self.db, txn, revenue_kind="usage_topup")
        return txn, wallet, True

    async def _invoice_topup(self, txn: PaymentTransaction) -> Optional[UUID]:
        """The tax invoice of a top-up paid with GST (TX-3); none for an order placed before GST."""
        if txn.net_amount is None or txn.gross_amount is None or txn.invoice_id is not None:
            return None
        from src.auth.models import Company
        from src.billing.invoices import issue_invoice
        from src.billing.tax import TaxedAmount, apply, tax_for

        company = await self.db.get(Company, txn.company_id)
        tax = await tax_for(self.db, company)
        split = apply(Decimal(str(txn.net_amount)), tax)       # the CGST / SGST / IGST split of what was charged
        taxed = TaxedAmount(Decimal(str(txn.net_amount)), split.cgst, split.sgst, split.igst,
                            Decimal(str(txn.tax_amount or 0)), Decimal(str(txn.gross_amount)), tax.regime, tax.rate)
        invoice = await issue_invoice(self.db, payment=txn, company=company, taxed=taxed, currency=txn.currency,
                                      lines=[("Wallet recharge (prepaid credit)", taxed.net)])
        return invoice.id

    async def _in_wallet_currency(self, amount: Decimal, currency: Optional[str], wallet_currency: str) -> Decimal:
        from src.billing.currency import current_rate, to_ccy, to_usd

        currency = (currency or "USD").upper()
        if currency == wallet_currency:
            return amount
        usd = to_usd(amount, await current_rate(self.db, currency))
        return to_ccy(usd, await current_rate(self.db, wallet_currency))

    # ── Webhook ────────────────────────────────────────────────────────

    async def handle_webhook_event(self, event: dict) -> str:
        """Apply one Razorpay webhook event; returns what was done.

        Unknown events and payments that are not ours are ``"ignored"`` (still
        a 200, so Razorpay does not retry them).
        """
        kind = event.get("event") or ""
        payload = event.get("payload") or {}
        payment = (payload.get("payment") or {}).get("entity") or {}
        rz_sub = (payload.get("subscription") or {}).get("entity") or {}
        if kind == "payment.captured":
            return await self._on_payment_captured(payment)
        if kind == "payment.failed":
            return await self._on_payment_failed(payment)
        if kind.startswith("subscription.") and rz_sub.get("id"):
            return await self._on_subscription_event(kind, rz_sub, payment)
        return "ignored"

    async def _on_subscription_event(self, kind: str, rz_sub: dict, payment: dict) -> str:
        sub = await self.subscription_by_razorpay_id(rz_sub["id"])
        if sub is None:
            return "ignored"
        if kind == "subscription.charged":
            if not payment.get("id"):
                return "ignored"
            from src.billing.currency import minor_units
            currency = (payment.get("currency") or sub.currency or "USD").upper()
            credited = await self.record_subscription_charge(
                sub,
                payment_id=payment["id"],
                amount=Decimal(str(payment.get("amount") or 0)) / (Decimal(10) ** await minor_units(self.db, currency)),
                cycle_end=razorpay_time(rz_sub.get("current_end")),
            )
            return "credited" if credited else "already_credited"
        status = RAZORPAY_SUBSCRIPTION_STATUS.get(rz_sub.get("status") or "")
        if status is None:
            return "ignored"
        await self.set_subscription_status(sub, status)
        return f"status_{status}"

    async def _on_payment_captured(self, payment: dict) -> str:
        order_id, payment_id = payment.get("order_id"), payment.get("id")
        if not order_id or not payment_id:
            return "ignored"
        txn = await self._topup(order_id, None)
        if txn is None:
            # A partnership fee or a setup / customisation fee (Phase 15 T8-6, T8-8), else not ours.
            from src.partners.payments import on_captured
            return await on_captured(self.db, payment) or "ignored"
        from src.billing.currency import minor_units
        currency = (txn.currency or "USD").upper()
        paid = Decimal(str(payment.get("amount") or 0)) / (Decimal(10) ** await minor_units(self.db, currency))
        if paid != Decimal(str(txn.amount)) or (payment.get("currency") or "USD").upper() != currency:
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

    # ── Subscriptions ──────────────────────────────────────────────────

    async def subscription_by_razorpay_id(
        self, razorpay_subscription_id: str, company_id: Optional[UUID] = None,
    ) -> Optional[Subscription]:
        stmt = select(Subscription).where(
            Subscription.razorpay_subscription_id == razorpay_subscription_id)
        if company_id is not None:
            stmt = stmt.where(Subscription.company_id == company_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def record_subscription_charge(
        self,
        sub: Subscription,
        *,
        payment_id: str,
        amount: Decimal,
        cycle_end: Optional[datetime] = None,
    ) -> bool:
        """One subscription payment (``amount`` is what it paid, GST included):
        credited once per payment id, with its invoice (``src.billing.subscriptions``)."""
        from src.billing.subscriptions import record_charge

        return await record_charge(self.db, sub, payment_id=payment_id, gross=amount, cycle_end=cycle_end)

    async def set_subscription_status(self, sub: Subscription, status: str) -> None:
        """Move ``sub`` to ``status``. A company left with no live subscription
        is labelled pay-as-you-go again; paid-for credits stay until they expire."""
        if sub.status == status:
            return
        now = datetime.utcnow()
        sub.status = status
        sub.updated_at = now
        from src.billing.plans import forget
        forget(sub.company_id)
        if status == "cancelled":
            sub.cancelled_at = sub.cancelled_at or now
            live = await self.db.execute(select(Subscription.id).where(
                Subscription.company_id == sub.company_id,
                Subscription.id != sub.id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            ))
            if live.first() is None:
                wallet = (await self.db.execute(select(CreditWallet).where(
                    CreditWallet.company_id == sub.company_id))).scalar_one_or_none()
                if wallet is not None:
                    wallet.account_model = "pay_as_you_go"
        await self.db.commit()

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
