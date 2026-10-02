"""A plan estimated past the entity's own cost cap does not start (P8.11 —
EP-I9).

The run's start already held the plan's estimate against the wallet (BC-05),
but nothing compared it with the entity's ``governance.max_cost_usd``: a plan
that could not finish inside its cap ran until the cap stopped it halfway,
"Partial results saved". Now such a run fails before any spend, saying why —
a child run too, since its cap is its own.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.credit_guard import CreditGuard

CHILDREN = [{"step_id": f"c{i}", "type": "CHILD_ENTITY_INVOCATION"} for i in range(6)]   # ~$0.60


def _guard(cap, *, child=False):
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), parent_run_id=uuid4() if child else None)
    entity = SimpleNamespace(governance={"max_cost_usd": cap}, logic_gate={})
    return CreditGuard(db=None, redis=None, run=run, entity=entity)


@pytest.mark.asyncio
async def test_a_plan_over_the_cap_is_refused_before_any_spend():
    refusal = await _guard(0.25).admit("AGENT", CHILDREN)
    assert refusal and "estimated at $0.60" in refusal and "max_cost_usd of $0.25" in refusal
    # A child run's cap is its own: refused too, though it holds no credit.
    assert await _guard(0.25, child=True).admit("AGENT", CHILDREN)


@pytest.mark.asyncio
async def test_a_plan_inside_the_cap_goes_on_to_the_credit_hold():
    guard = _guard(5.0, child=True)        # a child skips the wallet hold
    assert guard.over_own_cap(CHILDREN) is None
    assert await guard.admit("AGENT", CHILDREN) is None
    assert _guard(None).over_own_cap(CHILDREN) is None   # no cap, no check
