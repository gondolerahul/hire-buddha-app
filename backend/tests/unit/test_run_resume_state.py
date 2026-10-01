"""EP-29 — the loop shares its tree and honours reused steps.

The loop opened the run's tree into ``AgentState.cortex_tree_id`` only, so the
``__cortex_tree_id__`` key that ``create_child_run``, retry and refine read was
never there; and the ``__reuse_outputs__`` a retry or refine passes had no
reader, so every step ran again.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags

from tests.unit.test_agent_loop_billing_and_fallback import (  # noqa: F401
    _FakeDB,
    _FakeRun,
    _no_credit_gate,
    _static_entity,
)


class _Recorder:
    name = "SingleStep"

    def __init__(self):
        self.ran: list[str] = []
        self.tree_ids: list = []

    async def execute(self, move, state, db):  # noqa: ARG002
        sid = str(move.plan_fragment[0]["step_id"])
        self.ran.append(sid)
        self.tree_ids.append((await state.materialise_context_dict()).get("__cortex_tree_id__"))
        return ActionResult(output=f"out {sid}", cost_usd=Decimal("0"), completed_step_ids=[sid])


@pytest.fixture
def recorder(monkeypatch):
    original = EXECUTOR_REGISTRY.get("SingleStep")
    rec = _Recorder()
    register_executor(rec)

    async def _settle(self, run, name):  # noqa: ARG001
        return Decimal("0")

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(GovernanceService, "settle_billing", _settle)
    try:
        yield rec
    finally:
        if original is not None:
            register_executor(original)


def _two_step_entity():
    entity = _static_entity(uuid4(), uuid4())
    entity.planning = {"static_plan": {"enabled": True, "steps": [
        {"step_id": "s1", "order": 1, "name": "search", "type": "ACTION", "required": True},
        {"step_id": "s2", "order": 2, "name": "write", "type": "ACTION", "required": True,
         "target": {"input_dependencies": ["s1"]}},
    ]}}
    return entity


@pytest.mark.asyncio
async def test_the_tree_id_reaches_the_executors_and_the_run_row(recorder, monkeypatch):
    tree = SimpleNamespace(id=uuid4(), root_node_id=None)

    async def _open(db, state, entity, run_id):  # noqa: ARG001
        return None, tree

    monkeypatch.setattr("src.ai.memory.run_memory.open_run_tree", _open)
    run = _FakeRun(_two_step_entity())
    await AgentLoop(db=_FakeDB(run), redis=None, feature_flags=FeatureFlags(db=None)).run(run.id)

    assert recorder.tree_ids and all(t == str(tree.id) for t in recorder.tree_ids)
    assert (run.context_state or {}).get("__cortex_tree_id__") == str(tree.id)


@pytest.mark.asyncio
async def test_reused_steps_are_not_run_again(recorder):
    run = _FakeRun(_two_step_entity())
    run.input_data = {"input": "go", "__reuse_outputs__": {"s1": "five sources"}}
    await AgentLoop(db=_FakeDB(run), redis=None, feature_flags=FeatureFlags(db=None)).run(run.id)

    assert recorder.ran == ["s2"]
    assert run.status == "COMPLETED"
    steps = run.result_data["steps"]
    assert steps[0]["step_id"] == "s1" and steps[0]["reused"] and steps[0]["output"] == "five sources"
