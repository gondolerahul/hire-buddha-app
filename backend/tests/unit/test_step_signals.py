"""What the loop tells a step is typed, not keys in the context dict (P8.9 —
AK-21, D22).

The loop copied the run's context out for each executor with an
``__agent_state__`` key added (iteration, budget pressure, open subgoals), and
copied the whole dict back: every value in two places, and loop plumbing in
the dict a prompt is built from. Now the dict is data, the loop's signals ride
in a ContextVar around each executor call — seen by parallel branches, copied
back by nothing — and a meta tool still gets ``__agent_state__`` from them.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


@pytest.mark.asyncio
async def test_a_step_reads_the_loops_signals_and_the_dict_stays_data():
    from src.ai.core.step_signals import current_signals
    from src.ai.governance.tool_access import ExecutionContext

    seen: dict = {}

    class _Reads:
        name = "SingleStep"

        async def execute(self, move, state, db):  # noqa: ARG002
            ctx = await state.materialise_context_dict()
            seen["dict_keys"] = set(ctx)

            async def _branch():                     # a parallel DAG branch is its own task
                return current_signals()
            seen["signals"] = current_signals()
            seen["branch"] = await asyncio.create_task(_branch())
            seen["tool_ctx"] = ExecutionContext.for_run(
                type("R", (), {"company_id": "c", "user_id": None, "id": "r"})(),
                type("E", (), {"id": "e", "name": "n", "metadata_extensions": {}, "governance": {},
                               "capabilities": {}})(), ctx).as_tool_context()
            state.subjects_block = "## Subjects\n- contact c_1 — Asha"
            return ActionResult(success=True, output="ok", cost_usd=Decimal("0"),
                                completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])

    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(_Reads())
    try:
        run = _FakeRun()
        run.entity.planning = {"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "name": "Draft", "type": "ACTION"}]}, "dynamic_planning": {"enabled": False}}
        await AgentLoop(db=_FakeDB(run), redis=None, max_iterations=4, feature_flags=FeatureFlags(db=None)).run(run.id)
    finally:
        if original is not None:
            register_executor(original)

    signals = seen["signals"]
    assert signals.iteration == 1 and signals.budget_pressure is not None
    assert signals.step_names == {"Draft": "s1"}
    assert seen["branch"] is signals                              # the branch sees the same signals
    assert "__agent_state__" not in seen["dict_keys"]
    assert seen["tool_ctx"]["__agent_state__"]["iteration"] == 1  # a meta tool still reads it
    from src.ai.core.step_signals import current_signals as now
    assert now() is None                                          # nothing outlives the call
