"""Setup and customisation fees (Phase 15 T8-8, tech design §11.5; REQ-PT-3).

* Staff set, per partner type and fee kind, the range (USD) and the split
  (``fee_rules``).
* **Gold:** the partner raises a charge for a tenant it resells — an amount in
  the tenant's currency within the range at today's rate. **Silver:** BCL
  delivers and raises it; the Silver referrer and its uplines get their split.
* The tenant's admin pays it directly (not from the wallet) with GST on top;
  BCL issues the invoice; the split is written to the partners' ledger
  (``commission.distribute`` with ``setup_fee`` / ``customisation_fee``).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from src.partners.models import FEE_KINDS, OneTimeCharge

REVENUE_OF = {"setup": "setup_fee", "customisation": "customisation_fee"}


def view(charge: OneTimeCharge, *, names: Optional[dict] = None) -> Dict[str, Any]:
    names = names or {}
    return {"id": str(charge.id), "tenant_id": str(charge.tenant_id), "tenant": names.get(charge.tenant_id),
            "partner_id": str(charge.partner_id) if charge.partner_id else None,
            "partner": names.get(charge.partner_id), "fee_kind": charge.fee_kind, "description": charge.description,
            "amount": str(charge.amount), "currency": charge.currency, "amount_usd": str(charge.amount_usd),
            "status": charge.status, "rule_version": charge.rule_version,
            "invoice_id": str(charge.invoice_id) if charge.invoice_id else None,
            "created_at": charge.created_at.isoformat() if charge.created_at else None,
            "paid_at": charge.paid_at.isoformat() if charge.paid_at else None}


async def preview(db: Any, *, partner_id: Optional[UUID], tenant_id: UUID, fee_kind: str) -> Dict[str, Any]:
    """The range in the tenant's currency and the split (the partner's share shown before raising)."""
    from src.auth.models import Company
    from src.billing.currency import current_rate, to_ccy
    from src.partners.rules import fee_rule
    from src.partners.scope import partner_type_of

    tenant = await db.get(Company, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="No such business")
    if partner_id is None:
        return {"currency": tenant.billing_currency, "min": None, "max": None, "split": None, "rule_version": None}
    rule = await fee_rule(db, await partner_type_of(db, partner_id), fee_kind)
    if rule is None:
        raise HTTPException(status_code=409, detail="No fee rule for this partner type and fee")
    rate = await current_rate(db, tenant.billing_currency)
    return {"currency": tenant.billing_currency, "min": str(to_ccy(Decimal(str(rule.min_usd)), rate)),
            "max": str(to_ccy(Decimal(str(rule.max_usd)), rate)), "min_usd": str(rule.min_usd),
            "max_usd": str(rule.max_usd), "split": rule.split, "rule_version": rule.version}


async def raise_charge(db: Any, *, actor: Any, tenant_id: UUID, fee_kind: str, amount: Decimal,
                       description: Optional[str]) -> OneTimeCharge:
    """A partner (Gold, for a tenant it resells) or staff (for any tenant) raises a charge (the caller commits)."""
    from src.auth.models import Company
    from src.billing.currency import current_rate, to_usd
    from src.notifications.service import notify
    from src.partners.lifecycle import require_active
    from src.partners.scope import partner_of, tenant_ids

    if fee_kind not in FEE_KINDS:
        raise HTTPException(status_code=422, detail="the fee is setup or customisation")
    amount = Decimal(str(amount))
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(status_code=422, detail="an amount above zero, with at most two decimals")
    tenant = await db.get(Company, tenant_id)
    if tenant is None or tenant.type != "TENANT":
        raise HTTPException(status_code=404, detail="No such business")
    staff = str(actor.role) == "app_admin"
    if staff:
        partner_id = await partner_of(db, tenant_id)
    else:
        partner_id = actor.company_id
        profile = await require_active(db, partner_id, "raise charges")
        if profile.partner_type != "GOLD":
            raise HTTPException(status_code=403, detail="A Silver partner's customers are charged by HireBuddha")
        if tenant_id not in await tenant_ids(db, partner_id, relationship="resold"):
            raise HTTPException(status_code=403, detail="Only a business you resell")
    terms = await preview(db, partner_id=partner_id, tenant_id=tenant_id, fee_kind=fee_kind)
    usd = to_usd(amount, await current_rate(db, tenant.billing_currency))
    if terms["min_usd"] is not None and not Decimal(terms["min_usd"]) <= usd <= Decimal(terms["max_usd"]):
        raise HTTPException(status_code=422, detail=f"a {fee_kind} fee is between {tenant.billing_currency} "
                                                    f"{Decimal(terms['min']):,.2f} and {Decimal(terms['max']):,.2f}")
    charge = OneTimeCharge(tenant_id=tenant_id, partner_id=partner_id, fee_kind=fee_kind, description=description,
                           amount=amount, currency=tenant.billing_currency, amount_usd=usd, status="sent",
                           rule_version=terms["rule_version"], raised_by=actor.id)
    db.add(charge)
    await db.flush()
    await notify(tenant_id, kind="billing.charge", title=f"A {fee_kind} fee of {tenant.billing_currency} "
                 f"{amount:,.2f} is ready to pay", body=description, link="/billing/charges", severity="info",
                 dedupe_key=f"charge:{charge.id}")
    return charge


async def cancel(db: Any, charge: OneTimeCharge, *, actor: Any) -> OneTimeCharge:
    if charge.status not in ("draft", "sent"):
        raise HTTPException(status_code=409, detail=f"the charge is {charge.status}")
    if str(actor.role) != "app_admin" and charge.partner_id != actor.company_id:
        raise HTTPException(status_code=403, detail="Not your charge")
    charge.status = "cancelled"
    return charge


async def start_payment(db: Any, gateway: Any, charge: OneTimeCharge) -> Dict[str, Any]:
    from src.auth.models import Company
    from src.partners.payments import create_order

    if charge.status != "sent":
        raise HTTPException(status_code=409, detail=f"the charge is {charge.status}")
    tenant = await db.get(Company, charge.tenant_id)
    if tenant.billing_currency != charge.currency:
        raise HTTPException(status_code=409, detail="The business's currency changed: ask for a new charge")
    return await create_order(db, gateway, company=tenant, net=Decimal(str(charge.amount)),
                              purpose="one_time_charge", description=charge.description or
                              f"{charge.fee_kind.capitalize()} fee",
                              metadata={"charge_id": str(charge.id), "revenue_kind": REVENUE_OF[charge.fee_kind]})


async def on_charge_paid(db: Any, payment: Any, *, invoice_id: Any) -> None:
    """The order paid: the charge is paid (the caller commits; the split follows in ``payments``)."""
    charge_id = (payment.transaction_metadata or {}).get("charge_id")
    charge = await db.get(OneTimeCharge, UUID(charge_id)) if charge_id else None
    if charge is None:
        return
    charge.status, charge.payment_id, charge.invoice_id, charge.paid_at = ("paid", payment.id, invoice_id,
                                                                          datetime.utcnow())


async def for_tenant(db: Any, tenant_id: UUID) -> list:
    return list((await db.execute(select(OneTimeCharge).where(OneTimeCharge.tenant_id == tenant_id)
                                  .order_by(OneTimeCharge.created_at.desc()))).scalars().all())
