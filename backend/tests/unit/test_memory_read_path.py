"""MC-01 — the memory read path.

Memory assembled at the start of a run must reach the step prompt, the
critics (post critic and supervisor) and the planner.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.ai.memory.assembler import assemble_memory
from src.ai.memory.run_memory import (
    RunMemory, assemble_run_memory, memory_scope_for, open_run_tree,
)
from src.ai.step_executor import prompt_context_block


def _entity(memory: dict | None) -> SimpleNamespace:
    caps = {"memory": memory} if memory is not None else {}
    return SimpleNamespace(capabilities=caps, goal="Answer the question", name="researcher")


# ---------------------------------------------------------------------------
# Entity memory config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("memory, expected", [
    (None, None),
    ({"enabled": False, "memory_scope": "FULL"}, None),
    ({"enabled": True}, "FULL"),
    ({"enabled": True, "memory_scope": "run_scoped"}, "RUN_SCOPED"),
    ({"enabled": True, "memory_scope": "NONE"}, None),
])
def test_memory_scope_for(memory, expected) -> None:
    assert memory_scope_for(_entity(memory)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("scope, domains", [
    ("FULL", ["knowledge", "experience", "intelligence", "episodic"]),
    ("RUN_SCOPED", ["knowledge"]),
    ("INTELLIGENCE_ONLY", ["intelligence"]),
])
async def test_scope_selects_domains(scope, domains) -> None:
    assembler = MagicMock()
    assembler.assemble_runtime_memory = AsyncMock(return_value=SimpleNamespace(
        formatted_prompt="", intelligence_rules=[], episodic_context=[],
        knowledge_refs=[], experience_suggestions=[],
    ))
    with patch("src.ai.memory.memory_assembly_service.MemoryAssemblyService",
               return_value=assembler):
        await assemble_memory(MagicMock(), uuid4(), uuid4(), memory_scope=scope)
    assert assembler.assemble_runtime_memory.call_args.kwargs["include_domains"] == domains


# ---------------------------------------------------------------------------
# RunMemory — the reader the critics consume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_memory_serves_rules_and_runs() -> None:
    mem = RunMemory({
        "__intelligence_rules__": [{"title": f"r{i}", "rule": f"rule {i}"} for i in range(8)],
        "__episodic_memory__": [{"input": "Q2 revenue", "output": "grew 8%",
                                 "status": "COMPLETED", "at": "2026-09-01T10:00:00"}],
    })
    rules = await mem.intelligence_rules(entity_id=uuid4(), top_k=5)
    assert [r["title"] for r in rules] == ["r0", "r1", "r2", "r3", "r4"]
    runs = await mem.similar_runs(entity_id=uuid4(), top_k=3)
    assert runs == [{"summary": "[COMPLETED] Q2 revenue → grew 8%", "at": "2026-09-01T10:00:00"}]


@pytest.mark.asyncio
async def test_the_supervisor_reads_rules_from_run_memory_without_retired_ones() -> None:
    """AK-05: the Perceiver is gone; the supervisor reads the run's memory, and
    the lifecycle filter it applied (retired rules out) now happens there."""
    from src.ai.core.agent_state import AgentState, Budget
    from src.ai.planning.supervisor_critic import SupervisorCritic
    from src.ai.schemas.enums import EntityType

    mem = RunMemory({"__intelligence_rules__": [
        {"title": "Verify figures", "rule": "Check the source"},
        {"title": "Old", "rule": "Use the v1 API", "lifecycle": "retired"}]})
    assert [r["title"] for r in await mem.top_rules(3)] == ["Verify figures"]

    seen: dict = {}

    class _LLM:
        async def call_llm(self, **kw):
            seen["prompt"] = kw["user_prompt"]
            return SimpleNamespace(output='{"recommendation": "CONTINUE", "confidence": 0.9}',
                                   cost_usd=0, prompt_tokens=1, completion_tokens=1)

    state = AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(), entity_type=EntityType.AGENT,
                       budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))
    state.iteration = 3
    critic = SupervisorCritic(llm_router=_LLM(), intelligence_reader=mem)
    critic.config.fast_path_enabled = False
    await critic.assess(state)
    assert "Check the source" in seen["prompt"] and "v1 API" not in seen["prompt"]


# ---------------------------------------------------------------------------
# The run's tree + memory are set up once per run
# ---------------------------------------------------------------------------


def _db():
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _state(**ctx):
    return SimpleNamespace(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
                           context_state=dict(ctx))


@pytest.mark.asyncio
async def test_open_run_tree_creates_tree_for_run_input() -> None:
    db = _db()
    user_id = uuid4()
    run_row = MagicMock()
    run_row.first.return_value = SimpleNamespace(input_data={"input": "EV batteries"},
                                                 user_id=user_id)
    db.execute = AsyncMock(return_value=run_row)
    tree = SimpleNamespace(id=uuid4(), root_node_id=uuid4())
    cortex = MagicMock()
    cortex.create_tree = AsyncMock(return_value=tree)
    state = _state()
    with patch("src.ai.memory.cortex_service.CortexService", return_value=cortex):
        got_cortex, got_tree = await open_run_tree(db, state, _entity(None), uuid4())
    assert (got_cortex, got_tree) == (cortex, tree)
    cortex.create_tree.assert_awaited_once_with(
        entity_id=state.entity_id, user_id=user_id, task_description="EV batteries",
    )
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_open_run_tree_failure_disables_persistence() -> None:
    db = _db()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    with patch("src.ai.memory.cortex_service.CortexService"):
        assert await open_run_tree(db, _state(), _entity(None), uuid4()) == (None, None)


@pytest.mark.asyncio
async def test_run_memory_is_assembled_into_context() -> None:
    db, state = _db(), _state(input="Research the EV battery market")
    tree = SimpleNamespace(id=uuid4())
    assembled = {"__memory__": "## Learned Intelligence\n  📏 [80%] Cite sources",
                 "__intelligence_rules__": [{"title": "Cite sources"}]}
    with patch("src.ai.memory.assembler.assemble_memory",
               new=AsyncMock(return_value=assembled)) as assemble, \
         patch("src.ai.core.agent_loop_sse.event_async", new=AsyncMock()):
        mem = await assemble_run_memory(
            db, state, entity=_entity({"enabled": True, "memory_scope": "FULL"}),
            runtime_tree=tree,
        )

    kwargs = assemble.call_args.kwargs
    assert kwargs["task_description"] == "Research the EV battery market"
    assert kwargs["memory_scope"] == "FULL"
    assert kwargs["runtime_tree"] is tree
    assert state.context_state["__memory__"].startswith("## Learned Intelligence")
    assert await mem.intelligence_rules() == [{"title": "Cite sources"}]
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_memory_skipped_when_disabled() -> None:
    with patch("src.ai.memory.assembler.assemble_memory", new=AsyncMock()) as assemble:
        mem = await assemble_run_memory(_db(), _state(input="x"), entity=_entity({"enabled": False}))
    assert mem is None
    assemble.assert_not_called()


@pytest.mark.asyncio
async def test_resumed_run_reuses_snapshot_memory() -> None:
    state = _state(__intelligence_rules__=[{"title": "from snapshot"}])
    with patch("src.ai.memory.assembler.assemble_memory", new=AsyncMock()) as assemble:
        mem = await assemble_run_memory(_db(), state, entity=_entity({"enabled": True}),
                                        resumed=True)
    assemble.assert_not_called()
    assert await mem.intelligence_rules() == [{"title": "from snapshot"}]


@pytest.mark.asyncio
async def test_assembly_failure_runs_without_memory() -> None:
    db, state = _db(), _state(input="x")
    with patch("src.ai.memory.assembler.assemble_memory",
               new=AsyncMock(side_effect=RuntimeError("vector index missing"))), \
         patch("src.ai.core.agent_loop_sse.event_async", new=AsyncMock()):
        mem = await assemble_run_memory(db, state, entity=_entity({"enabled": True}))
    db.rollback.assert_awaited()
    assert "__memory__" not in state.context_state
    assert await mem.intelligence_rules() == []


@pytest.mark.asyncio
async def test_assembly_passes_on_the_retrievals_that_failed() -> None:
    from src.ai.memory.assembler import FAILURES_KEY

    assembler = MagicMock()
    assembler.assemble_runtime_memory = AsyncMock(return_value=SimpleNamespace(
        formatted_prompt="", intelligence_rules=[], episodic_context=[],
        knowledge_refs=[], experience_suggestions=[],
        failures={"experience": "ProgrammingError: relation missing"},
    ))
    with patch("src.ai.memory.memory_assembly_service.MemoryAssemblyService",
               return_value=assembler):
        ctx = await assemble_memory(MagicMock(), uuid4(), uuid4())
    assert ctx == {FAILURES_KEY: {"experience": "ProgrammingError: relation missing"}}


@pytest.mark.asyncio
async def test_a_failed_retrieval_is_on_the_trace_not_in_the_context() -> None:
    """MC-06: a domain that could not be read marks the run's memory span as
    an error, naming it, and is an event of its own — not an empty memory."""
    from contextlib import asynccontextmanager

    from src.ai.core.trace import SpanHandle
    from src.ai.memory.assembler import FAILURES_KEY

    handles: list = []

    @asynccontextmanager
    async def _span(kind, name=None, **payload):
        handle = SpanHandle(span_id=uuid4(), parent_span_id=None, kind=kind, name=name,
                            iteration=None, seq=0, payload=payload)
        handles.append(handle)
        yield handle

    db, state = _db(), _state(input="x")
    assembled = {"__episodic_memory__": [{"input": "q"}],
                 FAILURES_KEY: {"knowledge": "ProgrammingError: relation missing"}}
    events = AsyncMock()
    with patch("src.ai.memory.assembler.assemble_memory", new=AsyncMock(return_value=assembled)), \
         patch("src.ai.core.trace.span", new=_span), \
         patch("src.ai.core.agent_loop_sse.event_async", new=events):
        await assemble_run_memory(db, state, entity=_entity({"enabled": True}))

    [handle] = handles
    assert (handle.kind, handle.name, handle.status) == ("memory", "FULL", "error")
    assert "knowledge (ProgrammingError: relation missing)" in handle.error_message
    assert FAILURES_KEY not in state.context_state
    assert state.context_state["__episodic_memory__"] == [{"input": "q"}]
    calls = events.await_args_list
    assert [c.args[0] for c in calls] == ["agent.memory.retrieval_failed", "agent.memory.assembled"]
    assert (calls[0].kwargs["domain"], calls[0].kwargs["severity"]) == ("knowledge", "warning")
    assert calls[1].kwargs["failed"] == ["knowledge"]


@pytest.mark.asyncio
async def test_a_whole_assembly_failure_is_on_the_trace_too() -> None:
    from contextlib import asynccontextmanager

    from src.ai.core.trace import SpanHandle

    handles: list = []

    @asynccontextmanager
    async def _span(kind, name=None, **payload):
        handle = SpanHandle(span_id=uuid4(), parent_span_id=None, kind=kind, name=name,
                            iteration=None, seq=0, payload=payload)
        handles.append(handle)
        yield handle

    with patch("src.ai.memory.assembler.assemble_memory",
               new=AsyncMock(side_effect=RuntimeError("vector index missing"))), \
         patch("src.ai.core.trace.span", new=_span), \
         patch("src.ai.core.agent_loop_sse.event_async", new=AsyncMock()):
        await assemble_run_memory(_db(), _state(input="x"), entity=_entity({"enabled": True}))
    assert handles[0].status == "error"
    assert "assembly (RuntimeError: vector index missing)" in handles[0].error_message


# ---------------------------------------------------------------------------
# Consumers: step prompt + planner
# ---------------------------------------------------------------------------


def test_step_prompt_context_carries_memory() -> None:
    ctx = {"__memory__": "## Learned Intelligence\n  rule", "input": "q"}
    # The step's context policy may filter __memory__ out; it must still reach
    # the prompt.
    assert prompt_context_block({"input": "q"}, ctx) == "## Learned Intelligence\n  rule"
    assert prompt_context_block({"__context_sources__": "## Sources"}, ctx) == (
        "## Sources\n\n## Learned Intelligence\n  rule"
    )
    assert prompt_context_block({}, {}) is None


@pytest.mark.asyncio
async def test_planner_passes_rules_to_plan_generator() -> None:
    from src.ai.planning.planner_service import PlannerService

    captured = {}

    class _Gen:
        def __init__(self, **_kw):
            pass

        async def generate(self, ctx, n):
            captured["ctx"] = ctx
            chosen = SimpleNamespace(steps=[], style="linear", estimated_cost_usd=0)
            return SimpleNamespace(chosen=chosen, alternates=[], judge_reasoning="")

    rules = [{"title": "Fetch data before summarising"}]
    with patch("src.ai.planning.plan_generator.PlanGenerator", _Gen):
        svc = PlannerService(MagicMock(), company_id=uuid4())
        await svc._generate_dynamic_plan_v2(
            MagicMock(), _entity(None), {"input": "q", "__intelligence_rules__": rules}, {},
        )
    assert captured["ctx"].intelligence_rules == rules
