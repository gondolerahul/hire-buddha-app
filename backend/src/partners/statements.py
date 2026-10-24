"""Payouts: holdback, the margin guard, monthly statements (Phase 15 T8-10, tech design §11.6, §11.7).

* ``release`` (daily): an ``accrued`` entry whose ``payable_after`` has passed
  becomes ``payable`` — if its partner is in good standing.
* ``margin_guard`` (monthly, before statements): a tenant's commissions on
  its top-ups and subscriptions in a month may be at most
  ``partners.max_margin_share_pct`` of its margin that month (billed − cost,
  ``billing_lines``); the excess is ``held`` (newest first), released when a
  later month's spare margin covers it, and reversed after a quarter.
* ``build`` (day ``partners.statement_day``): per partner and currency, last
  month's payable entries with TDS (``partners.tds_pct``) deducted; below the
  minimum payout they carry forward. Staff approve, export (bank file) and
  mark paid; a partner may dispute and upload its GST invoice.

A statement's gross is the sum of its entries, and the ledger nets to what is
still owed: on payment a ``payout`` entry takes the net back out.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from src.partners.models import EARNING_STATUSES, PartnerLedgerEntry, PartnerProfile, PartnerStatement

logger = logging.getLogger(__name__)

HUNDRED = Decimal(100)
GUARDED = ("usage_topup", "subscription")
QUARTER = timedelta(days=92)


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def view(stmt: PartnerStatement, *, partner: Optional[str] = None) -> Dict[str, Any]:
    return {"id": str(stmt.id), "partner_id": str(stmt.partner_id), "partner": partner,
            "period": stmt.period.isoformat(), "currency": stmt.currency, "gross": str(stmt.gross),
            "tds": str(stmt.tds), "tds_pct": str(stmt.tds_pct), "net": str(stmt.net), "status": stmt.status,
            "gst_invoice_ref": stmt.gst_invoice_ref, "dispute_reason": stmt.dispute_reason,
            "payout_ref": stmt.payout_ref, "approved_at": stmt.approved_at.isoformat() if stmt.approved_at else None,
            "paid_at": stmt.paid_at.isoformat() if stmt.paid_at else None,
            "created_at": stmt.created_at.isoformat() if stmt.created_at else None}


def entry_view(e: PartnerLedgerEntry, *, tenant: Optional[str] = None) -> Dict[str, Any]:
    return {"id": str(e.id), "kind": e.kind, "amount": str(e.amount), "currency": e.currency,
            "revenue_kind": e.revenue_kind, "base_amount": str(e.base_amount) if e.base_amount is not None else None,
            "base_currency": e.base_currency, "rate_pct": str(e.rate_pct) if e.rate_pct is not None else None,
            "tenant_id": str(e.tenant_id) if e.tenant_id else None, "tenant": tenant, "level": e.level,
            "status": e.status, "hold_reason": e.hold_reason, "reason": e.reason,
            "payable_after": e.payable_after.isoformat() if e.payable_after else None,
            "statement_id": str(e.statement_id) if e.statement_id else None,
            "created_at": e.created_at.isoformat() if e.created_at else None}


# ── holdback ─────────────────────────────────────────────────────────────────

async def release(db: Any, *, now: Optional[datetime] = None) -> int:
    """Accrued entries past their holdback become payable (partners in good standing). Commits."""
    from sqlalchemy import update

    now = now or datetime.utcnow()
    good = select(PartnerProfile.company_id).where(PartnerProfile.status.in_(EARNING_STATUSES))
    result = await db.execute(update(PartnerLedgerEntry).where(
        PartnerLedgerEntry.status == "accrued", PartnerLedgerEntry.payable_after <= now,
        PartnerLedgerEntry.partner_id.in_(good)).values(status="payable", updated_at=now))
    await db.commit()
    return result.rowcount or 0


# ── the margin guard ─────────────────────────────────────────────────────────

async def _margin_usd(db: Any, tenant_id: UUID, start: date, end: date) -> Decimal:
    from src.billing.billing_models import BillingLine

    row = (await db.execute(select(func.coalesce(func.sum(BillingLine.billed_usd), 0),
                                   func.coalesce(func.sum(BillingLine.cost_usd), 0)).where(
        BillingLine.company_id == tenant_id, BillingLine.period_day >= start, BillingLine.period_day < end))).one()
    return Decimal(str(row[0])) - Decimal(str(row[1]))


async def margin_guard(db: Any, period: date) -> Dict[str, int]:
    """Hold commissions on a tenant's usage above the month's allowed share of its margin; release or
    reverse what earlier months held. Commits."""
    from src.billing.settings_catalogue import value

    share = Decimal(str(await value(db, "partners.max_margin_share_pct"))) / HUNDRED
    start, end = month_start(period), next_month(period)
    begin, finish = datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time())
    out = {"held": 0, "released": 0, "reversed": 0}
    tenants = (await db.execute(select(PartnerLedgerEntry.tenant_id).where(
        PartnerLedgerEntry.revenue_kind.in_(GUARDED), PartnerLedgerEntry.created_at >= begin,
        PartnerLedgerEntry.created_at < finish, PartnerLedgerEntry.kind.in_(("commission", "override")),
        PartnerLedgerEntry.tenant_id.isnot(None)).distinct())).scalars().all()
    for tenant_id in tenants:
        allowed = max(await _margin_usd(db, tenant_id, start, end), Decimal(0)) * share
        entries = (await db.execute(select(PartnerLedgerEntry).where(
            PartnerLedgerEntry.tenant_id == tenant_id, PartnerLedgerEntry.revenue_kind.in_(GUARDED),
            PartnerLedgerEntry.kind.in_(("commission", "override")),
            PartnerLedgerEntry.status.in_(("accrued", "payable", "held")),
            PartnerLedgerEntry.created_at >= begin, PartnerLedgerEntry.created_at < finish)
            .order_by(PartnerLedgerEntry.created_at.desc()))).scalars().all()
        total = sum((Decimal(str(e.amount_usd or 0)) for e in entries if e.hold_reason != "margin_guard"),
                    Decimal(0))
        for entry in entries:
            if total <= allowed:
                break
            if entry.status in ("accrued", "payable") and entry.statement_id is None:
                entry.status, entry.hold_reason = "held", "margin_guard"
                total -= Decimal(str(entry.amount_usd or 0))
                out["held"] += 1
    # Earlier months' margin holds: released by spare margin since, reversed after a quarter.
    held = (await db.execute(select(PartnerLedgerEntry).where(
        PartnerLedgerEntry.hold_reason == "margin_guard", PartnerLedgerEntry.status == "held",
        PartnerLedgerEntry.created_at < begin).order_by(PartnerLedgerEntry.created_at))).scalars().all()
    spare_by_tenant: Dict[Any, Decimal] = {}
    for entry in held:
        if entry.tenant_id not in spare_by_tenant:
            margin = max(await _margin_usd(db, entry.tenant_id, start, end), Decimal(0)) * share
            used = (await db.execute(select(func.coalesce(func.sum(PartnerLedgerEntry.amount_usd), 0)).where(
                PartnerLedgerEntry.tenant_id == entry.tenant_id, PartnerLedgerEntry.revenue_kind.in_(GUARDED),
                PartnerLedgerEntry.status.in_(("accrued", "payable", "paid")),
                PartnerLedgerEntry.created_at >= begin, PartnerLedgerEntry.created_at < finish))).scalar()
            spare_by_tenant[entry.tenant_id] = margin - Decimal(str(used or 0))
        amount = Decimal(str(entry.amount_usd or 0))
        if spare_by_tenant[entry.tenant_id] >= amount:
            entry.status, entry.hold_reason = "accrued", None
            spare_by_tenant[entry.tenant_id] -= amount
            out["released"] += 1
        elif entry.created_at < finish - QUARTER:
            entry.status = "reversed"
            entry.reason = f"{entry.reason or ''} — reversed: the margin did not cover it within a quarter"
            out["reversed"] += 1
    await db.commit()
    return out


# ── statements ───────────────────────────────────────────────────────────────

async def build(db: Any, period: date) -> Dict[str, int]:
    """Statements of ``period``'s month: its payable entries (and earlier ones carried forward). Commits."""
    from src.billing.currency import current_rate, to_ccy
    from src.billing.settings_catalogue import value

    period = month_start(period)
    end = datetime.combine(next_month(period), datetime.min.time())
    tds_pct = Decimal(str(await value(db, "partners.tds_pct")))
    minimum_usd = Decimal(str(await value(db, "partners.payout_min_usd")))
    out = {"statements": 0, "carried": 0, "existing": 0}
    groups = (await db.execute(select(PartnerLedgerEntry.partner_id, PartnerLedgerEntry.currency,
                                      func.sum(PartnerLedgerEntry.amount)).where(
        PartnerLedgerEntry.status == "payable", PartnerLedgerEntry.statement_id.is_(None),
        PartnerLedgerEntry.created_at < end).group_by(PartnerLedgerEntry.partner_id, PartnerLedgerEntry.currency)
    )).all()
    for partner_id, currency, gross in groups:
        gross = Decimal(str(gross or 0))
        if (await db.execute(select(PartnerStatement.id).where(
                PartnerStatement.partner_id == partner_id, PartnerStatement.period == period,
                PartnerStatement.currency == currency))).first():
            out["existing"] += 1
            continue
        tds = (gross * tds_pct / HUNDRED).quantize(Decimal("0.01")) if gross > 0 else Decimal(0)
        net = gross - tds
        if net < to_ccy(minimum_usd, await current_rate(db, currency)):
            out["carried"] += 1
            continue
        stmt = PartnerStatement(partner_id=partner_id, period=period, currency=currency, gross=gross, tds=tds,
                                net=net, tds_pct=tds_pct, status="draft")
        db.add(stmt)
        await db.flush()
        entries = (await db.execute(select(PartnerLedgerEntry).where(
            PartnerLedgerEntry.partner_id == partner_id, PartnerLedgerEntry.currency == currency,
            PartnerLedgerEntry.status == "payable", PartnerLedgerEntry.statement_id.is_(None),
            PartnerLedgerEntry.created_at < end))).scalars().all()
        for entry in entries:
            entry.statement_id = stmt.id
        if tds:
            db.add(PartnerLedgerEntry(partner_id=partner_id, kind="tds", amount=-tds, currency=currency,
                                      status="payable", statement_id=stmt.id, source_type="statement",
                                      source_id=str(stmt.id), reason=f"TDS {tds_pct.normalize()} %"))
        out["statements"] += 1
        from src.partners.lifecycle import notify_partner
        await notify_partner(partner_id, kind="partner.statement", title=f"Your {period:%B %Y} statement is ready",
                             body=f"{currency} {net:,.2f} after TDS, to be approved and paid.",
                             link="/partner/statements", dedupe=f"partner.statement:{stmt.id}")
    await db.commit()
    return out


async def run_month(db: Any, *, today: Optional[date] = None, force: bool = False) -> Dict[str, Any]:
    """The statement day's job: last month's margin guard, then its statements."""
    from src.billing.settings_catalogue import value

    today = today or datetime.utcnow().date()
    if not force and today.day != int(await value(db, "partners.statement_day")):
        return {"skipped": "not the statement day"}
    last = month_start(today.replace(day=1) - timedelta(days=1))
    return {"period": last.isoformat(), "margin_guard": await margin_guard(db, last), **await build(db, last)}


async def entries_of(db: Any, stmt: PartnerStatement) -> List[PartnerLedgerEntry]:
    return list((await db.execute(select(PartnerLedgerEntry).where(PartnerLedgerEntry.statement_id == stmt.id)
                                  .order_by(PartnerLedgerEntry.created_at))).scalars().all())


async def approve(db: Any, stmt: PartnerStatement, *, actor: Any) -> PartnerStatement:
    from src.common.admin_audit import record_admin_change

    if stmt.status not in ("draft", "disputed"):
        raise HTTPException(status_code=409, detail=f"the statement is {stmt.status}")
    profile = await db.get(PartnerProfile, stmt.partner_id)
    if profile is None or profile.kyc_status != "verified" or not profile.bank_encrypted:
        raise HTTPException(status_code=409, detail="the partner's KYC and bank account must be verified first")
    stmt.status, stmt.approved_by, stmt.approved_at = "approved", actor.id, datetime.utcnow()
    record_admin_change(db, actor=actor, action="approve", object_type="partner_statement", object_key=str(stmt.id),
                        target_company_id=stmt.partner_id, new_value={"net": str(stmt.net), "currency": stmt.currency})
    return stmt


async def mark_paid(db: Any, stmt: PartnerStatement, *, actor: Any, payout_ref: str) -> PartnerStatement:
    from sqlalchemy import update

    from src.common.admin_audit import record_admin_change

    if stmt.status != "approved":
        raise HTTPException(status_code=409, detail="only an approved statement is paid")
    now = datetime.utcnow()
    stmt.status, stmt.paid_at, stmt.payout_ref = "paid", now, payout_ref
    await db.execute(update(PartnerLedgerEntry).where(PartnerLedgerEntry.statement_id == stmt.id)
                     .values(status="paid", updated_at=now))
    db.add(PartnerLedgerEntry(partner_id=stmt.partner_id, kind="payout", amount=-Decimal(str(stmt.net)),
                              currency=stmt.currency, status="paid", statement_id=stmt.id, source_type="statement",
                              source_id=str(stmt.id), reason=f"paid: {payout_ref}"))
    record_admin_change(db, actor=actor, action="pay", object_type="partner_statement", object_key=str(stmt.id),
                        target_company_id=stmt.partner_id, new_value={"net": str(stmt.net), "ref": payout_ref})
    from src.partners.lifecycle import notify_partner
    await notify_partner(stmt.partner_id, kind="partner.paid", title=f"{stmt.currency} {stmt.net:,.2f} paid",
                         body=f"Your {stmt.period:%B %Y} statement ({payout_ref}).", link="/partner/statements",
                         dedupe=f"partner.paid:{stmt.id}")
    return stmt


async def dispute(db: Any, stmt: PartnerStatement, *, reason: str) -> PartnerStatement:
    if stmt.status not in ("draft", "approved"):
        raise HTTPException(status_code=409, detail=f"the statement is {stmt.status}")
    stmt.status, stmt.dispute_reason = "disputed", reason
    return stmt


async def export_csv(db: Any, statements: List[PartnerStatement]) -> str:
    """The bank file of approved statements: payee, account, IFSC, amount, reference."""
    from src.common.security import decrypt_api_key

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["statement", "partner", "period", "currency", "net", "account_name", "account_number", "ifsc",
                     "pan", "gstin"])
    for stmt in statements:
        profile = await db.get(PartnerProfile, stmt.partner_id)
        bank: Dict[str, Any] = {}
        if profile is not None and profile.bank_encrypted:
            import json
            bank = json.loads(decrypt_api_key(profile.bank_encrypted) or "{}")
        writer.writerow([str(stmt.id), profile.legal_name if profile else "", stmt.period.isoformat(), stmt.currency,
                         str(stmt.net), bank.get("account_name", ""), bank.get("account_number", ""),
                         bank.get("ifsc", ""), profile.pan if profile else "", profile.gstin if profile else ""])
    return buffer.getvalue()


def render_pdf(stmt: PartnerStatement, entries: List[PartnerLedgerEntry], *, partner: str) -> bytes:
    from src.billing.pdf import Document, rows

    doc = Document(f"Statement {stmt.period:%B %Y}")
    page = doc.page()
    page.text(50, 790, "HireBuddha partner statement", size=16, bold=True)
    page.text(50, 770, f"{partner} · {stmt.period:%B %Y} · {stmt.currency}")
    y = 740
    for e in entries[:40]:
        label = (e.reason or e.kind)[:80]
        page.text(50, y, label, size=8)
        page.right(545, y, f"{Decimal(str(e.amount)):,.2f}", size=8)
        y -= 14
    page.line(50, y, 545, y)
    rows(page, y - 20, [("Gross", f"{stmt.gross:,.2f}"), (f"TDS ({stmt.tds_pct.normalize()} %)", f"-{stmt.tds:,.2f}"),
                        ("Net payable", f"{stmt.net:,.2f}")])
    return doc.to_bytes()
