"""AK-07 — governance.max_concurrent_children bounds a parent's fan-out.

The cap was computed, logged and ignored; and since the parent dispatched one
child per move and waited for it, independent children never ran together
anyway. The ready children of a move are now dispatched together, up to the
entity's cap, and the parent waits for the batch.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.schemas.enums import RunStatus


def _entity(cap):
    steps = [{"step_id": f"c{i}", "name": f"Child {i}", "type": "CHILD_ENTITY_INVOCATION",
              "target": {"entity_id": str(uuid4())}} for i in range(1, 6)]
    return SimpleNamespace(
        id=uuid4(), company_id=uuid4(), name="fan-out", type="PROCESS", goal="g", description="d",
        identity=None, hierarchy=None, logic_gate=None,
        planning={"static_plan": {"enabled": True, "steps": steps}},
        capabilities=None,
        governance={"max_cost_usd": 5.0, "timeout_ms": 600_000, "max_concurrent_children": cap},
        io_contract=None, observability=None, metadata_extensions=None,
    )


class _Run:
    def __init__(self, entity):
        self.id, self.entity_id, self.company_id = uuid4(), entity.id, entity.company_id
        self.user_id = self.parent_run_id = None
        self.status = RunStatus.PENDING.value
        self.input_data = {"input": "go"}
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


class _Dispatcher:
    name = "ChildEntity"

    def __init__(self):
        self.batches: list[list[str]] = []

    async def execute(self, move, state, db):  # noqa: ARG002
        ids = [s["step_id"] for s in move.plan_fragment]
        self.batches.append(ids)
        return ActionResult(success=True, awaiting_children=[
            {"run_id": str(uuid4()), "step_id": sid, "status": "PENDING"} for sid in ids])


@pytest.fixture
def dispatcher(monkeypatch):
    from src.ai.core.credit_guard import CreditGuard

    async def _admitted(self, *args, **kwargs):
        return None

    monkeypatch.setattr(CreditGuard, "admit", _admitted)
    monkeypatch.setattr(CreditGuard, "check", _admitted)
    original = EXECUTOR_REGISTRY.get("ChildEntity")
    fake = _Dispatcher()
    register_executor(fake)
    try:
        yield fake
    finally:
        if original is not None:
            register_executor(original)


@pytest.mark.asyncio
@pytest.mark.parametrize("cap, first_batch", [(2, ["c1", "c2"]), (8, ["c1", "c2", "c3", "c4", "c5"])])
async def test_the_entitys_cap_bounds_the_first_batch(dispatcher, cap, first_batch) -> None:
    entity = _entity(cap)
    run = _Run(entity)
    loop = AgentLoop(db=_DB(run), redis=None, max_iterations=5, feature_flags=FeatureFlags(db=None))
    outcome = await loop.run(run.id)

    assert outcome["status"] == RunStatus.WAITING_ON_CHILDREN.value
    assert dispatcher.batches == [first_batch]
