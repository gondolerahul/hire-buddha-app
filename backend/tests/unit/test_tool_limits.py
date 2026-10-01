"""Per-run tool limits are limits (P3.3).

TL-11 — ``rate_limit_per_run`` was read off the call dict, which no caller ever
         filled, and the counts were reset per step.
TL-21 — ``max_tool_calls`` was a line in the prompt that could go negative.
Found in P3.2 — ``meta_entity_creator``'s runtime-creation cap counted in a
         per-call copy of the context and never fired.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.governance.tool_access import ToolAccess, ToolDenied
from src.ai.tool_executor import ToolExecutor
from src.ai.tools.base import Tool, ToolRegistry


class _Spy(Tool):
    description = "spy"

    def __init__(self, name):
        self.name = name
        self.log: list[str] = []  # a registered tool is frozen (TX-02)

    @property
    def calls(self) -> int:
        return len(self.log)

    async def run(self, input_data):
        self.log.append(input_data)
        return "ok"


@pytest.fixture
def spies():
    made = {n: _Spy(n) for n in ("p33_a", "p33_b")}
    for t in made.values():
        ToolRegistry.register(t)
    yield made
    for t in made.values():
        ToolRegistry._tools.pop(t.name, None)


def _entity(*grants, governance=None, meta=None, meta_agent=False, etype="ACTION"):
    return SimpleNamespace(
        id=uuid4(), name="limits", type=etype,
        capabilities={"tools": list(grants), "meta_cognition": meta or {}},
        planning={}, logic_gate={}, governance=governance or {},
        metadata_extensions={"is_meta_agent": True} if meta_agent else {},
    )


async def _load(entity, *, db=None, run_id=None) -> ToolAccess:
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=False)
    return await ToolAccess.load(db, uuid4(), entity, feature_flags=flags, run_id=run_id)


async def _call(access, name):
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": name, "args": {"input": "x"}}], access=access)
    if not tr.skipped:
        access.record(tr.tool)  # what the step executor does when it logs the call
    return tr


@pytest.mark.asyncio
async def test_a_grants_rate_limit_stops_the_extra_call(spies):
    access = await _load(_entity({"tool_id": "p33_a", "rate_limit_per_run": 2}))
    results = [await _call(access, "p33_a") for _ in range(3)]
    assert [r.success for r in results] == [True, True, False]
    assert results[2].skip_reason == "rate_limited" and "2 time(s) per run" in results[2].output
    assert spies["p33_a"].calls == 2


@pytest.mark.asyncio
async def test_max_tool_calls_is_a_limit_across_tools(spies):
    access = await _load(_entity({"tool_id": "p33_a"}, {"tool_id": "p33_b"},
                                 governance={"execution_limits": {"max_tool_calls": 2}}))
    assert access.calls_left() == 2
    await _call(access, "p33_a")
    await _call(access, "p33_b")
    third = await _call(access, "p33_a")
    assert third.skip_reason == "call_budget"
    assert spies["p33_a"].calls + spies["p33_b"].calls == 2
    assert access.calls_left() == 0
    assert access.schemas() == []  # the model is no longer offered tools it cannot call


@pytest.mark.asyncio
async def test_the_runs_earlier_calls_count(spies):
    """The count is read from the run's log rows, so it survives steps,
    suspends and workers; refused calls are not counted."""
    db = MagicMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = []          # nothing disabled
    counts = MagicMock()
    counts.all.return_value = [("p33_a", 1), ("web_search→p33_b", 1)]
    db.execute = AsyncMock(side_effect=[rows, counts])
    access = await _load(_entity({"tool_id": "p33_a", "rate_limit_per_run": 1}), db=db, run_id=uuid4())
    assert access.used == {"p33_a": 1, "web_search": 1, "p33_b": 1}
    assert (await _call(access, "p33_a")).skip_reason == "rate_limited"
    stmt = db.execute.await_args_list[1].args[0]
    assert "tool_interaction_logs" in str(stmt) and "refused" in stmt.compile().params.values()


@pytest.mark.asyncio
async def test_a_refused_call_does_not_count(spies):
    access = await _load(_entity({"tool_id": "p33_a"},
                                 governance={"execution_limits": {"max_tool_calls": 1}}))
    refused = await _call(access, "not_granted_tool")
    assert refused.skipped and access.calls_left() == 1
    assert (await _call(access, "p33_a")).success is True


@pytest.mark.asyncio
async def test_runtime_creations_are_capped_for_an_entity_that_is_not_the_meta_agent():
    entity = _entity(etype="AGENT", meta={"self_modification": True, "max_runtime_creations": 1})
    access = await _load(entity)
    assert not isinstance(access.resolve("meta_entity_creator"), ToolDenied)
    access.record("meta_entity_creator")
    denied = access.resolve("meta_entity_creator")
    assert isinstance(denied, ToolDenied) and denied.reason == "rate_limited"


@pytest.mark.asyncio
async def test_the_meta_agent_has_no_creation_cap():
    entity = _entity(etype="AGENT", meta={"max_runtime_creations": 1}, meta_agent=True)
    access = await _load(entity)
    for _ in range(3):
        access.record("meta_entity_creator")
    assert not isinstance(access.resolve("meta_entity_creator"), ToolDenied)


@pytest.mark.asyncio
async def test_the_creator_no_longer_keeps_its_own_counter():
    """The in-tool counter is gone: it lived in a per-call copy of the context."""
    import inspect
    from src.ai.tools.meta import entity_creator
    assert "__meta_runtime_creations_" not in inspect.getsource(entity_creator)


def test_there_is_no_per_call_rate_limit_plumbing_left():
    import inspect
    assert "call_counts" not in inspect.signature(ToolExecutor.execute_from_function_calls).parameters
