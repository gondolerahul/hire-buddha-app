"""One-off orders outside the wallet: the annual partnership fee and setup / customisation fees (T8-6, T8-8).

Both are paid directly (not from the wallet), with GST on top (tax-exclusive,
TX-1) and a tax invoice (TX-3), through the payment gateway: an order, then
the Checkout callback (``record_paid``) or the ``payment.captured`` webhook
(``on_captured``) — whichever comes first records it, once.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

logger = logging.getLogger(__name__)

PURPOSES = ("partner_fee", "one_time_charge")


async def create_order(db: Any, gateway: Any, *, company: Any, net: Decimal, purpose: str, description: str,
                       metadata: Dict[str, Any]) -> Dict[str, Any]:
    """A gateway order for ``net`` + GST, recorded as a pending payment. Commits."""
    from src.billing.billing_models import PaymentTransaction
    from src.billing.currency import minor_units
    from src.billing.tax import apply, tax_for

    currency = company.billing_currency
    taxed = apply(Decimal(str(net)), await tax_for(db, company), await minor_units(db, currency))
    order = await gateway.create_order(taxed.gross, currency, receipt=f"{purpose[:7]}_{uuid.uuid4().hex[:20]}",
                                       notes={"company_id": str(company.id), "purpose": purpose})
    db.add(PaymentTransaction(company_id=company.id, razorpay_order_id=order["id"], amount=taxed.gross,
                              currency=currency, transaction_type=purpose, purpose=purpose, status="pending",
                              net_amount=taxed.net, tax_amount=taxed.tax, gross_amount=taxed.gross,
                              transaction_metadata={**metadata, "description": description}))
    await db.commit()
    return {"order_id": order["id"], "amount": str(taxed.gross), "net": str(taxed.net), "tax": str(taxed.tax),
            "tax_rate": str(taxed.rate), "currency": currency, "key_id": gateway.key_id, "description": description}


async def _order(db: Any, order_id: str, company_id: Optional[UUID], *, lock: bool = False) -> Any:
    from src.billing.billing_models import PaymentTransaction

    query = select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == order_id,
                                             PaymentTransaction.purpose.in_(PURPOSES))
    if company_id is not None:
        query = query.where(PaymentTransaction.company_id == company_id)
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def record_paid(db: Any, *, order_id: str, payment_id: str, signature: Optional[str] = None,
                      company_id: Optional[UUID] = None) -> tuple[Any, bool]:
    """Record the order paid, once: its invoice, then what it was for. Commits. ``(payment, recorded)``."""
    from src.auth.models import Company
    from src.billing.invoices import issue_invoice, store_pdf
    from src.billing.tax import TaxedAmount, apply, tax_for

    payment = await _order(db, order_id, company_id, lock=True)
    if payment is None:
        raise HTTPException(status_code=404, detail="No such order")
    if payment.status == "success":
        await db.commit()
        return payment, False
    payment.status, payment.razorpay_payment_id = "success", payment_id
    if signature:
        payment.razorpay_signature = signature
    company = await db.get(Company, payment.company_id)
    split = apply(Decimal(str(payment.net_amount)), await tax_for(db, company))
    taxed = TaxedAmount(Decimal(str(payment.net_amount)), split.cgst, split.sgst, split.igst,
                        Decimal(str(payment.tax_amount or 0)), Decimal(str(payment.gross_amount)), split.regime,
                        split.rate)
    description = (payment.transaction_metadata or {}).get("description") or payment.purpose
    invoice = await issue_invoice(db, payment=payment, company=company, taxed=taxed, currency=payment.currency,
                                  lines=[(description, taxed.net)])
    if payment.purpose == "partner_fee":
        from src.partners.fees import on_fee_paid
        await on_fee_paid(db, payment)
    else:
        from src.partners.charges import on_charge_paid
        await on_charge_paid(db, payment, invoice_id=invoice.id)
    invoice_id = invoice.id
    await db.commit()
    await store_pdf(db, invoice_id)
    if payment.purpose == "one_time_charge":
        from src.partners.commission import on_payment
        await on_payment(db, payment, revenue_kind=(payment.transaction_metadata or {}).get("revenue_kind"))
    return payment, True


async def on_captured(db: Any, payment: Dict[str, Any]) -> Optional[str]:
    """The webhook's ``payment.captured`` for a partner fee or a charge; ``None`` when the order is neither."""
    from src.billing.currency import minor_units

    order_id, payment_id = payment.get("order_id"), payment.get("id")
    txn = await _order(db, order_id, None) if order_id else None
    if txn is None or not payment_id:
        return None
    paid = Decimal(str(payment.get("amount") or 0)) / (Decimal(10) ** await minor_units(db, txn.currency))
    if paid != Decimal(str(txn.amount)) or (payment.get("currency") or "").upper() != txn.currency:
        logger.error("payment %s for order %s paid %s %s; the order is for %s %s — not recorded",
                     payment_id, order_id, paid, payment.get("currency"), txn.amount, txn.currency)
        return "amount_mismatch"
    _, recorded = await record_paid(db, order_id=order_id, payment_id=payment_id)
    return "recorded" if recorded else "already_recorded"
