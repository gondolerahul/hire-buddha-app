"""Tax invoices and credit notes (Phase 15 T6-5, T6-6; tech design §12.3).

One tax invoice per payment received (TX-3), issued in the payment's
transaction with a number from a gap-free series per Indian financial year —
``HB/2026-27/000123`` (TX-4): the series row is taken under its lock, so two
payments cannot share a number and a rolled-back payment gives its number
back. The customer (legal name, GSTIN, address, state) and the supplier are
copied onto the invoice as they are then. The PDF is written after the
commit, stored as an object (``<company>/invoices/…``) and the company's
billing admins are told (TX-6). A credit note is issued against an invoice for
a refund (TX-7), from its own series.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

SAC = "998313"            # IT consulting and support services
INVOICE, CREDIT_NOTE = "invoice", "credit_note"


def financial_year(at: datetime) -> str:
    """The Indian financial year of ``at``: April to March, ``2026-27``."""
    start = at.year if at.month >= 4 else at.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


async def next_number(db: Any, kind: str, prefix: str, at: Optional[datetime] = None) -> str:
    """The series' next number, taken under its row lock (the caller's transaction)."""
    from src.billing.billing_models import DocumentSeries

    fy = financial_year(at or datetime.utcnow())
    await db.execute(pg_insert(DocumentSeries).values(kind=kind, prefix=prefix, financial_year=fy, next_number=1)
                     .on_conflict_do_nothing())
    row = (await db.execute(select(DocumentSeries).where(
        DocumentSeries.kind == kind, DocumentSeries.prefix == prefix, DocumentSeries.financial_year == fy)
        .with_for_update())).scalar_one()
    number = row.next_number
    row.next_number = number + 1
    await db.flush()
    return f"{prefix}/{fy}/{number:06d}"


async def _supplier(db: Any) -> dict:
    from src.billing.settings_catalogue import value

    return {"legal_name": await value(db, "tax.supplier_legal_name"),
            "gstin": await value(db, "tax.supplier_gstin"),
            "state": await value(db, "tax.supplier_state"),
            "address": await value(db, "tax.supplier_address"),
            "lut_number": await value(db, "tax.lut_number")}


def _customer(company: Any) -> dict:
    return {"name": getattr(company, "legal_name", None) or company.name, "gstin": getattr(company, "gstin", None),
            "state": getattr(company, "billing_state", None), "country": getattr(company, "country_code", None),
            "address": getattr(company, "billing_address", None)}


async def issue_invoice(db: Any, *, payment: Any, company: Any, taxed: Any, lines: List[Tuple[str, Decimal]],
                        currency: str) -> Any:
    """The invoice of ``payment`` (the caller commits): ``taxed`` is its ``tax.TaxedAmount``,
    ``lines`` (description, net amount)."""
    from src.billing.billing_models import Invoice, InvoiceLine
    from src.billing.settings_catalogue import value

    prefix = str(await value(db, "invoice.series_prefix") or "HB")
    invoice = Invoice(number=await next_number(db, INVOICE, prefix), company_id=company.id, payment_id=payment.id,
                      currency=currency, net=taxed.net, cgst=taxed.cgst, sgst=taxed.sgst, igst=taxed.igst,
                      tax=taxed.tax, total=taxed.gross, tax_rate=taxed.rate, regime=taxed.regime,
                      place_of_supply=getattr(company, "billing_state", None) if taxed.regime != "export" else None,
                      customer=_customer(company), supplier=await _supplier(db), issued_at=datetime.utcnow())
    db.add(invoice)
    await db.flush()
    for description, amount in lines:
        db.add(InvoiceLine(invoice_id=invoice.id, description=description, sac=SAC, amount=amount))
    payment.invoice_id = invoice.id
    await db.flush()
    return invoice


async def issue_credit_note(db: Any, *, invoice: Any, taxed: Any, reason: str) -> Any:
    from src.billing.billing_models import CreditNote
    from src.billing.settings_catalogue import value

    prefix = f"{await value(db, 'invoice.series_prefix') or 'HB'}-CN"
    note = CreditNote(number=await next_number(db, CREDIT_NOTE, prefix), invoice_id=invoice.id,
                      company_id=invoice.company_id, currency=invoice.currency, net=taxed.net, cgst=taxed.cgst,
                      sgst=taxed.sgst, igst=taxed.igst, tax=taxed.tax, total=taxed.gross, reason=reason,
                      issued_at=datetime.utcnow())
    db.add(note)
    await db.flush()
    return note


def _money(amount: Any, currency: str) -> str:
    return f"{currency} {Decimal(str(amount or 0)):,.2f}"


def render(document: Any, lines: List[Any], *, title: str, against: Optional[str] = None) -> bytes:
    """An invoice or a credit note as a PDF."""
    from src.billing.pdf import Document, rows

    doc = Document(f"{title} {document.number}")
    page = doc.page()
    supplier, customer = document_parties(document)
    page.text(50, 790, title.upper(), 18, bold=True)
    page.right(545, 790, document.number, 12, bold=True)
    page.right(545, 774, f"Date: {document.issued_at:%d %b %Y}", 9)
    if against:
        page.right(545, 760, f"Against invoice {against}", 9)
    y = 740
    page.text(50, y, supplier.get("legal_name") or "HireBuddha", 11, bold=True)
    for line in (supplier.get("address"), f"GSTIN: {supplier['gstin']}" if supplier.get("gstin") else None,
                 f"State: {supplier['state']}" if supplier.get("state") else None):
        if line:
            y -= 13
            page.text(50, y, str(line), 9)
    y2 = 740
    page.text(320, y2, "Billed to", 9, bold=True)
    for line in (customer.get("name"), _address(customer.get("address")),
                 f"GSTIN: {customer['gstin']}" if customer.get("gstin") else None,
                 f"State: {customer['state']}" if customer.get("state") else None,
                 f"Country: {customer['country']}" if customer.get("country") else None):
        if line:
            y2 -= 13
            page.text(320, y2, str(line)[:48], 9)
    y = min(y, y2) - 30
    page.line(50, y, 545, y)
    y -= 15
    page.text(50, y, "Description", 9, bold=True)
    page.text(330, y, "SAC", 9, bold=True)
    page.right(545, y, "Amount", 9, bold=True)
    y -= 6
    page.line(50, y, 545, y)
    y -= 15
    for line in lines:
        page.text(50, y, str(line.description)[:55], 10)
        page.text(330, y, line.sac or "", 10)
        page.right(545, y, _money(line.amount, document.currency), 10)
        y -= 16
    page.line(300, y, 545, y)
    y -= 16
    items = [("Taxable value", _money(document.net, document.currency))]
    if Decimal(str(document.cgst or 0)) > 0 or Decimal(str(document.sgst or 0)) > 0:
        half = Decimal(str(getattr(document, "tax_rate", 0) or 0)) / 2
        items += [(f"CGST {half:g}%", _money(document.cgst, document.currency)),
                  (f"SGST {half:g}%", _money(document.sgst, document.currency))]
    if Decimal(str(document.igst or 0)) > 0:
        items.append((f"IGST {Decimal(str(document.tax_rate)):g}%", _money(document.igst, document.currency)))
    y = rows(page, y, items, x=300)
    page.line(300, y + 6, 545, y + 6)
    page.text(300, y - 8, "Total", 11, bold=True)
    page.right(545, y - 8, _money(document.total, document.currency), 11, bold=True)
    y -= 40
    regime = getattr(document, "regime", None)
    if regime == "export":
        lut = supplier.get("lut_number")
        page.text(50, y, "Export of services: zero-rated supply under LUT" + (f" {lut}" if lut else "") + ".", 9)
        y -= 13
    if getattr(document, "place_of_supply", None):
        page.text(50, y, f"Place of supply: {document.place_of_supply}", 9)
        y -= 13
    if getattr(document, "reason", None):
        page.text(50, y, f"Reason: {document.reason}"[:95], 9)
        y -= 13
    page.text(50, 60, "Prices are exclusive of GST. This is a computer-generated document.", 8)
    return doc.to_bytes()


def document_parties(document: Any) -> Tuple[dict, dict]:
    supplier = getattr(document, "supplier", None) or {}
    customer = getattr(document, "customer", None) or {}
    return supplier, customer


def _address(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.values() if v)
    return str(value)


async def store_pdf(db: Any, invoice_id: UUID) -> Optional[str]:
    """Write the invoice's PDF to storage and tell the billing admins (best-effort; commits)."""
    from src.billing.billing_models import Invoice, InvoiceLine
    from src.common.platform.storage import company_namespace, get_storage
    from src.notifications.service import notify

    try:
        invoice = await db.get(Invoice, invoice_id)
        lines = (await db.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id))).scalars().all()
        key = f"{company_namespace(invoice.company_id)}/invoices/{invoice.number.replace('/', '-')}.pdf"
        await get_storage().put(key, render(invoice, list(lines), title="Tax invoice"),
                                content_type="application/pdf")
        invoice.pdf_key = key
        await db.commit()
        told = await notify(invoice.company_id, kind="billing.invoice", severity="info", link="/billing/invoices",
                            title=f"Invoice {invoice.number}: {_money(invoice.total, invoice.currency)}",
                            body="Your payment is received; the tax invoice is on the Invoices page.",
                            dedupe_key=f"invoice:{invoice.number}")
        if told:
            invoice.emailed_at = datetime.utcnow()
            await db.commit()
        return key
    except Exception:  # noqa: BLE001 - the payment stands; the PDF can be made again
        logger.warning("invoice %s PDF not stored", invoice_id, exc_info=True)
        await db.rollback()
        return None


async def credit_note_pdf(db: Any, note: Any) -> bytes:
    from src.billing.billing_models import Invoice

    invoice = await db.get(Invoice, note.invoice_id)
    from types import SimpleNamespace

    line = SimpleNamespace(description=f"Refund against {invoice.number}", sac=SAC, amount=note.net)
    view = SimpleNamespace(**{c: getattr(note, c) for c in ("number", "issued_at", "currency", "net", "cgst",
                                                             "sgst", "igst", "tax", "total", "reason")},
                           tax_rate=invoice.tax_rate, regime=invoice.regime, place_of_supply=invoice.place_of_supply,
                           supplier=invoice.supplier, customer=invoice.customer)
    return render(view, [line], title="Credit note", against=invoice.number)
