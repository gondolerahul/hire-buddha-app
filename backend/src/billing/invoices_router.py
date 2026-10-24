"""Invoices, the billing profile, payments and refunds (Phase 15 T6-5, T6-6; tech design §12, §15).

The company (any of its users reads; its admins edit the profile):

    GET /api/v1/billing/invoices                       its invoices and credit notes, newest first
    GET /api/v1/billing/invoices/{id}/pdf              the invoice as a PDF
    GET /api/v1/billing/credit-notes/{id}/pdf
    GET /api/v1/billing/profile                        legal name, GSTIN, billing state and address (TX-5)
    PUT /api/v1/billing/profile

Staff (``app_admin``):

    GET  /api/v1/admin/payments?company_id=&status=    payments with their tax split and invoice
    POST /api/v1/admin/payments/{id}/refund            {net?, reason}
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import RoleChecker, StaffChecker
from src.auth.models import Company, User
from src.auth.roles import Role
from src.auth.router import get_current_user
from src.billing.billing_models import CreditNote, Invoice, InvoiceLine, PaymentTransaction
from src.common.tenancy.session import get_control_db

router = APIRouter(tags=["Invoices"])
staff = RoleChecker([Role.APP_ADMIN])
finance = StaffChecker('finance')
billing_admin = RoleChecker([Role.PARTNER_ADMIN, Role.TENANT_ADMIN])
STAFF_ROLES = {"app_admin", "app_user"}


def _role(user: User) -> str:
    return str(getattr(user.role, "value", user.role))


def _invoice_view(i: Invoice) -> dict:
    return {"id": str(i.id), "number": i.number, "currency": i.currency, "net": str(i.net), "cgst": str(i.cgst),
            "sgst": str(i.sgst), "igst": str(i.igst), "tax": str(i.tax), "total": str(i.total),
            "tax_rate": str(i.tax_rate), "regime": i.regime, "place_of_supply": i.place_of_supply,
            "issued_at": i.issued_at.isoformat() if i.issued_at else None, "payment_id": str(i.payment_id)}


@router.get("/api/v1/billing/invoices")
async def list_invoices(company_id: Optional[UUID] = Query(None, description="Staff: another company's"),
                        db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    target = company_id if company_id and _role(user) in STAFF_ROLES else user.company_id
    invoices = (await db.execute(select(Invoice).where(Invoice.company_id == target)
                                 .order_by(Invoice.issued_at.desc()).limit(200))).scalars().all()
    notes = (await db.execute(select(CreditNote).where(CreditNote.company_id == target)
                              .order_by(CreditNote.issued_at.desc()).limit(200))).scalars().all()
    numbers = {i.id: i.number for i in invoices}
    return {"invoices": [_invoice_view(i) for i in invoices],
            "credit_notes": [{"id": str(n.id), "number": n.number, "invoice_id": str(n.invoice_id),
                              "invoice_number": numbers.get(n.invoice_id), "currency": n.currency,
                              "net": str(n.net), "tax": str(n.tax), "total": str(n.total), "reason": n.reason,
                              "issued_at": n.issued_at.isoformat() if n.issued_at else None} for n in notes]}


async def _own(db: AsyncSession, model, document_id: UUID, user: User):
    row = await db.get(model, document_id)
    if row is None or (row.company_id != user.company_id and _role(user) not in STAFF_ROLES):
        raise HTTPException(status_code=404, detail="not found")
    return row


def _pdf(body: bytes, number: str) -> Response:
    return Response(content=body, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{number.replace("/", "-")}.pdf"'})


@router.get("/api/v1/billing/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: UUID, db: AsyncSession = Depends(get_control_db),
                      user: User = Depends(get_current_user)):
    from src.billing.invoices import render
    from src.common.platform.storage import get_storage

    invoice = await _own(db, Invoice, invoice_id, user)
    if invoice.pdf_key:
        try:
            return _pdf(await get_storage().get(invoice.pdf_key), invoice.number)
        except Exception:  # noqa: BLE001 - made again below
            pass
    lines = (await db.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))).scalars().all()
    return _pdf(render(invoice, list(lines), title="Tax invoice"), invoice.number)


@router.get("/api/v1/billing/credit-notes/{note_id}/pdf")
async def credit_note_pdf(note_id: UUID, db: AsyncSession = Depends(get_control_db),
                          user: User = Depends(get_current_user)):
    from src.billing.invoices import credit_note_pdf as render_note

    note = await _own(db, CreditNote, note_id, user)
    return _pdf(await render_note(db, note), note.number)


class ProfileBody(BaseModel):
    legal_name: Optional[str] = Field(None, max_length=200)
    gstin: Optional[str] = Field(None, max_length=15)
    billing_state: Optional[str] = Field(None, max_length=2)
    billing_address: Optional[dict] = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, value: Optional[str]) -> Optional[str]:
        from src.auth.geography import valid_gstin
        return valid_gstin(value)

    @field_validator("billing_state")
    @classmethod
    def _state(cls, value: Optional[str]) -> Optional[str]:
        from src.auth.geography import valid_state
        return valid_state(value)


def _profile(c: Company) -> dict:
    return {"name": c.name, "legal_name": c.legal_name, "gstin": c.gstin, "billing_state": c.billing_state,
            "billing_address": c.billing_address or {}, "country_code": c.country_code,
            "billing_currency": c.billing_currency}


@router.get("/api/v1/billing/profile")
async def get_profile(db: AsyncSession = Depends(get_control_db), user: User = Depends(get_current_user)):
    return _profile(await db.get(Company, user.company_id))


@router.put("/api/v1/billing/profile")
async def put_profile(body: ProfileBody, db: AsyncSession = Depends(get_control_db),
                      user: User = Depends(billing_admin)):
    """What the next invoices show (TX-5); invoices already issued keep what they showed."""
    company = await db.get(Company, user.company_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await db.commit()
    return _profile(company)


# ── staff ──────────────────────────────────────────────────────────────────

def _payment_view(p: PaymentTransaction, invoice_number: Optional[str]) -> dict:
    return {"id": str(p.id), "company_id": str(p.company_id), "purpose": p.purpose or p.transaction_type,
            "status": p.status, "currency": p.currency, "gross": str(p.gross_amount or p.amount),
            "net": str(p.net_amount if p.net_amount is not None else p.amount), "tax": str(p.tax_amount or 0),
            "refunded_gross": str(p.refunded_gross or 0), "credits_awarded": str(p.credits_awarded or 0),
            "invoice_id": str(p.invoice_id) if p.invoice_id else None, "invoice_number": invoice_number,
            "gateway_payment_id": p.razorpay_payment_id,
            "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("/api/v1/admin/payments")
async def admin_payments(company_id: Optional[UUID] = None, status: Optional[str] = None,
                         limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_control_db),
                         user: User = Depends(finance)):
    query = select(PaymentTransaction, Invoice.number).outerjoin(Invoice, Invoice.id == PaymentTransaction.invoice_id)
    if company_id:
        query = query.where(PaymentTransaction.company_id == company_id)
    if status:
        query = query.where(PaymentTransaction.status == status)
    rows = (await db.execute(query.order_by(PaymentTransaction.created_at.desc()).limit(limit))).all()
    return [_payment_view(p, number) for p, number in rows]


class RefundBody(BaseModel):
    net: Optional[Decimal] = Field(None, gt=0, decimal_places=2, description="Net amount to refund; all that is left by default")
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/api/v1/admin/payments/{payment_id}/refund")
async def refund(payment_id: UUID, body: RefundBody, db: AsyncSession = Depends(get_control_db),
                 user: User = Depends(staff)):
    from src.billing.gateways import GatewayError, GatewayUnavailable, get_gateway
    from src.billing.refunds import RefundProblem, refund_payment

    payment = (await db.execute(select(PaymentTransaction).where(PaymentTransaction.id == payment_id)
                                .with_for_update())).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="no such payment")
    try:
        gateway = await get_gateway(db)
        done = await refund_payment(db, gateway, payment, net=body.net, reason=body.reason, actor=user)
    except GatewayUnavailable as missing:
        raise HTTPException(status_code=503, detail=str(missing)) from None
    except GatewayError as error:
        raise HTTPException(status_code=502, detail=f"The gateway refused the refund: {error}") from None
    except RefundProblem as problem:
        raise HTTPException(status_code=problem.status, detail=str(problem)) from None
    return {"refund_id": str(done.id), "gross": str(done.gross), "net": str(done.net), "currency": done.currency,
            "credit_taken": str(done.credit_taken), "debt_added": str(done.debt_added),
            "credit_note_id": str(done.credit_note_id) if done.credit_note_id else None}
