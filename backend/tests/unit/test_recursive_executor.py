"""RecursiveExecutor — plans an entity that reached the loop without a plan.

It maps the goal onto a plan via the PlannerService and never hands the run to
the legacy ``execute_run``. When the goal yields a plan, it populates
``state.plan_steps`` for the loop's plan-driven path; when nothing can be
planned it fails with the reason — it used to report "Success" for work it never
did (EP-26).
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
@pytest.mark.parametrize("reconcile_result, reason", [
    ({"steps": []}, "No plan could be made for this entity"),
    (RuntimeError("planner down"), "RuntimeError: planner down"),
])
async def test_recursive_executor_without_a_plan_fails_with_the_reason(
    monkeypatch, reconcile_result, reason,
) -> None:
    import src.ai.planning.planner_service as ps_mod
    from src.ai.core.executors.recursive import RecursiveExecutor

    class _FakePlanner:
        def __init__(self, db, company_id=None):     # noqa: ANN001, ARG002
            pass

        async def reconcile(self, run, entity, input_data):  # noqa: ANN001, ARG002
            if isinstance(reconcile_result, Exception):
                raise reconcile_result
            return reconcile_result

    monkeypatch.setattr(ps_mod, "PlannerService", _FakePlanner)

    run = _Run()

    async def _fake_reload(db, run_id):              # noqa: ANN001, ARG001
        return run

    monkeypatch.setattr(RecursiveExecutor, "_reload_run", staticmethod(_fake_reload))

    state = _state()
    result = await RecursiveExecutor().execute(None, state, db=_FakeDB())

    assert result.success is False
    assert reason in (result.error or "")
    assert result.output != "Success"
    assert state.plan_steps == []
    assert run.dynamic_plan is None
