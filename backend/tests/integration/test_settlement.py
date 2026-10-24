"""Settlement: every usage row charged exactly once, never free (Phase 15 T3-5, T3-6; tech design §6.5).

A run's rows and its descendants' are charged when it finishes; a call's at
hang-up — into debt when the wallet runs out (no free calls, B-10); a row whose
rating failed is rated then; usage with no run, and anything a failed
settlement left, is charged by the hourly job — but not the rows of work still
holding credit. Σ billed of the rows = Σ charged to the wallet. Real Postgres,
rolled back.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.orm.usage import UsageLog
from src.billing.billing_models import BillingLine, CreditHold, WalletEntry
from src.billing.settlement import settle_run, settle_unsettled
from src.billing.wallet import WalletService
from src.billing.wallet_jobs import settle_standalone
from tests.harness.wallet import available, fund

pytestmark = pytest.mark.needs_db


async def _company(db, currency="INR"):
    from src.auth.models import Company
    c = Company(name=f"settle-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency)
    db.add(c)
    await db.flush()
    return c.id


async def _run(db, company_id, parent=None):
    ent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name=f"s-{uuid.uuid4().hex[:4]}")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=company_id, status="COMPLETED", input_data={},
                       parent_run_id=parent.id if parent else None, depth=1 if parent else 0)
    db.add(run)
    await db.flush()
    return run


async def _row(db, company_id, run_id, billed, *, category="ai_models", rated=True, age=timedelta(0)):
    row = UsageLog(company_id=company_id, run_id=run_id, raw_quantity=Decimal(1), calculated_cost=Decimal(billed),
                   billed_usd=Decimal(billed) if rated else None, category=category if rated else None,
                   attribution="actor_step", timestamp=datetime.utcnow() - age)
    db.add(row)
    await db.flush()
    return row


async def _charged(db, company_id) -> Decimal:
    """What settlements took from the wallet: deductions and debt, in its currency."""
    return -Decimal(str((await db.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
        WalletEntry.company_id == company_id, WalletEntry.kind.in_(("deduct", "debt_add")),
        WalletEntry.source_type == "settlement"))).scalar()))


@pytest.mark.asyncio
async def test_a_run_and_its_descendants_are_settled_once(db):
    company = await _company(db)
    await fund(db, company, "10")                                         # ₹1,000
    parent = await _run(db, company)
    child = await _run(db, company, parent)
    await _row(db, company, parent.id, "0.40")
    await _row(db, company, child.id, "0.10", category="tools")
    first = await settle_run(db, db, parent)
    second = await settle_run(db, db, parent)
    assert first.claimed and first.billed_usd == Decimal("0.50") and first.billed_ccy == Decimal("50")
    assert not second.claimed and second.billed_usd == 0
    assert await available(db, company) == Decimal("950")
    rows = (await db.execute(select(UsageLog).where(UsageLog.company_id == company))).scalars().all()
    assert {r.settlement_id for r in rows} == {first.settlement_id}
    assert {(r.currency, r.billed_ccy) for r in rows} == {("INR", Decimal("40")), ("INR", Decimal("10"))}
    lines = dict((await db.execute(select(BillingLine.category, BillingLine.billed_ccy).where(
        BillingLine.company_id == company))).all())
    assert lines == {"ai_models": Decimal("40"), "tools": Decimal("10")}
    hold = (await db.execute(select(CreditHold).where(CreditHold.run_id == parent.id))).scalar_one()
    assert hold.settled_at and hold.billed_amount == Decimal("0.50") and hold.billed_ccy == Decimal("50")
    deducts = (await db.execute(select(WalletEntry.category, WalletEntry.amount).where(
        WalletEntry.company_id == company, WalletEntry.kind == "deduct"))).all()
    assert sorted(deducts) == [("ai_models", Decimal("-40")), ("tools", Decimal("-10"))]
    assert await WalletService(db).check(company) == []


@pytest.mark.asyncio
async def test_a_call_with_too_little_credit_goes_into_debt(db):
    """No free calls (B-10): the old path refused the deduction and the call cost nothing."""
    company = await _company(db)
    await fund(db, company, "0.20")                                       # ₹20
    call = await _run(db, company)
    await _row(db, company, call.id, "0.75", category="voice")
    settled = await settle_run(db, db, SimpleNamespace(id=call.id, company_id=company, total_cost_usd=Decimal("0.75"),
                                                       entity_id=None),
                               grouping_type="agent", subject_type="call", descendants=False)
    assert settled.billed_ccy == Decimal("75") and settled.change.debt_added == Decimal("55")
    wallet = await WalletService(db).get(company)
    assert wallet.state == "over_tolerance" and wallet.debt == Decimal("55")
    assert await available(db, company) == 0


@pytest.mark.asyncio
async def test_a_row_whose_rating_failed_is_rated_at_settlement(db):
    company = await _company(db, currency="USD")
    await fund(db, company, "5")
    run = await _run(db, company)
    await _row(db, company, run.id, "0.30", rated=False)
    settled = await settle_run(db, db, run)
    row = (await db.execute(select(UsageLog).where(UsageLog.run_id == run.id))).scalar_one()
    assert row.billed_usd is not None and row.billed_usd > 0 and row.category == "tools"
    assert settled.billed_usd == row.billed_usd


@pytest.mark.asyncio
async def test_the_hourly_job_settles_what_no_run_settled_but_not_running_work(db):
    company = await _company(db, currency="USD")
    await fund(db, company, "5")
    running = await _run(db, company)
    db.add(CreditHold(company_id=company, run_id=running.id, amount=Decimal("1"), currency="USD"))
    finished = await _run(db, company)
    await _row(db, company, None, "0.05", category="hosting")                    # no run: settled now
    await _row(db, company, finished.id, "0.20", age=timedelta(minutes=30))      # left behind: settled
    await _row(db, company, finished.id, "0.70", age=timedelta(minutes=2))       # too recent: waits
    await _row(db, company, running.id, "0.90", age=timedelta(minutes=30))       # running: its own
    settled = await settle_unsettled(db, company)
    assert settled.billed_usd == Decimal("0.25") and len(settled.rows) == 2
    again = await settle_unsettled(db, company)
    assert again.billed_usd == 0
    later = await settle_unsettled(db, company, now=datetime.utcnow() + timedelta(minutes=15))
    assert later.billed_usd == Decimal("0.70")


@pytest.mark.asyncio
async def test_every_rated_row_is_charged_and_the_sums_reconcile(db):
    """Σ billed of the rows = Σ charged to the wallets (the T3-6 reconciliation)."""
    companies = [await _company(db), await _company(db, currency="USD")]
    for company in companies:
        await fund(db, company, "1")
        run = await _run(db, company)
        for billed in ("0.11", "0.22", "0.33"):
            await _row(db, company, run.id, billed)
        await _row(db, company, None, "0.44", category="database")
        await settle_run(db, db, run)
    await settle_standalone(db)
    for company in companies:
        unsettled = (await db.execute(select(func.count()).where(UsageLog.company_id == company,
                                                                  UsageLog.settlement_id.is_(None)))).scalar()
        billed_ccy = Decimal(str((await db.execute(select(func.sum(UsageLog.billed_ccy)).where(
            UsageLog.company_id == company))).scalar()))
        assert unsettled == 0 and billed_ccy == await _charged(db, company)
        assert await WalletService(db).check(company) == []


@pytest.mark.asyncio
async def test_rows_charged_before_the_cutover_are_never_charged_again(db):
    company = await _company(db, currency="USD")
    await fund(db, company, "5")
    run = await _run(db, company)
    row = await _row(db, company, run.id, "1.00")
    await db.execute(text("UPDATE usage_logs SET settlement_id = '00000000-0000-0000-0000-00000000c015' "
                          "WHERE id = :i"), {"i": row.id})
    settled = await settle_run(db, db, run)
    assert settled.billed_usd == 0 and await available(db, company) == Decimal("5")
