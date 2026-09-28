"""Phase 11 Track 7 — PlanGenerator end-to-end (stubbed LLM)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.ai.planning.plan_generator import (
    PlanCandidate,
    PlanContext,
    PlanGenerator,
    classify_plan_style,
)


def _entity(*, tools=None, governance=None):
    return SimpleNamespace(
        capabilities={"tools": list(tools or [])},
        governance=dict(governance or {}),
        goal="Do a thing",
    )


def _llm_router(payloads: list[str]) -> AsyncMock:
    """Cycles through payloads — one per candidate call."""
    it = iter(payloads)

    async def call_llm(*args, **kwargs):
        try:
            out = next(it)
        except StopIteration:
            out = '{"steps": []}'
        return SimpleNamespace(output=out, cost_usd=0.001)

    m = AsyncMock()
    m.call_llm = call_llm
    return m


def _good_plan() -> str:
    return json.dumps({
        "steps": [
            {"step_id": "s1", "type": "TOOL_CALL", "name": "search",
             "target": {"tool_id": "web_search"}},
        ]
    })


def _expensive_plan() -> str:
    return json.dumps({
        "steps": [
            {"step_id": f"s{i}", "type": "TOOL_CALL",
             "name": f"img_{i}", "target": {"tool_id": "image_generation"}}
            for i in range(8)
        ]
    })


# ---------------------------------------------------------------------------
# classify_plan_style
# ---------------------------------------------------------------------------


def test_classify_single_tool() -> None:
    assert classify_plan_style(
        [{"type": "TOOL_CALL", "target": {}}]
    ) == "SINGLE_TOOL"


def test_classify_child_entity() -> None:
    assert classify_plan_style(
        [{"type": "TOOL_CALL", "target": {}},
         {"type": "CHILD_ENTITY_INVOCATION", "target": {}}]
    ) == "CHILD_ENTITY"


def test_classify_dag_parallel_when_no_deps() -> None:
    assert classify_plan_style(
        [{"type": "TOOL_CALL", "target": {}},
         {"type": "TOOL_CALL", "target": {}}]
    ) == "DAG_PARALLEL"


def test_classify_dag_sequential_when_deps_present() -> None:
    assert classify_plan_style(
        [{"type": "TOOL_CALL", "step_id": "s1", "target": {}},
         {"type": "TOOL_CALL", "step_id": "s2",
          "target": {"input_dependencies": ["s1"]}}]
    ) == "DAG_SEQUENTIAL"


# ---------------------------------------------------------------------------
# generate — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_chosen_and_alternates() -> None:
    # 3 candidates all clean; judge picks index 0.
    llm = _llm_router([
        _good_plan(), _good_plan(), _good_plan(),
        json.dumps({"winner": 0, "scores": [0.9, 0.8], "reasoning": "ok"}),
    ])
    gen = PlanGenerator(llm_router=llm)
    ctx = PlanContext(
        entity=_entity(tools=["web_search"],
                       governance={"max_cost_usd": 1.0}),
        goal="research",
    )
    result = await gen.generate(ctx, n=3)
    assert result.chosen.steps
    assert result.chosen.invariant_violations == []
    assert isinstance(result.alternates, list)


# ---------------------------------------------------------------------------
# generate — over-budget candidates filtered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overbudget_candidates_filtered_out() -> None:
    # All three LLM candidates are over-cost; only the static plan fits the
    # budget. With D-2 the static plan competes as a first-class "authored"
    # candidate, so it is selected directly (it no longer has to come back
    # through the repair path).
    static = {
        "steps": [
            {"step_id": "s1", "type": "TOOL_CALL", "name": "search",
             "target": {"tool_id": "web_search"}},
        ]
    }
    llm = _llm_router([_expensive_plan()] * 3)
    gen = PlanGenerator(llm_router=llm)
    ctx = PlanContext(
        entity=_entity(tools=["image_generation", "web_search"],
                       governance={"max_cost_usd": 0.02}),
        static_plan=static,
        goal="research",
    )
    result = await gen.generate(ctx, n=3)
    # The over-budget LLM candidates were filtered; the authored static plan
    # (which fits the budget) is chosen.
    assert result.chosen.source == "authored"
    assert [s["step_id"] for s in result.chosen.steps] == ["s1"]
    assert result.chosen.invariant_violations == []


# ---------------------------------------------------------------------------
# Events emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_emits_events_per_candidate() -> None:
    events: list[tuple[str, dict]] = []

    async def emit(name, **payload):
        events.append((name, payload))

    llm = _llm_router([_good_plan()] * 2 + [
        json.dumps({"winner": 0, "scores": [0.8, 0.7]})
    ])
    gen = PlanGenerator(llm_router=llm, emit_event=emit)
    ctx = PlanContext(
        entity=_entity(tools=["web_search"],
                       governance={"max_cost_usd": 1.0}),
        goal="research",
    )
    await gen.generate(ctx, n=2)
    names = [e[0] for e in events]
    assert "agent.plan.generation_start" in names
    assert names.count("agent.plan.candidate_generated") == 2
    assert "agent.plan.chosen" in names


# ---------------------------------------------------------------------------
# replan path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replan_emits_replan_event_and_returns_candidates() -> None:
    events: list[tuple[str, dict]] = []

    async def emit(name, **payload):
        events.append((name, payload))

    llm = _llm_router([_good_plan(), _good_plan(),
                       json.dumps({"winner": 0, "scores": [0.9, 0.8]})])
    gen = PlanGenerator(llm_router=llm, emit_event=emit)
    fake_state = SimpleNamespace(
        entity=_entity(tools=["web_search"],
                       governance={"max_cost_usd": 1.0}),
        plan_steps=[],
        task_class="research_topic",
        budget=None,
        company_id=None,
    )
    result = await gen.replan(fake_state, failed_step={"name": "x", "error": "y"})
    assert result.chosen.steps
    assert any(e[0] == "agent.plan.replan" for e in events)


# ---------------------------------------------------------------------------
# Single-candidate fast path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_candidate_skips_judge() -> None:
    llm = _llm_router([_good_plan()])
    gen = PlanGenerator(llm_router=llm)
    ctx = PlanContext(
        entity=_entity(tools=["web_search"], governance={"max_cost_usd": 1.0}),
        goal="research",
    )
    result = await gen.generate(ctx, n=1)
    assert result.chosen.judge_score is None  # judge not invoked
    assert result.alternates == []


# ---------------------------------------------------------------------------
# D-2: static plan as a first-class candidate + STRICT binding
# ---------------------------------------------------------------------------


def test_authored_candidate_built_for_adaptive() -> None:
    gen = PlanGenerator(llm_router=_llm_router([]))
    ctx = PlanContext(
        entity=_entity(tools=["web_search"]),
        static_plan={"steps": [
            {"step_id": "a1", "type": "TOOL_CALL", "name": "authored_search",
             "target": {"tool_id": "web_search"}},
        ]},  # default fallback_behavior == ADAPTIVE
        goal="research",
    )
    cand = gen._authored_candidate(ctx)
    assert cand is not None
    assert cand.source == "authored"
    assert [s["step_id"] for s in cand.steps] == ["a1"]


def test_authored_candidate_skipped_for_dynamic_only() -> None:
    gen = PlanGenerator(llm_router=_llm_router([]))
    ctx = PlanContext(
        entity=_entity(tools=["web_search"]),
        static_plan={
            "fallback_behavior": "DYNAMIC_ONLY",
            "steps": [{"step_id": "a1", "type": "TOOL_CALL", "name": "x",
                       "target": {"tool_id": "web_search"}}],
        },
        goal="research",
    )
    assert gen._authored_candidate(ctx) is None


@pytest.mark.asyncio
async def test_strict_binding_authored_plan_wins() -> None:
    # STRICT static plan with a compliance step the LLM candidates omit.
    static = {
        "fallback_behavior": "STRICT",
        "steps": [
            {"step_id": "audit", "type": "TOOL_CALL", "name": "audit_log",
             "target": {"tool_id": "web_search"}},
        ],
    }
    # Every LLM candidate proposes a DIFFERENT plan (s1/search) that drops
    # the authored 'audit' step.
    llm = _llm_router([_good_plan()] * 3)
    gen = PlanGenerator(llm_router=llm)
    ctx = PlanContext(
        entity=_entity(tools=["web_search"]),
        static_plan=static,
        goal="research",
    )
    result = await gen.generate(ctx, n=3)
    # Binding (STRICT): only a plan covering 'audit' is allowed → the authored
    # plan is the one that survives.
    assert result.chosen.source == "authored"
    assert "audit" in {s.get("step_id") for s in result.chosen.steps}


# ---------------------------------------------------------------------------
# Shared-session safety — candidates must not use the run's session at once
# ---------------------------------------------------------------------------


def _concurrency_probe() -> tuple[SimpleNamespace, dict[str, int], list[str]]:
    """Router + usage logger that record how many calls overlap."""
    peak = {"llm": 0, "log": 0}
    active = {"llm": 0, "log": 0}
    logged: list[str] = []

    async def enter(kind: str, delay: float) -> None:
        active[kind] += 1
        peak[kind] = max(peak[kind], active[kind])
        await asyncio.sleep(delay)
        active[kind] -= 1

    async def call_llm(**kwargs):
        # Later temperatures finish first, so completion order differs.
        await enter("llm", 0.03 * (1 - kwargs["temperature"]))
        if kwargs["temperature"] == 0.5:
            raise RuntimeError("provider down")
        return SimpleNamespace(output=_good_plan(), rationale=kwargs["temperature"])

    async def log_usage(ctx, resp, attribution):
        await enter("log", 0.01)
        logged.append(f"{attribution}@{resp.rationale}")

    return SimpleNamespace(call_llm=call_llm, log_usage=log_usage), peak, logged


@pytest.mark.asyncio
async def test_candidates_call_llm_concurrently_but_log_usage_one_at_a_time() -> None:
    # Usage logging commits on the run's AsyncSession; overlapping commits
    # flushed each other's rows (duplicate usage_logs PK) and broke the
    # session, so the planner fell back to an empty plan.
    probe, peak, logged = _concurrency_probe()
    gen = PlanGenerator(llm_router=probe)
    gen._log_attributed_usage = probe.log_usage  # type: ignore[method-assign]
    ctx = PlanContext(
        entity=_entity(tools=["web_search"]),
        static_plan={"steps": [{"step_id": "fallback", "type": "THOUGHT"}]},
        goal="research",
    )

    cands = await gen._generate_candidates(ctx, n=3)

    assert peak["llm"] == 3                        # still parallel
    assert peak["log"] == 1                        # never overlapping
    assert logged == ["planner@0.2", "planner@0.8"]  # failed call not billed
    assert [c.rationale for c in cands] == ["temp=0.2", "temp=0.5", "temp=0.8"]
    assert [s["step_id"] for s in cands[1].steps] == ["fallback"]  # failed → static
    assert [s["step_id"] for s in cands[0].steps] == ["s1"]
