"""A run is admitted on credit, holds it, and stops when it runs out (BC-05, BC-06).

Before: ``check_credit_gate`` and ``check_credit_circuit_breaker`` had no
callers — a run started on an empty wallet ran to completion and was debited
at the end — and nothing reserved credit, so two runs could both spend the
same balance. Real Postgres, rolled back per test.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.ai.core.credit_guard import CreditGuard
from src.ai.core.exceptions import CreditExhaustedError
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.billing.billing_models import CreditHold
from src.billing.formulas import formula_for
from src.billing.credit_service import CreditService
from tests.harness.wallet import available, fund

pytestmark = pytest.mark.needs_db


async def _company(db, balance: str, currency: str = "USD"):
    """A company whose wallet holds ``balance`` USD (a top-up lot), billed in ``currency``."""
    from src.auth.models import Company
    c = Company(name=f"guard-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", billing_currency=currency)
    db.add(c)
    await db.flush()
    if Decimal(balance) > 0:
        await fund(db, c.id, balance)
    await db.flush()
    return c.id


async def _usage(db, run, cost: str):
    """A usage row of ``run`` rated with the company's formula, as the meters write it (T3-3)."""
    from src.ai.orm.usage import UsageLog
    formula = await formula_for(db, run.company_id)
    row = UsageLog(company_id=run.company_id, run_id=run.id, raw_quantity=Decimal(1), calculated_cost=Decimal(cost),
                   billed_usd=formula.rate(Decimal(cost)), formula_id=formula.id, category="ai_models",
                   attribution="actor_step")
    db.add(row)
    await db.flush()
    return row


async def _run(db, company_id, entity_type="PROCESS", status="RUNNING"):
    ent = HierarchicalEntity(company_id=company_id, type=entity_type, status="ACTIVE",
                             name=f"guard-{uuid.uuid4().hex[:4]}")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=company_id, status=status, input_data={})
    db.add(run)
    await db.flush()
    return run, ent


async def _admit(db, run, ent, estimate):
    guard = CreditGuard(db, None, run, ent)

    async def _estimate(_steps):
        return Decimal(estimate)
    guard.estimate = _estimate
    return guard, await guard.admit(ent.type, [])


async def _hold(db, run_id):
    return (await db.execute(select(CreditHold).where(CreditHold.run_id == run_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_a_run_on_an_empty_wallet_is_refused(db):
    company = await _company(db, "0")
    run, ent = await _run(db, company)
    _, refusal = await _admit(db, run, ent, "1.00")
    assert refusal and "Cannot start execution" in refusal
    assert await _hold(db, run.id) is None


@pytest.mark.asyncio
async def test_an_admitted_run_holds_its_estimate(db):
    company = await _company(db, "5")
    run, ent = await _run(db, company)
    _, refusal = await _admit(db, run, ent, "1.20")
    assert refusal is None
    assert Decimal(str((await _hold(db, run.id)).amount)) == Decimal("1.20")
    balance = await CreditService(db).get_balance(company)
    assert balance["held"] == 1.2 and balance["free"] == pytest.approx(3.8)


@pytest.mark.asyncio
async def test_two_runs_cannot_be_admitted_on_the_same_credit(db):
    company = await _company(db, "1.00")
    first, ent1 = await _run(db, company)
    second, ent2 = await _run(db, company)
    guard1, refused1 = await _admit(db, first, ent1, "0.80")
    _, refused2 = await _admit(db, second, ent2, "0.80")
    assert refused1 is None
    assert refused2 and "held by running executions" in refused2   # $0.20 free < $0.50 PROCESS floor
    # The first run settles; its hold is released and the second can start.
    first_row = await db.get(ExecutionRun, first.id)
    first_row.total_cost_usd = Decimal("0")
    await guard1.settle(first_row)
    assert (await _hold(db, first.id)).released_at is not None
    _, refused_again = await _admit(db, second, ent2, "0.80")
    assert refused_again is None


@pytest.mark.asyncio
async def test_a_finished_runs_hold_no_longer_counts(db):
    company = await _company(db, "1.00")
    crashed, ent1 = await _run(db, company)
    await _admit(db, crashed, ent1, "0.90")
    crashed.status = "FAILED"   # finished without settling (e.g. a worker died)
    await db.flush()
    run, ent = await _run(db, company)
    _, refusal = await _admit(db, run, ent, "0.60")
    assert refusal is None


@pytest.mark.asyncio
async def test_the_breaker_stops_the_run_when_its_bill_uses_up_its_credit(db):
    company = await _company(db, "1.00")
    run, ent = await _run(db, company)
    guard, _ = await _admit(db, run, ent, "0.10")
    formula = await formula_for(db, company)  # the company's price formula (Phase 15 T3-2)
    under = Decimal("0.01")
    while formula.rate(under * 2) < Decimal("1.00"):
        under *= 2
    await guard.check(under)                       # billed < $1: continues
    with pytest.raises(CreditExhaustedError, match="Partial results saved"):
        await guard.check(Decimal("5.00"))         # billed > $1: stops


@pytest.mark.asyncio
async def test_other_runs_holds_count_against_the_breaker(db):
    company = await _company(db, "2.00")
    other, ent_o = await _run(db, company)
    await _admit(db, other, ent_o, "1.50")
    run, ent = await _run(db, company, entity_type="ACTION")
    guard, refusal = await _admit(db, run, ent, "0.10")
    assert refusal is None
    formula = await formula_for(db, company)  # the company's price formula (Phase 15 T3-2)
    # $2.00 balance − $1.50 held by the other run leaves $0.50 for this one.
    cost = Decimal("0.60")
    assert formula.rate(cost) >= Decimal("0.50")
    with pytest.raises(CreditExhaustedError):
        await guard.check(cost)


@pytest.mark.asyncio
async def test_a_run_settled_twice_is_charged_once(db):
    """Settlement is keyed by the run (Phase 14 WS2 2.6): the wallet deduction,
    the billing lines and the hold's settlement commit together, and settling
    the same run again — a retried finalisation — charges nothing."""
    from src.ai.governance.governance_service import GovernanceService
    from src.billing.billing_models import BillingLine

    company = await _company(db, "5")
    run, ent = await _run(db, company)
    await _admit(db, run, ent, "1.00")
    run.total_cost_usd = Decimal("0.40")
    run.status = "COMPLETED"
    await _usage(db, run, "0.40")
    await db.flush()

    async def _state():
        billed = (await db.execute(select(BillingLine.billed_usd)
                                   .where(BillingLine.company_id == company)
                                   .execution_options(populate_existing=True))).scalars().all()
        return await available(db, company), [Decimal(str(b)) for b in billed]

    first = await GovernanceService(db, None).settle_billing(run, ent.name)
    after_first = await _state()
    second = await GovernanceService(db, None).settle_billing(run, ent.name)
    assert first > 0 and second == 0
    assert await _state() == after_first
    assert after_first[0] == Decimal("5") - first and after_first[1] == [first]
    hold = await _hold(db, run.id)
    assert hold.settled_at is not None and hold.released_at is not None
    assert Decimal(str(hold.billed_amount)) == first


@pytest.mark.asyncio
async def test_a_run_admitted_without_a_hold_is_settled_once_too(db):
    """A call's run (video frames) has no hold: settlement makes its row."""
    from src.ai.governance.governance_service import GovernanceService

    company = await _company(db, "5")
    run, ent = await _run(db, company, status="COMPLETED")
    run.total_cost_usd = Decimal("0.25")
    await _usage(db, run, "0.25")
    await db.flush()
    assert await GovernanceService(db, None).settle_billing(run, ent.name) > 0
    assert await GovernanceService(db, None).settle_billing(run, ent.name) == 0
    hold = await _hold(db, run.id)
    assert Decimal(str(hold.amount)) == 0 and hold.settled_at is not None


@pytest.mark.asyncio
async def test_child_runs_are_not_gated_separately(db):
    company = await _company(db, "0")
    parent, ent = await _run(db, company)
    child = ExecutionRun(entity_id=ent.id, company_id=company, status="RUNNING", input_data={},
                         parent_run_id=parent.id)
    db.add(child)
    await db.flush()
    guard, refusal = await _admit(db, child, ent, "1.00")
    assert refusal is None
    await guard.check(Decimal("100"))
    assert await _hold(db, child.id) is None


@pytest.mark.asyncio
async def test_triggering_a_run_without_free_credit_is_402(db):
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService
    company = await _company(db, "0")
    ent = HierarchicalEntity(company_id=company, type="AGENT", status="ACTIVE", name="guard-402")
    db.add(ent)
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await AIService(db).trigger_execution(
            ExecutionRunCreate(entity_id=ent.id, input_data={"input": "x"}), company, None,
            user_role="tenant_admin")
    assert exc.value.status_code == 402
    runs = (await db.execute(select(ExecutionRun).where(ExecutionRun.entity_id == ent.id))).scalars().all()
    assert runs == []


async def test_a_partner_starting_its_tenants_agent_starts_the_tenants_run_on_its_credit(db, monkeypatch):
    """D54 (owner, 21 Oct 2026): whose run, whose credits — the tenant's. The partner's own wallet is
    empty; the run is admitted on the tenant's and stamped with the tenant's company."""
    from src.ai.schemas.execution import ExecutionRunCreate
    from src.ai.service import AIService
    from src.auth.models import Company

    async def _queued(*args, **kwargs):
        return None

    monkeypatch.setattr("src.ai.service.enqueue_job", _queued)
    partner = await _company(db, "0")
    (await db.get(Company, partner)).type = "PARTNER"
    tenant = await _company(db, "50")
    (await db.get(Company, tenant)).parent_id = partner
    agent = HierarchicalEntity(company_id=tenant, type="AGENT", status="ACTIVE", name="tenant agent")
    db.add(agent)
    await db.flush()

    run = await AIService(db).trigger_execution(
        ExecutionRunCreate(entity_id=agent.id, input_data={"input": "x"}), partner, uuid.uuid4(),
        user_role="partner_admin")
    assert run.company_id == tenant

    stranger = await _company(db, "50")   # a company the partner cannot see
    other = HierarchicalEntity(company_id=stranger, type="AGENT", status="ACTIVE", name="not theirs")
    db.add(other)
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await AIService(db).trigger_execution(
            ExecutionRunCreate(entity_id=other.id, input_data={"input": "x"}), partner, uuid.uuid4(),
            user_role="partner_admin")
    assert exc.value.status_code == 404
