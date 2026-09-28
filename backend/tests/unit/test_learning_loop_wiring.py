"""MC-02 / MC-03 — the learning loop runs, and what it learns is read.

MC-02: the scheduled Dreaming sweep and semantic-graph maintenance are
registered, enqueue correctly, and select the right entities.
MC-03: learned Intelligence rules reach the post critic's prompt.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState, Observation
from src.ai.core.budget import Budget
from src.ai.memory.run_memory import RunMemory
from src.ai.planning.critic_pipeline import RealCriticPipeline, StepHealthRecord
from src.ai.schemas.enums import EntityType


# ---------------------------------------------------------------------------
# MC-02 — worker registration
# ---------------------------------------------------------------------------


def test_dreaming_and_graph_jobs_are_registered() -> None:
    from src.ai.worker import WorkerSettings

    names = {f.__name__ for f in WorkerSettings.functions}
    assert {"dreaming_worker", "graph_maintenance_worker"} <= names
    crons = {c.coroutine.__name__ for c in WorkerSettings.cron_jobs}
    assert {"dreaming_cron_trigger", "graph_maintenance_worker"} <= crons


def _session_returning(rows):
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


@pytest.mark.asyncio
async def test_dreaming_cron_enqueues_memory_enabled_entities() -> None:
    from src.ai.core.arq_jobs import dreaming_cron_trigger

    e1, e2, company = uuid4(), uuid4(), uuid4()
    cm, session = _session_returning([(e1, company), (e2, company)])
    redis = MagicMock()
    redis.enqueue_job = AsyncMock()
    with patch("src.common.database.AsyncSessionLocal", return_value=cm):
        result = await dreaming_cron_trigger({"redis": redis})

    assert result == {"enqueued": 2}
    # The worker's pool is used as-is (wrapping it in ArqRedis(...) broke enqueueing).
    redis.enqueue_job.assert_any_await("dreaming_worker", str(e1), str(company), False)
    sql = str(session.execute.call_args.args[0])
    assert "capabilities->'memory'->>'enabled' = 'true'" in sql
    assert "'DELETED'" in sql


@pytest.mark.asyncio
async def test_dreaming_cron_without_redis_enqueues_nothing() -> None:
    from src.ai.core.arq_jobs import dreaming_cron_trigger

    assert await dreaming_cron_trigger({}) == {"enqueued": 0}


@pytest.mark.asyncio
async def test_graph_maintenance_runs_one_global_pass() -> None:
    from src.ai.core.arq_jobs import graph_maintenance_worker

    cm, session = _session_returning([])
    graph = MagicMock()
    graph.decay_weights = AsyncMock(return_value=4)
    graph.prune_weak_edges = AsyncMock(return_value=1)
    with patch("src.common.database.AsyncSessionLocal", return_value=cm), \
         patch("cortex_memory.graph.SemanticGraphService", return_value=graph):
        result = await graph_maintenance_worker({})

    assert result == {"decayed": 4, "pruned": 1}
    graph.decay_weights.assert_awaited_once_with(days_inactive=30)
    graph.prune_weak_edges.assert_awaited_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("memory, enqueued", [(None, False), (RunMemory({}), True)])
async def test_outcome_dreaming_only_for_memory_entities(memory, enqueued) -> None:
    from arq.connections import ArqRedis
    from src.ai.core.agent_loop import AgentLoop

    redis = MagicMock(spec=ArqRedis)
    redis.enqueue_job = AsyncMock()
    loop = AgentLoop(MagicMock(), redis=redis, feature_flags=MagicMock())
    loop._flag_or_default = AsyncMock(return_value=True)
    loop.memory = memory
    state = SimpleNamespace(entity_id=uuid4(), company_id=uuid4(), run_id=uuid4())
    with patch("src.ai.core.agent_loop.event_async", new=AsyncMock()):
        await loop._enqueue_dreaming_trigger(state, "COMPLETED")
    assert redis.enqueue_job.await_count == (1 if enqueued else 0)


# ---------------------------------------------------------------------------
# MC-03 — the post critic reads learned rules
# ---------------------------------------------------------------------------


def _state() -> AgentState:
    return AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
        entity_type=EntityType.SKILL, iteration=1,
        budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
    )


@pytest.mark.asyncio
async def test_post_critic_prompt_carries_learned_rules() -> None:
    llm = AsyncMock()
    llm.call_llm.return_value = SimpleNamespace(output='{"verdict": "PASS"}', cost_usd=0.001)
    memory = RunMemory({"__intelligence_rules__": [
        {"title": "Cite sources", "rule": "Every figure must cite its source.", "type": "instruction"},
        {"title": "Fetch first", "rule": "Fetch data before summarising.", "type": "strategy"},
    ]})
    pipe = RealCriticPipeline(
        db=None, llm_router=llm, cortex_service=None, intelligence_reader=memory,
        config={"entity_goal": "research EV batteries", "enable_different_model": False},
    )
    state = _state()
    pipe._current_record = StepHealthRecord(iteration=state.iteration)
    obs = Observation(iteration=1, outcome="success", novelty_score=0.5,
                      goal_delta_estimate=0.1, summary="Prices fell 20%.")

    await pipe.post_action(state, obs)

    prompt = llm.call_llm.call_args.kwargs["user_prompt"]
    assert "- Every figure must cite its source." in prompt
    assert "- Fetch data before summarising." in prompt


@pytest.mark.asyncio
async def test_run_memory_top_rules() -> None:
    mem = RunMemory({"__intelligence_rules__": [{"rule": f"r{i}"} for i in range(5)]})
    assert await mem.top_rules(limit=3) == [{"rule": "r0"}, {"rule": "r1"}, {"rule": "r2"}]
    assert await RunMemory({}).top_rules() == []


def test_rule_text_handles_dicts_and_nodes() -> None:
    text = RealCriticPipeline._rule_text
    assert text({"title": "T", "rule": "Do X"}) == "Do X"
    assert text({"title": "Only a title"}) == "Only a title"
    assert text(SimpleNamespace(summary="node summary")) == "node summary"
