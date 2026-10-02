"""Every executor runs on its own session (P8.8 — AK-18, EP-20).

``SingleStepExecutor`` opened its own session because a step that commits (a
child run's lifecycle) corrupted the loop's; the DAG, ChildEntity, Debate and
Recursive executors still used the loop's, so a corrupted session surfaced as
a ``PendingRollbackError`` several operations later in code that did nothing
wrong. Now the loop hands every executor a session of its own.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


class _Own:
    """A session the loop opens for one executor call."""
    opened: list["_Own"] = []

    def __init__(self):
        self.closed = False
        _Own.opened.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False


@pytest.mark.asyncio
async def test_the_loop_hands_each_executor_a_session_of_its_own(monkeypatch):
    import src.common.database as database

    handed: list = []

    class _Records:
        name = "SingleStep"

        async def execute(self, move, state, db):
            handed.append(db)
            return ActionResult(success=True, output="ok", cost_usd=Decimal("0"),
                                completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])

    _Own.opened = []
    monkeypatch.setattr(database, "AsyncSessionLocal", _Own)
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(_Records())
    try:
        run = _FakeRun()
        run.entity.planning = {"static_plan": {"enabled": True, "steps": [
            {"step_id": "a", "name": "A", "type": "ACTION"},
            {"step_id": "b", "name": "B", "type": "ACTION", "target": {"input_dependencies": ["a"]}}]},
            "dynamic_planning": {"enabled": False}}
        loop_db = _FakeDB(run)
        loop = AgentLoop(db=loop_db, redis=None, max_iterations=5, feature_flags=FeatureFlags(db=None))
        await loop.run(run.id)
    finally:
        if original is not None:
            register_executor(original)

    assert len(handed) == 2 and all(isinstance(db, _Own) for db in handed)
    assert loop_db not in handed and handed[0] is not handed[1]
    assert all(db.closed for db in handed)
