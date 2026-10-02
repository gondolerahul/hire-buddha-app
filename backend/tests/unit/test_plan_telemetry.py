"""Planning is visible in the run's trace (P7.9 — PC-13, PC-14).

``PlanGenerator`` emits ``agent.plan.*`` events — candidates, invariant
violations, the judge's choice — through an ``emit_event`` hook that every
caller left unset, so no planning event ever fired. ``PlanGenerator.replan``
had no caller (and built its context without the entity); replans run through
``PlannerService.adapt_plan``, which since PC-20 passes the entity and run.
Now both planning paths hand the generator an emitter bound to the run, the
replan path says so with ``agent.plan.replan``, and the dead method is gone.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.core.events import capture_test_events


@pytest.mark.asyncio
async def test_a_replan_emits_planning_events_for_its_run(monkeypatch):
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.planning.plan_generator import PlanGenerator
    from src.ai.planning.planner_service import PlannerService

    async def _generate(self, ctx, n=None):
        await self._emit("agent.plan.chosen", style="DAG_SEQUENTIAL")
        return SimpleNamespace(chosen=SimpleNamespace(steps=[{"name": "Write", "type": "ACTION"}]))

    monkeypatch.setattr(PlanGenerator, "generate", _generate)
    monkeypatch.setattr(FeatureFlags, "is_on", AsyncMock(return_value=True))
    svc = PlannerService(MagicMock(), company_id=uuid4())
    run_id = uuid4()
    with capture_test_events() as evts:
        new_plan = await svc.adapt_plan(
            original_plan=[{"step_id": "s1", "name": "Research"}, {"step_id": "s2", "name": "Write"}],
            completed_steps=[{"step_id": "s1", "name": "s1", "output": "notes"}],
            failed_step={"name": "supervisor_request", "error": "too long"}, goal="report",
            entity=None, run_id=run_id)

    assert new_plan and new_plan[0]["name"] == "Write"
    by_name = {e.name: e.payload for e in evts}
    assert by_name["agent.plan.chosen"]["run_id"] == str(run_id)
    assert by_name["agent.plan.replan"] == {"run_id": str(run_id), "by": "supervisor_request",
                                             "new_steps": 1, "kept": 1}


def test_the_unused_replan_path_is_gone():
    from src.ai.planning.plan_generator import PlanGenerator
    assert not hasattr(PlanGenerator, "replan") and not hasattr(PlanGenerator, "_ctx_from_state")
