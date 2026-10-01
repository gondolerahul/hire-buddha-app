"""R1 / EP-26 — every level resolves and runs its plan the same way.

An entity with no plan used to be handled by its type: ACTION and SKILL got a
default step, an AGENT was "planned" and stamped COMPLETED with output "Success"
when nothing came of it, and a PROCESS (or a LOOP, a GRAPH) with no planning
blocks idled through no-op iterations until the cap. Now, at every level: the
static plan, else a dynamic plan, else delegation when it has children and no
tools, else one default step — and a run that still has no plan fails, saying
why.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.events import capture_test_events
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.default_step import default_step, display_planning
from src.ai.planning.planner_service import PlannerService
from src.ai.schemas.enums import EntityType, RunStatus

LEVELS = [t.value for t in EntityType]


def _entity(type_: str, *, tools=None, planning=None, io_contract=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), company_id=uuid4(), name=f"planless-{type_.lower()}", type=type_,
        goal="Answer the request.", description=f"The {type_.lower()} that answers requests.",
        identity=None, hierarchy=None, logic_gate=None,
        planning=planning if planning is not None else {},
        capabilities={"tools": tools} if tools else None,
        governance={"max_cost_usd": 5.0, "timeout_ms": 600_000},
        io_contract=io_contract, observability=None, metadata_extensions=None,
    )


def _no_children():
    return patch("src.ai.meta.platform_schema_compiler.load_entity_children", AsyncMock(return_value=[]))


# ── The planner ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("level", LEVELS)
async def test_a_planless_entity_gets_one_default_step_at_every_level(level) -> None:
    entity = _entity(level)
    with _no_children():
        plan = await PlannerService(AsyncMock(), company_id=uuid4()).reconcile(MagicMock(), entity, {"input": "hi"})
    assert [s["step_id"] for s in plan["steps"]] == ["auto_generated"]
    step = plan["steps"][0]
    assert step["type"] == "ACTION"
    assert step["target"]["prompt_template"] == "{{input}}"
    assert step["description"] == entity.description


def test_the_default_step_reads_the_declared_inputs() -> None:
    entity = _entity("AGENT", io_contract={"input_schema": {"properties": {"topic": {}, "audience": {}}}})
    assert default_step(entity)["target"]["prompt_template"] == "topic: {{topic}}\naudience: {{audience}}"
    only_input = _entity("AGENT", io_contract={"input_schema": {"properties": {"input": {}}}})
    assert default_step(only_input)["target"]["prompt_template"] == "{{input}}"


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["ACTION", "SKILL", "AGENT", "PROCESS", "LOOP", "GRAPH"])
async def test_children_and_no_tools_delegates_at_every_level(level) -> None:
    child = SimpleNamespace(id=uuid4(), name="child", type="ACTION", goal="g", description="d")
    service = PlannerService(AsyncMock(), company_id=uuid4())
    routed = [{"entity_id": str(child.id), "name": "child", "instruction": "do it"}]
    with patch("src.ai.meta.platform_schema_compiler.load_entity_children", AsyncMock(return_value=[child])), \
         patch.object(service, "_route_children_llm", AsyncMock(return_value=routed)):
        plan = await service.reconcile(MagicMock(), _entity(level), {"input": "hi"})
    assert [s["type"] for s in plan["steps"]] == ["CHILD_ENTITY_INVOCATION"]
    assert plan["steps"][0]["target"]["entity_id"] == str(child.id)


@pytest.mark.asyncio
async def test_an_entity_with_its_own_tools_is_not_forced_to_delegate() -> None:
    """The rule is tools, not type: a PROCESS that binds tools used to be forced."""
    child = SimpleNamespace(id=uuid4(), name="child", type="AGENT", goal="g", description="d")
    service = PlannerService(AsyncMock(), company_id=uuid4())
    static = {"static_plan": {"steps": [{"step_id": "s1", "name": "Work", "type": "TOOL_CALL",
                                         "target": {"tool_id": "web_search"}}]}}
    entity = _entity("PROCESS", tools=[{"tool_id": "web_search"}], planning=static)
    with patch("src.ai.meta.platform_schema_compiler.load_entity_children", AsyncMock(return_value=[child])), \
         patch.object(service, "_route_children_llm",
                      AsyncMock(return_value=[{"entity_id": str(child.id), "instruction": "x"}])):
        plan = await service.reconcile(MagicMock(), entity, {"input": "hi"})
    assert [s["step_id"] for s in plan["steps"]] == ["s1"]


def test_the_display_plan_is_a_copy_with_the_default_step() -> None:
    entity = _entity("PROCESS", planning={"dynamic_planning": {"enabled": False}})
    shown = display_planning(entity)
    assert shown["static_plan"]["steps"][0]["step_id"] == "auto_generated"
    assert shown["dynamic_planning"] == {"enabled": False}
    assert entity.planning == {"dynamic_planning": {"enabled": False}}      # the row is untouched
    authored = _entity("AGENT", planning={"static_plan": {"steps": [{"step_id": "s1"}]}})
    assert display_planning(authored) is authored.planning


# ── The loop ────────────────────────────────────────────────────────────────

class _Run:
    def __init__(self, entity):
        self.id, self.entity_id, self.company_id = uuid4(), entity.id, entity.company_id
        self.user_id = self.parent_run_id = None
        self.status = RunStatus.PENDING.value
        self.input_data = {"input": "summarise the quarter"}
        self.dynamic_plan = self.result_data = self.context_state = self.error_message = None
        self.total_cost_usd, self.total_tokens = Decimal("0"), 0
        self.started_at = self.completed_at = None
        self.entity = entity


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _DB:
    def __init__(self, run):
        self.run = run

    async def execute(self, *_a, **_k):
        return _Result(self.run)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, _obj):
        return


class _StepRunner:
    name = "SingleStep"

    def __init__(self):
        self.fragments: list = []

    async def execute(self, move, state, db):  # noqa: ARG002
        self.fragments.append(move.plan_fragment)
        done = [str(move.plan_fragment[0]["step_id"])] if move.plan_fragment else []
        return ActionResult(output="the quarter, summarised", cost_usd=Decimal("0.01"),
                            latency_ms=5, success=True, completed_step_ids=done)


@pytest.fixture
def step_runner(monkeypatch):
    from src.ai.core.credit_guard import CreditGuard

    async def _admitted(self, *args, **kwargs):
        return None

    monkeypatch.setattr(CreditGuard, "admit", _admitted)
    monkeypatch.setattr(CreditGuard, "check", _admitted)
    original = EXECUTOR_REGISTRY.get("SingleStep")
    runner = _StepRunner()
    register_executor(runner)
    try:
        yield runner
    finally:
        if original is not None:
            register_executor(original)


@pytest.mark.asyncio
@pytest.mark.parametrize("level", LEVELS)
async def test_a_planless_entity_does_its_work_at_every_level(step_runner, level) -> None:
    entity = _entity(level)            # no static plan, no dynamic planning, no children
    run = _Run(entity)
    loop = AgentLoop(db=_DB(run), redis=None, max_iterations=10, feature_flags=FeatureFlags(db=None))
    with _no_children(), capture_test_events() as events:
        outcome = await loop.run(run.id)

    assert "agent.loop.plan_reconciled" in [e.name for e in events]
    assert step_runner.fragments and step_runner.fragments[0][0]["step_id"] == "auto_generated"
    assert outcome["status"] == RunStatus.COMPLETED.value
    assert outcome["iterations"] <= 2


@pytest.mark.asyncio
async def test_a_run_that_cannot_be_planned_fails_with_the_reason(step_runner, monkeypatch) -> None:
    async def _down(self, *_a):
        raise RuntimeError("planner down")

    monkeypatch.setattr(PlannerService, "reconcile", _down)
    entity = _entity("AGENT")
    run = _Run(entity)
    loop = AgentLoop(db=_DB(run), redis=None, max_iterations=10, feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)

    assert outcome["status"] == RunStatus.FAILED.value
    assert outcome["iterations"] == 1                 # not the iteration cap
    assert "planner down" in (run.error_message or "")
    assert step_runner.fragments == []
