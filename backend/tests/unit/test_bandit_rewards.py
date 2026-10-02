"""The bandit is rewarded per pull, for what it chose (P7.10 — PC-15, PC-21).

Every move the Strategist made was recorded as a "pull" — a child step, a
debate, planning the goal — though the bandit only ever chose between a
parallel and a sequential DAG. At the run's end each arm used was updated
once with the *run's* success and an even share of the run's whole cost, so
an arm used once in a long run that failed for another reason took a full
penalty. Now only the bandit's choices are pulls, each rewarded with its own
iteration's outcome and cost.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState, Budget
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.plan_style_bandit import PlanStyleBandit
from src.ai.schemas.enums import EntityType, RunStatus

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


@pytest.mark.asyncio
async def test_each_pull_gets_its_own_iterations_outcome():
    bandit = PlanStyleBandit()          # in memory
    loop = AgentLoop(db=None, redis=None, feature_flags=FeatureFlags(db=None))
    loop.bandit = bandit
    state = AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(), entity_type=EntityType.AGENT,
                       budget=Budget.from_governance(max_cost_usd=5.0, timeout_ms=60_000))
    state.bandit_pulls = [
        {"arm": "DAG_PARALLEL", "iteration": 1, "success": True, "cost_usd": 0.02},
        {"arm": "DAG_SEQUENTIAL", "iteration": 4, "success": False, "cost_usd": 0.30},
    ]
    # The run failed: under the old reward both arms would have been failures,
    # each charged half the run's cost.
    await loop._finalize_bandit(state, RunStatus.FAILED.value)

    table = await bandit.load_table(state.entity_id, state.task_class)
    par, seq = table.arms["DAG_PARALLEL"], table.arms["DAG_SEQUENTIAL"]
    assert (par.pulls, par.successes, par.avg_cost_usd) == (1, 1, 0.02)
    assert (seq.pulls, seq.successes, seq.avg_cost_usd) == (1, 0, 0.30)
    assert set(table.arms) == {"DAG_PARALLEL", "DAG_SEQUENTIAL"}


@pytest.mark.asyncio
async def test_the_loop_records_the_bandits_choice_with_its_iteration(monkeypatch):
    import random
    from decimal import Decimal
    from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor

    class _Done:
        def __init__(self, name):
            self.name = name

        async def execute(self, move, state, db):  # noqa: ARG002
            return ActionResult(success=True, output="ok", cost_usd=Decimal("0.01"),
                                completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])

    originals = {n: EXECUTOR_REGISTRY.get(n) for n in ("SingleStep", "DAG")}
    for n in originals:
        register_executor(_Done(n))
    bandit = PlanStyleBandit(epsilon=0.0, rng=random.Random(1))

    async def _bandit(self, state):  # noqa: ARG001
        return bandit

    monkeypatch.setattr(AgentLoop, "_build_bandit", _bandit)
    try:
        run = _FakeRun()
        run.entity.planning = {"static_plan": {"enabled": True, "steps": [
            {"step_id": "a", "name": "A", "type": "ACTION"}, {"step_id": "b", "name": "B", "type": "ACTION"}]},
            "dynamic_planning": {"enabled": False}}
        loop = AgentLoop(db=_FakeDB(run), redis=None, max_iterations=10, feature_flags=FeatureFlags(db=None))
        await loop.run(run.id)
    finally:
        for n, ex in originals.items():
            if ex is not None:
                register_executor(ex)

    [table] = bandit._memory_tables.values()
    pulled = {arm: st for arm, st in table.arms.items() if st.pulls}
    assert len(pulled) == 1 and next(iter(pulled.values())).successes == 1
    assert next(iter(pulled.values())).avg_cost_usd == pytest.approx(0.01)
