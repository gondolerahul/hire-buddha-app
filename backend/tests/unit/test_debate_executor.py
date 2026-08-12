"""Phase 12 (D-3) — DebateExecutor: registration + winner selection.

Pure unit tests with a stub LLM. No DB / Redis / real LLM: the executor's
``LLMRouter`` is monkeypatched and CORTEX is left disabled
(``cortex_working_root_id=None``) so the test exercises the candidate →
judge → winner path in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState
from src.ai.core.executors import get_executor, registered_executor_names
from src.ai.core.executors.debate import DebateExecutor
from src.ai.core.strategist import Move
from src.ai.schemas.enums import EntityType


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _StubResp:
    output: str
    prompt_tokens: int = 20
    completion_tokens: int = 8
    latency_ms: int = 5
    model_name: str = "stub-model"
    provider: str = "stub"
    finish_reason: str = "stop"
    function_calls: list = field(default_factory=list)


class _StubRouter:
    """Records calls; returns a per-temperature candidate, picks #2 as judge."""

    def __init__(self, db=None, company_id=None):  # noqa: ARG002
        self.calls: list[dict] = []

    async def call_llm(self, task_type, system_prompt, user_prompt,  # noqa: ARG002
                       temperature=0.7, max_tokens=None, model_override=None, **kw):
        self.calls.append({"system": system_prompt, "temp": temperature})
        if system_prompt.startswith("You are an impartial judge"):
            # Pick candidate #2 (1-indexed) → winner_idx == 1.
            return _StubResp(output='{"best": 2, "reason": "clearest"}')
        # Candidate output keyed on temperature so it's independent of the
        # order asyncio.gather happens to schedule the coroutines in.
        return _StubResp(output=f"candidate@temp={round(temperature, 2)}")


class _FakeResult:
    def __init__(self, run):
        self._run = run

    def scalar_one(self):
        return self._run

    def scalar_one_or_none(self):
        # UsageService registry lookups must miss so billing is a clean $0.
        return None


class _FakeDB:
    def __init__(self, run):
        self.run = run
        self.commits = 0

    async def execute(self, *_a, **_k):
        return _FakeResult(self.run)

    async def commit(self):
        self.commits += 1


def _entity():
    return SimpleNamespace(
        id=uuid4(),
        name="debater",
        goal="Answer the hard question.",
        identity={"system_prompt": "You are a careful assistant."},
        logic_gate={"reasoning_config": {"temperature": 0.7}},
    )


def _run(entity):
    return SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        entity=entity,
        total_cost_usd=Decimal("0"),
        total_tokens=0,
    )


def _state(company_id):
    return AgentState(
        run_id=uuid4(), entity_id=uuid4(), company_id=company_id,
        entity_type=EntityType.AGENT,
        cortex_working_root_id=None,   # disable CORTEX writes in this test
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_debate_executor_is_registered() -> None:
    assert "Debate" in registered_executor_names()
    assert get_executor("Debate").name == "Debate"


@pytest.mark.asyncio
async def test_debate_picks_judge_selected_winner(monkeypatch) -> None:
    entity = _entity()
    run = _run(entity)
    db = _FakeDB(run)
    stub = _StubRouter()
    monkeypatch.setattr("src.ai.core.executors.debate.LLMRouter", lambda **kw: stub)

    state = _state(run.company_id)
    move = Move(
        move_id="m1", goal_id=None, executor="Debate",
        plan_fragment=[{"step_id": "s1", "name": "synthesize", "type": "THOUGHT"}],
        reasoning_hint="DEBATE",
    )

    result = await DebateExecutor().execute(move, state, db)

    # 3 candidates (default) + 1 judge = 4 LLM calls.
    assert len(stub.calls) == 4
    # Judge picked candidate #2 → the i=1 candidate, whose temperature is 0.8.
    assert result.success is True
    assert result.output == "candidate@temp=0.8"
    assert result.completed_step_ids == ["s1"]
    # No pricing rows → real cost resolves to $0 (billing is best-effort).
    assert result.cost_usd == Decimal("0")


@pytest.mark.asyncio
async def test_debate_respects_candidate_count_config(monkeypatch) -> None:
    entity = _entity()
    entity.logic_gate = {"reasoning_config": {"debate_num_candidates": 2}}
    run = _run(entity)
    db = _FakeDB(run)
    stub = _StubRouter()
    monkeypatch.setattr("src.ai.core.executors.debate.LLMRouter", lambda **kw: stub)

    move = Move(move_id="m", goal_id=None, executor="Debate",
                plan_fragment=[{"step_id": "s1", "type": "THOUGHT"}])
    result = await DebateExecutor().execute(move, _state(run.company_id), db)

    # 2 candidates + 1 judge.
    assert len(stub.calls) == 3
    assert result.success is True


@pytest.mark.asyncio
async def test_debate_defaults_to_first_on_unparseable_judge(monkeypatch) -> None:
    """A malformed judge verdict must not crash — fall back to candidate #1."""
    class _BadJudge(_StubRouter):
        async def call_llm(self, task_type, system_prompt, user_prompt,  # noqa: ARG002
                           temperature=0.7, max_tokens=None, model_override=None, **kw):
            self.calls.append({"temp": temperature})
            if system_prompt.startswith("You are an impartial judge"):
                return _StubResp(output="no json here, sorry")
            return _StubResp(output=f"candidate@temp={round(temperature, 2)}")

    entity = _entity()
    run = _run(entity)
    stub = _BadJudge()
    monkeypatch.setattr("src.ai.core.executors.debate.LLMRouter", lambda **kw: stub)

    move = Move(move_id="m", goal_id=None, executor="Debate",
                plan_fragment=[{"step_id": "s1", "type": "THOUGHT"}])
    result = await DebateExecutor().execute(move, _state(run.company_id), _FakeDB(run))

    assert result.success is True
    # winner_idx defaults to 0 → first candidate (temp == base 0.7).
    assert result.output == "candidate@temp=0.7"
