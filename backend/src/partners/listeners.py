"""The programme's billing listeners (``src.billing.hooks``): a refund claws back commission (T8-7)
and marks a fully refunded setup or customisation fee (T8-8)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.billing.hooks import on_refund


@on_refund
async def clawback_commission(db: Any, payment: Any, refund: Any) -> None:
    from src.partners.commission import on_refund as clawback

    await clawback(db, payment, refund)


@on_refund
async def charge_refunded(db: Any, payment: Any, refund: Any) -> None:
    from sqlalchemy import select

    from src.partners.models import OneTimeCharge

    if payment.purpose != "one_time_charge":
        return
    if Decimal(str(payment.refunded_gross or 0)) < Decimal(str(payment.gross_amount or payment.amount)):
        return
    charge = (await db.execute(select(OneTimeCharge).where(OneTimeCharge.payment_id == payment.id))
              ).scalar_one_or_none()
    if charge is not None and charge.status == "paid":
        charge.status = "refunded"
        await db.commit()
