"""Meta-Agent prompt evolution — Phase 12 `06` §6.1.

Hermetic: the critic-of-critic LLM is a canned fake. Locks in: a proposal is
parsed from JSON, an empty diff is non-actionable, no samples short-circuits, and
an LLM failure degrades to a safe (non-actionable) proposal — never autonomous.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ai.meta.prompt_evolution import (
    PromptEvolutionCritic,
    RunSample,
)


class _FakeLLM:
    def __init__(self, output: str):
        self._output = output

    async def call_llm(self, **kwargs):
        return SimpleNamespace(output=self._output, model_name="critic-model")


def _samples(n=5):
    return [RunSample(run_id=f"run-{i}", outcome="COMPLETED", board_decision="CREATE",
                      critic_verdict="PASS", cost_usd=1.5 * i) for i in range(n)]


@pytest.mark.asyncio
async def test_proposes_actionable_diff() -> None:
    llm = _FakeLLM(json.dumps({
        "prompt_diff": "Prefer REUSE over CREATE when a candidate scores >0.8.",
        "rationale": "5/5 runs chose CREATE despite close reuse candidates.",
        "confidence": "high",
    }))
    proposal = await PromptEvolutionCritic().propose("current prompt", _samples(), llm=llm)
    assert proposal.actionable
    assert proposal.confidence == "high"
    assert proposal.evidence_run_ids == ["run-0", "run-1", "run-2", "run-3", "run-4"]
    assert proposal.model_used == "critic-model"


@pytest.mark.asyncio
async def test_empty_diff_not_actionable() -> None:
    llm = _FakeLLM(json.dumps({"prompt_diff": "", "rationale": "no systemic issue"}))
    proposal = await PromptEvolutionCritic().propose("p", _samples(), llm=llm)
    assert not proposal.actionable
    assert proposal.confidence == "low"


@pytest.mark.asyncio
async def test_no_samples_short_circuits() -> None:
    called = {"n": 0}

    class _Spy:
        async def call_llm(self, **kw):
            called["n"] += 1
            return SimpleNamespace(output="{}", model_name="x")

    proposal = await PromptEvolutionCritic().propose("p", [], llm=_Spy())
    assert not proposal.actionable
    assert called["n"] == 0  # no LLM call when there are no runs


@pytest.mark.asyncio
async def test_llm_failure_is_safe() -> None:
    class _Boom:
        async def call_llm(self, **kw):
            raise RuntimeError("down")

    proposal = await PromptEvolutionCritic().propose("p", _samples(), llm=_Boom())
    assert not proposal.actionable
    assert "unavailable" in proposal.rationale.lower()


def test_run_sample_line_is_compact() -> None:
    line = RunSample(run_id="abcdef123456", outcome="FAILED", cost_usd=2.0).to_line()
    assert "abcdef12" in line and "FAILED" in line
