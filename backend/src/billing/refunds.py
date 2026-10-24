"""Refunds, for staff (Phase 15 T6-6, tech design §12.2).

A refund of a captured payment, all of it or a part (the net amount to give
back; its GST follows at the invoice's rate):

1. the gateway refunds the gross part;
2. the credit the payment granted is taken back — from the lot it granted
   first, then from other credit, and what is no longer there becomes debt
   (W-1: value never leaves without a trace);
3. a credit note is issued against the payment's invoice (TX-7);
4. listeners are told (the partner programme's clawback, ``src.billing.hooks``).

Audited (``admin_audit_log``). A payment cannot be refunded beyond what it paid.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import or_, select

logger = logging.getLogger(__name__)


class RefundProblem(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


async def refund_payment(db: Any, gateway: Any, payment: Any, *, net: Optional[Decimal], reason: str,
                         actor: Any) -> Any:
    """Refund ``net`` (default: what is left) of ``payment``. Commits; returns the ``Refund``."""
    from src.billing.billing_models import Invoice, Refund, WalletLot
    from src.billing.currency import minor_units
    from src.billing.enforcement import wallet_changed
    from src.billing.hooks import refunded
    from src.billing.invoices import issue_credit_note
    from src.billing.tax import Tax, apply
    from src.billing.wallet import WalletService
    from src.common.admin_audit import record_admin_change

    if payment.status != "success" or not payment.razorpay_payment_id:
        raise RefundProblem("only a captured payment can be refunded")
    if not reason or len(reason.strip()) < 3:
        raise RefundProblem("a refund needs a reason", 422)
    currency = payment.currency
    digits = await minor_units(db, currency)
    paid_net = Decimal(str(payment.net_amount if payment.net_amount is not None else payment.amount))
    paid_gross = Decimal(str(payment.gross_amount if payment.gross_amount is not None else payment.amount))
    refunded_gross = Decimal(str(payment.refunded_gross or 0))
    invoice = await db.get(Invoice, payment.invoice_id) if payment.invoice_id else None
    tax = Tax(invoice.regime, Decimal(str(invoice.tax_rate)), invoice.place_of_supply, "") if invoice \
        else Tax("export", Decimal(0), None, "")
    left_net = paid_net - (refunded_gross * paid_net / paid_gross if paid_gross else Decimal(0))
    net = Decimal(str(net)) if net is not None else left_net
    taxed = apply(net, tax, digits)
    if net <= 0 or taxed.gross > paid_gross - refunded_gross + Decimal("0.01"):
        raise RefundProblem(f"at most {currency} {paid_gross - refunded_gross:,.2f} of this payment is left to refund",
                            422)
    result = await gateway.refund(payment.razorpay_payment_id, taxed.gross, currency,
                                  notes={"payment": str(payment.id), "reason": reason[:200]})
    # The credit the payment granted is in the wallet's currency (credits_awarded); refund it in proportion.
    awarded = Decimal(str(payment.credits_awarded or paid_net))
    credit = awarded * taxed.net / paid_net if paid_net else Decimal(0)
    source = payment.razorpay_order_id or payment.razorpay_payment_id
    lot_id = (await db.execute(select(WalletLot.id).where(
        WalletLot.company_id == payment.company_id, WalletLot.kind.in_(("topup", "subscription")),
        or_(WalletLot.source_id == source, WalletLot.source_id == payment.razorpay_payment_id))
        .order_by(WalletLot.granted_at.desc()).limit(1))).scalar_one_or_none()
    change = await WalletService(db).take_back(payment.company_id, credit, lot_id=lot_id,
                                               reason=f"refund: {reason}", source_id=str(payment.id),
                                               actor_id=getattr(actor, "id", None))
    note = await issue_credit_note(db, invoice=invoice, taxed=taxed, reason=reason) if invoice else None
    refund = Refund(payment_id=payment.id, company_id=payment.company_id, currency=currency, gross=taxed.gross,
                    net=taxed.net, credit_taken=credit - change.debt_added, debt_added=change.debt_added,
                    gateway_refund_id=result.get("id"), credit_note_id=note.id if note else None, reason=reason,
                    actor_id=getattr(actor, "id", None))
    db.add(refund)
    payment.refunded_gross = refunded_gross + taxed.gross
    record_admin_change(db, actor=actor, action="refund", object_type="payment", object_key=str(payment.id),
                        target_company_id=payment.company_id,
                        new_value={"gross": str(taxed.gross), "net": str(taxed.net), "currency": currency,
                                   "credit_taken": str(credit), "debt_added": str(change.debt_added),
                                   "credit_note": note.number if note else None}, reason=reason)
    await db.commit()
    await wallet_changed(db, payment.company_id, change)
    await refunded(db, payment, refund)
    logger.info("payment %s refunded %s %s (%s)", payment.id, taxed.gross, currency, reason)
    return refund
