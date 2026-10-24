"""GST on payments (Phase 15 T6-5, tech design §12.3, Q8).

Prices are tax-exclusive (TX-1, O-6): what a company pays is the net amount
plus GST. The tax follows the place of supply (TX-2):

* a company in India whose billing state is the supplier's (``tax.supplier_state``)
  — CGST + SGST, half of ``tax.gst_rate`` each;
* a company in India in another state — IGST at ``tax.gst_rate``;
* a company in India with no billing state — the supplier's state (a B2C
  service with no recipient address is supplied where the supplier is);
* a company outside India — an export of services, zero-rated under the LUT
  (``tax.lut_number``).

GST is charged when money is received (TX-3): one tax invoice per payment;
wallet consumption is not invoiced again. Tax amounts are rounded to the
currency's minor unit, half up — an invoice is a payment document (K-1).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

INTRA, INTER, EXPORT = "intra_state", "inter_state", "export"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Tax:
    regime: str                  # intra_state | inter_state | export
    rate: Decimal                # % of the net amount
    place_of_supply: Optional[str]
    supplier_state: str


@dataclass(frozen=True)
class TaxedAmount:
    net: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    tax: Decimal
    gross: Decimal
    regime: str
    rate: Decimal


async def tax_for(db: Any, company: Any) -> Tax:
    """The tax on what ``company`` pays (TX-2)."""
    from src.billing.settings_catalogue import value

    rate = Decimal(str(await value(db, "tax.gst_rate")))
    supplier = str(await value(db, "tax.supplier_state") or "").upper()
    country = (getattr(company, "country_code", None) or "IN").upper()
    if country != "IN":
        return Tax(EXPORT, ZERO, None, supplier)
    state = (getattr(company, "billing_state", None) or supplier or "").upper()
    return Tax(INTRA if state == supplier else INTER, rate, state or None, supplier)


def _round(amount: Decimal, digits: int) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def apply(net: Decimal, tax: Tax, digits: int = 2) -> TaxedAmount:
    """``net`` (rounded to the minor unit) with its GST split by ``tax``."""
    net = _round(Decimal(str(net)), digits)
    total = _round(net * tax.rate / Decimal(100), digits)
    cgst = sgst = igst = ZERO
    if tax.regime == INTRA:
        cgst = _round(total / 2, digits)
        sgst = total - cgst
    elif tax.regime == INTER:
        igst = total
    return TaxedAmount(net, cgst, sgst, igst, total, net + total, tax.regime, tax.rate)


def net_of(gross: Decimal, tax: Tax, digits: int = 2) -> TaxedAmount:
    """The split of a ``gross`` amount already paid (a subscription charge, a webhook's amount)."""
    gross = _round(Decimal(str(gross)), digits)
    if tax.rate == 0:
        return apply(gross, tax, digits)
    net = _round(gross * Decimal(100) / (Decimal(100) + tax.rate), digits)
    taxed = apply(net, tax, digits)
    if taxed.gross != gross:                      # a paisa of rounding: the tax takes it
        diff = gross - taxed.gross
        if tax.regime == INTRA:
            taxed = TaxedAmount(net, taxed.cgst, taxed.sgst + diff, ZERO, taxed.tax + diff, gross, tax.regime, tax.rate)
        else:
            taxed = TaxedAmount(net, ZERO, ZERO, taxed.igst + diff, taxed.tax + diff, gross, tax.regime, tax.rate)
    return taxed
