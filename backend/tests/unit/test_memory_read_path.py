"""MC-01 — the memory read path.

Memory assembled at the start of a run must reach the step prompt, the
Perceiver (and through it the supervisor critic) and the planner.
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
               return_value=assembler), \
         patch("src.ai.memory.legacy_episodic_reader.LegacyEpisodicReader") as legacy:
        legacy.return_value.read = AsyncMock(return_value=[])
        await assemble_memory(MagicMock(), uuid4(), uuid4(), memory_scope=scope)
    assert assembler.assemble_runtime_memory.call_args.kwargs["include_domains"] == domains


# ---------------------------------------------------------------------------
# RunMemory — the reader the Perceiver and critic consume
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
async def test_perceiver_reads_rules_from_run_memory() -> None:
    from src.ai.core.perceiver import Perceiver

    mem = RunMemory({"__intelligence_rules__": [{"title": "Verify figures", "rule": "Check the source"}]})
    state = SimpleNamespace(entity_id=uuid4(), company_id=uuid4())
    with patch("src.ai.core.feature_flags.FeatureFlags.is_on", new=AsyncMock(return_value=False)):
        rules = await Perceiver(memory_assembler=mem)._gather_intelligence_rules(state)
    assert rules == [{"title": "Verify figures", "rule": "Check the source"}]


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
