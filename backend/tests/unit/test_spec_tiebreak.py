"""Third-model spec-critic tiebreak — Phase 12 `06` §4.3.

Hermetic: the third model is a fake LLM. Locks in the high-stakes gate, the
disagreement gate, that the third model only runs when both fire, and the
conservative fallbacks.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ai.meta.spec_tiebreak import SpecCriticTiebreaker, is_high_stakes


class _FakeLLM:
    def __init__(self, output):
        self._output = output
        self.calls = 0

    async def call_llm(self, **kw):
        self.calls += 1
        return SimpleNamespace(output=self._output, model_name="third-model")


def _wide_process():
    return {"type": "PROCESS", "children": [1, 2, 3, 4, 5, 6]}


def _cheap_action():
    return {"type": "ACTION", "est_cost_usd": 0.1}


def test_high_stakes_wide_process() -> None:
    assert is_high_stakes(_wide_process(), governance_ceiling_usd=10.0)


def test_high_stakes_near_ceiling() -> None:
    assert is_high_stakes({"type": "AGENT", "est_cost_usd": 8.5}, governance_ceiling_usd=10.0)


def test_not_high_stakes() -> None:
    assert not is_high_stakes(_cheap_action(), governance_ceiling_usd=10.0)


@pytest.mark.asyncio
async def test_no_disagreement_skips_third_model() -> None:
    llm = _FakeLLM(json.dumps({"verdict": "BLOCK"}))
    res = await SpecCriticTiebreaker().maybe_adjudicate(
        _wide_process(), "PASS", "PASS", llm=llm, governance_ceiling_usd=10.0)
    assert not res.invoked
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_low_stakes_defers_to_critic() -> None:
    llm = _FakeLLM(json.dumps({"verdict": "PASS"}))
    res = await SpecCriticTiebreaker().maybe_adjudicate(
        _cheap_action(), "PASS", "REVISE", llm=llm, governance_ceiling_usd=10.0)
    assert not res.invoked
    assert res.verdict == "REVISE"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_high_stakes_disagreement_invokes_third_model() -> None:
    llm = _FakeLLM(json.dumps({"verdict": "PASS", "rationale": "architect is right"}))
    res = await SpecCriticTiebreaker().maybe_adjudicate(
        _wide_process(), "PASS", "REVISE", llm=llm, governance_ceiling_usd=10.0)
    assert res.invoked
    assert res.verdict == "PASS"
    assert llm.calls == 1
    assert res.model_used == "third-model"


@pytest.mark.asyncio
async def test_third_model_failure_defers_to_critic() -> None:
    class _Boom:
        async def call_llm(self, **kw):
            raise RuntimeError("down")

    res = await SpecCriticTiebreaker().maybe_adjudicate(
        _wide_process(), "PASS", "BLOCK", llm=_Boom(), governance_ceiling_usd=10.0)
    assert not res.invoked
    assert res.verdict == "BLOCK"
