"""Top-ups with GST, tax invoices and refunds (Phase 15 T6-4…T6-6, tech design §11). Real Postgres, rolled back.

* A top-up's amount is the credit (net); the order charges net + GST; the
  wallet is credited the net, and one invoice is issued, numbered in the
  financial year's gap-free series (HB/2026-27/000123).
* A refund is of a net amount: the gateway refunds it with its GST, the credit
  it bought is taken back (into debt when already spent), and a credit note is
  issued against the invoice. More than is left is refused.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from src.auth.models import Company
from src.auth.roles import Role
from src.billing.billing_models import CreditNote, CreditWallet, Invoice, InvoiceLine, PaymentTransaction, Refund
from tests.harness.wallet import available
from tests.integration.test_subscriptions import CREDS, KEY_SECRET, FakeRazorpay

pytestmark = pytest.mark.needs_db


@pytest.fixture
def rzp(monkeypatch):
    from src.billing.gateways import razorpay as gateway_module

    fake = FakeRazorpay()

    async def _creds(_db):
        return CREDS

    monkeypatch.setattr(gateway_module, "get_razorpay_creds", _creds)
    monkeypatch.setattr(gateway_module, "razorpay_client", lambda creds: fake)
    return fake


def _user(role, company_id=None):
    return SimpleNamespace(id=uuid.uuid4(), role=Role(role), company_id=company_id or uuid.uuid4())


def _app(db, user) -> FastAPI:
    from src.auth import dependencies, router as auth_router
    from src.billing import credits_router, invoices_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_control_db

    app = FastAPI()
    app.include_router(credits_router.router)
    app.include_router(invoices_router.router)

    async def _u():
        return user

    async def _db():
        yield db

    for dep in (dependencies.get_current_user, auth_router.get_current_user):
        app.dependency_overrides[dep] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    return app


async def _call(db, user, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, user)), base_url="http://t") as c:
        return await c.request(method, path, **kw)


async def _company(db, state="KA", country="IN", currency="INR"):
    c = Company(name=f"inv-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency,
                country_code=country, billing_state=state, gstin="29ABCDE1234F1Z5" if state == "KA" else None)
    db.add(c)
    await db.flush()
    return c.id


async def _top_up(db, rzp, company, amount="1000", payment_id=None):
    admin = _user("tenant_admin", company)
    order = await _call(db, admin, "POST", "/api/v1/credits/topup", json={"amount": amount})
    assert order.status_code == 200, order.text
    body = order.json()
    payment_id = payment_id or f"pay_{uuid.uuid4().hex[:10]}"
    sig = hmac.new(KEY_SECRET.encode(), f"{body['order_id']}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    verified = await _call(db, admin, "POST", "/api/v1/credits/topup/verify", json={
        "razorpay_order_id": body["order_id"], "razorpay_payment_id": payment_id, "razorpay_signature": sig})
    assert verified.status_code == 200, verified.text
    return body, verified.json()


@pytest.mark.asyncio
async def test_a_top_up_charges_gst_on_top_and_credits_the_net(db, rzp):
    company = await _company(db)
    order, verified = await _top_up(db, rzp, company, "1000")
    assert (Decimal(order["net"]), Decimal(order["tax"]), Decimal(order["amount"])) == (1000, 180, 1180)
    assert rzp.orders[-1]["amount"] == 118000 and rzp.orders[-1]["currency"] == "INR"
    assert Decimal(verified["credits_added"]) == Decimal(1000)
    assert await available(db, company) == Decimal(1000)
    invoice = await db.get(Invoice, uuid.UUID(verified["invoice_id"]))
    assert (invoice.net, invoice.cgst, invoice.sgst, invoice.igst, invoice.total) == (1000, 90, 90, 0, 1180)
    assert re.fullmatch(r"HB/\d{4}-\d{2}/\d{6}", invoice.number)
    lines = (await db.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))).scalars().all()
    assert len(lines) == 1 and lines[0].amount == Decimal(1000)


@pytest.mark.asyncio
async def test_another_state_pays_igst(db, rzp):
    company = await _company(db, state="MH")
    _, verified = await _top_up(db, rzp, company, "500.00")
    invoice = await db.get(Invoice, uuid.UUID(verified["invoice_id"]))
    assert (invoice.regime, invoice.igst, invoice.cgst, invoice.place_of_supply) == ("inter_state", 90, 0, "MH")


@pytest.mark.asyncio
async def test_an_export_is_zero_rated(db, rzp):
    company = await _company(db, state=None, country="US", currency="USD")
    order, verified = await _top_up(db, rzp, company, "50")
    assert Decimal(order["tax"]) == 0 and Decimal(order["amount"]) == 50
    invoice = await db.get(Invoice, uuid.UUID(verified["invoice_id"]))
    assert (invoice.regime, invoice.tax, invoice.currency) == ("export", 0, "USD")


@pytest.mark.asyncio
async def test_invoice_numbers_run_without_gaps(db, rzp):
    company = await _company(db)
    numbers = []
    for _ in range(3):
        _, verified = await _top_up(db, rzp, company, "600")
        numbers.append((await db.get(Invoice, uuid.UUID(verified["invoice_id"]))).number)
    seq = [int(n.rsplit("/", 1)[1]) for n in numbers]
    assert seq == [seq[0], seq[0] + 1, seq[0] + 2]
    assert len({n.rsplit("/", 1)[0] for n in numbers}) == 1


@pytest.mark.asyncio
async def test_verifying_twice_issues_one_invoice(db, rzp):
    company = await _company(db)
    order, verified = await _top_up(db, rzp, company, "600", payment_id="pay_twice")
    sig = hmac.new(KEY_SECRET.encode(), f"{order['order_id']}|pay_twice".encode(), hashlib.sha256).hexdigest()
    again = await _call(db, _user("tenant_admin", company), "POST", "/api/v1/credits/topup/verify", json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_twice", "razorpay_signature": sig})
    assert again.json()["credits_added"] == "0"
    invoices = (await db.execute(select(Invoice).where(Invoice.company_id == company))).scalars().all()
    assert len(invoices) == 1


@pytest.mark.asyncio
async def test_the_company_lists_its_invoices_and_gets_the_pdf(db, rzp):
    company = await _company(db)
    _, verified = await _top_up(db, rzp, company, "600")
    user = _user("tenant_user", company)
    listed = (await _call(db, user, "GET", "/api/v1/billing/invoices")).json()
    assert [i["id"] for i in listed["invoices"]] == [verified["invoice_id"]]
    pdf = await _call(db, user, "GET", f"/api/v1/billing/invoices/{verified['invoice_id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other = _user("tenant_user", await _company(db))
    assert (await _call(db, other, "GET", f"/api/v1/billing/invoices/{verified['invoice_id']}/pdf")).status_code == 404


@pytest.mark.asyncio
async def test_the_billing_profile_validates_the_gstin(db, rzp):
    company = await _company(db)
    admin = _user("tenant_admin", company)
    bad = await _call(db, admin, "PUT", "/api/v1/billing/profile", json={"gstin": "not-a-gstin"})
    good = await _call(db, admin, "PUT", "/api/v1/billing/profile",
                       json={"gstin": "27ABCDE1234F1Z5", "billing_state": "MH", "legal_name": "Acme Pvt Ltd"})
    assert bad.status_code == 422
    assert good.status_code == 200 and good.json()["billing_state"] == "MH"
    viewer = await _call(db, _user("tenant_user", company), "PUT", "/api/v1/billing/profile", json={"legal_name": "x"})
    assert viewer.status_code == 403


async def _payment(db, verified):
    invoice = await db.get(Invoice, uuid.UUID(verified["invoice_id"]))
    return await db.get(PaymentTransaction, invoice.payment_id)


@pytest.mark.asyncio
async def test_a_partial_refund_takes_back_its_credit_and_issues_a_credit_note(db, rzp):
    company = await _company(db)
    _, verified = await _top_up(db, rzp, company, "1000")
    payment = await _payment(db, verified)
    res = await _call(db, _user("app_admin"), "POST", f"/api/v1/admin/payments/{payment.id}/refund",
                      json={"net": "400", "reason": "test: unused credit"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (Decimal(body["net"]), Decimal(body["gross"]), Decimal(body["credit_taken"])) == (400, 472, 400)
    assert rzp.refunds[-1] == (payment.razorpay_payment_id, {"amount": 47200, "notes": rzp.refunds[-1][1]["notes"]})
    assert await available(db, company) == Decimal(600)
    note = await db.get(CreditNote, uuid.UUID(body["credit_note_id"]))
    assert note.number.startswith("HB-CN/") and note.total == Decimal(472)
    await db.refresh(payment)
    assert payment.refunded_gross == Decimal(472)


@pytest.mark.asyncio
async def test_a_refund_of_spent_credit_becomes_debt(db, rzp):
    from src.billing.wallet import WalletService

    company = await _company(db)
    _, verified = await _top_up(db, rzp, company, "1000")
    await WalletService(db).deduct(company, Decimal("900"), source_type="test")
    await db.commit()
    payment = await _payment(db, verified)
    res = await _call(db, _user("app_admin"), "POST", f"/api/v1/admin/payments/{payment.id}/refund",
                      json={"reason": "test: refund everything"})
    assert res.status_code == 200, res.text
    assert Decimal(res.json()["debt_added"]) == Decimal(900)
    wallet = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == company)
                               .execution_options(populate_existing=True))).scalar_one()
    assert Decimal(str(wallet.debt)) == Decimal(900)


@pytest.mark.asyncio
async def test_more_than_is_left_is_not_refunded(db, rzp):
    company = await _company(db)
    _, verified = await _top_up(db, rzp, company, "600")
    payment = await _payment(db, verified)
    staff = _user("app_admin")
    first = await _call(db, staff, "POST", f"/api/v1/admin/payments/{payment.id}/refund",
                        json={"net": "500", "reason": "test: most of it"})
    second = await _call(db, staff, "POST", f"/api/v1/admin/payments/{payment.id}/refund",
                         json={"net": "150", "reason": "test: too much"})
    assert (first.status_code, second.status_code) == (200, 422)
    assert len(rzp.refunds) == 1
    assert len((await db.execute(select(Refund).where(Refund.payment_id == payment.id))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_only_staff_refund(db, rzp):
    company = await _company(db)
    _, verified = await _top_up(db, rzp, company, "600")
    payment = await _payment(db, verified)
    res = await _call(db, _user("tenant_admin", company), "POST", f"/api/v1/admin/payments/{payment.id}/refund",
                      json={"reason": "please"})
    assert res.status_code == 403 and rzp.refunds == []
