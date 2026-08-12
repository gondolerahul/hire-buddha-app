"""RecursiveExecutor re-platform (C4 PR-7).

The loop's RecursiveExecutor must map a goal-only AGENT onto a plan via the
PlannerService and never hand the run to the legacy ``execute_run``. When the
goal yields a plan, it populates ``state.plan_steps`` for the loop's plan-driven
path; when it yields nothing, it completes cleanly with the sentinel output.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState
from src.ai.core.budget import Budget
from src.ai.schemas.enums import EntityType


def _state() -> AgentState:
    return AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.AGENT, budget=Budget(),
    )


class _Run:
    input_data: dict = {}
    dynamic_plan: dict | None = None
    total_cost_usd = 0

    def __init__(self) -> None:
        self.entity = type("E", (), {"goal": "g", "name": "n"})()


class _FakeDB:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


@pytest.mark.asyncio
async def test_recursive_executor_maps_goal_onto_plan(monkeypatch) -> None:
    import src.ai.planning.planner_service as ps_mod
    from src.ai.core.executors.recursive import RecursiveExecutor

    plan = {"steps": [{"step_id": "step_1", "name": "do it", "type": "THOUGHT"}]}

    class _FakePlanner:
        def __init__(self, db, company_id=None):     # noqa: ANN001, ARG002
            pass

        async def reconcile(self, run, entity, input_data):  # noqa: ANN001, ARG002
            return plan

    monkeypatch.setattr(ps_mod, "PlannerService", _FakePlanner)

    run = _Run()

    async def _fake_reload(db, run_id):              # noqa: ANN001, ARG001
        return run

    monkeypatch.setattr(RecursiveExecutor, "_reload_run", staticmethod(_fake_reload))

    state = _state()
    result = await RecursiveExecutor().execute(None, state, db=_FakeDB())

    assert result.success is True
    assert state.plan_steps == plan["steps"]   # handed to the loop's plan path
    assert run.dynamic_plan == plan


@pytest.mark.asyncio
async def test_recursive_executor_no_plan_completes_with_sentinel(monkeypatch) -> None:
    import src.ai.planning.planner_service as ps_mod
    from src.ai.core.executors.recursive import RecursiveExecutor

    class _FakePlanner:
        def __init__(self, db, company_id=None):     # noqa: ANN001, ARG002
            pass

        async def reconcile(self, run, entity, input_data):  # noqa: ANN001, ARG002
            return {"steps": []}

    monkeypatch.setattr(ps_mod, "PlannerService", _FakePlanner)

    async def _fake_reload(db, run_id):              # noqa: ANN001, ARG001
        return _Run()

    monkeypatch.setattr(RecursiveExecutor, "_reload_run", staticmethod(_fake_reload))

    state = _state()
    result = await RecursiveExecutor().execute(None, state, db=_FakeDB())

    assert result.success is True
    assert result.output == "Success"
    assert state.plan_steps == []   # nothing to dispatch; loop winds down to DONE
