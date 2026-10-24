"""GST on what a company pays (Phase 15 T6-4, tech design §11; TX-1, TX-2).

GST is added on top of a net price (tax-exclusive). Within HireBuddha's state
it is CGST + SGST, half each; across states IGST; outside India an export,
zero-rated under the LUT. A gross amount already paid (a subscription charge)
is split back into net and tax, any paisa of rounding going to the tax.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.billing import tax as tax_mod
from src.billing.invoices import financial_year
from src.billing.tax import EXPORT, INTER, INTRA, Tax, apply, net_of

D = Decimal


def _tax(regime, rate="18"):
    return Tax(regime, D(rate), "KA", "KA")


@pytest.fixture
def settings(monkeypatch):
    values = {"tax.gst_rate": D("18"), "tax.supplier_state": "KA"}

    async def _value(db, key, *a, **k):
        return values[key]

    monkeypatch.setattr("src.billing.settings_catalogue.value", _value)
    return values


@pytest.mark.asyncio
async def test_the_regime_follows_where_the_company_is(settings):
    same = await tax_mod.tax_for(None, SimpleNamespace(country_code="IN", billing_state="KA"))
    other = await tax_mod.tax_for(None, SimpleNamespace(country_code="IN", billing_state="MH"))
    abroad = await tax_mod.tax_for(None, SimpleNamespace(country_code="US", billing_state=None))
    unknown = await tax_mod.tax_for(None, SimpleNamespace(country_code="IN", billing_state=None))
    assert (same.regime, same.rate) == (INTRA, D(18))
    assert (other.regime, other.rate, other.place_of_supply) == (INTER, D(18), "MH")
    assert (abroad.regime, abroad.rate) == (EXPORT, D(0))
    assert unknown.regime == INTRA                    # no state yet: the supplier's


def test_a_thousand_rupees_within_the_state_is_ninety_and_ninety():
    taxed = apply(D("1000"), _tax(INTRA))
    assert (taxed.net, taxed.cgst, taxed.sgst, taxed.igst, taxed.gross) == (D(1000), D(90), D(90), 0, D(1180))


def test_across_states_it_is_igst():
    taxed = apply(D("1000"), _tax(INTER))
    assert (taxed.cgst, taxed.sgst, taxed.igst, taxed.tax, taxed.gross) == (0, 0, D(180), D(180), D(1180))


def test_an_export_is_zero_rated():
    taxed = apply(D("49.99"), Tax(EXPORT, D(0), None, "KA"))
    assert (taxed.tax, taxed.gross) == (0, D("49.99"))


def test_an_odd_paisa_of_cgst_goes_to_sgst():
    taxed = apply(D("0.05"), _tax(INTRA))             # 18% = 0.009 -> 0.01 in all
    assert taxed.tax == D("0.01") and taxed.cgst + taxed.sgst == taxed.tax


@pytest.mark.parametrize("gross", ["1180", "1179.99", "99", "0.01", "354"])
def test_a_gross_payment_splits_back_exactly(gross):
    taxed = net_of(D(gross), _tax(INTRA))
    assert taxed.gross == D(gross)
    assert taxed.net + taxed.tax == D(gross)
    assert taxed.cgst + taxed.sgst == taxed.tax


def test_the_financial_year_runs_april_to_march():
    assert financial_year(datetime(2026, 4, 1)) == "2026-27"
    assert financial_year(datetime(2027, 3, 31, 23, 59)) == "2026-27"
    assert financial_year(datetime(2027, 4, 1)) == "2027-28"
    assert financial_year(datetime(2099, 12, 1)) == "2099-00"


def test_the_pdf_writer_makes_a_pdf():
    from src.billing.pdf import Document

    doc = Document("Tax invoice")
    page = doc.page()
    page.text(50, 800, "Tax invoice HB/2026-27/000001", size=14, bold=True)
    page.right(545, 780, "INR 1,180.00")
    page.line(50, 770, 545, 770)
    data = doc.to_bytes()
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert b"HB/2026-27/000001" in data
