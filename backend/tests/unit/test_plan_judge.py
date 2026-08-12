"""Phase 11 Track 7 — PlanJudge selection + tiebreak."""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.ai.planning.plan_generator import PlanCandidate
from src.ai.planning.plan_judge import PlanJudge


def _llm(payload: str, cost: float = 0.001) -> AsyncMock:
    m = AsyncMock()
    m.call_llm.return_value = SimpleNamespace(output=payload, cost_usd=cost)
    return m


def _cand(style: str, cost: float, steps=None) -> PlanCandidate:
    return PlanCandidate(
        steps=steps or [{"step_id": "s1", "type": "TOOL_CALL",
                         "name": "t", "target": {"tool_id": "web_search"}}],
        style=style,
        estimated_cost_usd=Decimal(str(cost)),
    )


# ---------------------------------------------------------------------------
# Single candidate short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_candidate_returns_immediately() -> None:
    judge = PlanJudge(llm_router=AsyncMock())
    only = _cand("DAG_PARALLEL", 0.05)
    chosen, scores, _ = await judge.pick([only])
    assert chosen is only
    assert scores == [1.0]


# ---------------------------------------------------------------------------
# LLM picks winner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_winner_index_used() -> None:
    a = _cand("DAG_PARALLEL", 0.05)
    b = _cand("DAG_SEQUENTIAL", 0.08)
    judge = PlanJudge(_llm(json.dumps(
        {"winner": 1, "scores": [0.4, 0.85], "reasoning": "B cleaner"}
    )))
    chosen, scores, reason = await judge.pick([a, b])
    assert chosen is b
    assert scores == [0.4, 0.85]
    assert reason == "B cleaner"


# ---------------------------------------------------------------------------
# Tiebreak by lower cost when scores within 0.10
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tiebreak_picks_cheaper_when_close() -> None:
    cheap = _cand("DAG_PARALLEL", 0.02)
    pricey = _cand("DAG_SEQUENTIAL", 0.08)
    judge = PlanJudge(_llm(json.dumps(
        {"winner": 1, "scores": [0.78, 0.80], "reasoning": "barely"}
    )))
    chosen, _, _ = await judge.pick([cheap, pricey])
    # Both contenders are within 0.10; cheaper wins.
    assert chosen is cheap


# ---------------------------------------------------------------------------
# LLM failure → cost fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_cheapest() -> None:
    cheap = _cand("DAG_PARALLEL", 0.02)
    pricey = _cand("DAG_SEQUENTIAL", 0.08)
    bad_llm = AsyncMock()
    bad_llm.call_llm.side_effect = RuntimeError("provider down")
    judge = PlanJudge(bad_llm)
    chosen, _, reason = await judge.pick([cheap, pricey])
    assert chosen is cheap
    assert "fallback" in reason


# ---------------------------------------------------------------------------
# Malformed LLM JSON → defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_defaults_to_winner_zero() -> None:
    a = _cand("DAG_PARALLEL", 0.02)
    b = _cand("DAG_SEQUENTIAL", 0.08)
    judge = PlanJudge(_llm("not json"))
    chosen, scores, _ = await judge.pick([a, b])
    # parse → winner=0, scores=[0,0] → cheapest still wins on tiebreak.
    assert chosen is a
    assert len(scores) == 2
