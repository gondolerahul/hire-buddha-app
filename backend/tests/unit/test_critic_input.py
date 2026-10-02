"""The critics judge the step's output, not its 160-character summary (PC-27).

``Observer._summarise`` builds ``"[<outcome>] " + output[:160]`` for the
timeline, and the post critic and the alignment check judged that. Any answer
longer than 160 characters reached them cut mid-word, so the post critic said
``REVISE``/``INCOMPLETE`` every iteration and the supervisor replanned until a
cap (live run a13cae0f: nine iterations, cancelled). The same summary was also
stored as the run's result, the text parents and episodes read.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import AgentState, Observation
from src.ai.core.budget import Budget
from src.ai.core.executors.base import ActionResult
from src.ai.core.observer import CRITIC_OUTPUT_TOKENS, Observer, bounded_output
from src.ai.planning.critic_pipeline import RealCriticPipeline, StepHealthRecord
from src.ai.schemas.enums import EntityType

ANSWER = (
    "Unit tests catch regressions the moment a change breaks existing behaviour, long "
    "before a user does. They also document what each function is meant to do, so the "
    "next person can change the code with confidence."
)


def _state() -> AgentState:
    return AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
                      entity_type=EntityType.ACTION,
                      budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000))


def _observe(output: str = ANSWER, **kw) -> Observation:
    return Observer().parse(ActionResult(success=True, output=output, **kw), _state())


def test_the_observation_keeps_the_whole_output():
    assert len(ANSWER) > 160
    obs = _observe()
    assert obs.output == ANSWER
    assert obs.summary.startswith("[success]") and len(obs.summary) < len(ANSWER)


@pytest.mark.asyncio
async def test_the_post_critic_is_shown_the_whole_answer():
    llm = AsyncMock()
    llm.call_llm.return_value = SimpleNamespace(output='{"verdict": "PASS", "tags": []}', cost_usd=0)
    pipe = RealCriticPipeline(db=None, llm_router=llm, cortex_service=None,
                              config={"entity_goal": "explain unit tests", "enable_different_model": False})
    state = _state()
    pipe._current_record = StepHealthRecord(iteration=state.iteration)

    await pipe.post_action(state, _observe())

    prompt = llm.call_llm.await_args.kwargs["user_prompt"]
    assert ANSWER in prompt
    assert "[success]" not in prompt


@pytest.mark.asyncio
async def test_a_failed_step_with_no_output_still_shows_its_error():
    llm = AsyncMock()
    llm.call_llm.return_value = SimpleNamespace(output='{"verdict": "REJECT"}', cost_usd=0)
    pipe = RealCriticPipeline(db=None, llm_router=llm, cortex_service=None,
                              config={"entity_goal": "g", "enable_different_model": False})
    state = _state()
    pipe._current_record = StepHealthRecord(iteration=state.iteration)
    obs = Observer().parse(ActionResult(success=False, error="tool timed out"), state)

    await pipe.post_action(state, obs)

    assert "tool timed out" in llm.call_llm.await_args.kwargs["user_prompt"]


@pytest.mark.asyncio
async def test_the_alignment_check_is_given_the_whole_answer(monkeypatch):
    import src.ai.planning.goal_alignment as ga
    verify = AsyncMock(return_value={"aligned": True, "confidence": 0.9})
    monkeypatch.setattr(ga.GoalAlignmentVerifier, "verify_step_alignment", verify)
    pipe = RealCriticPipeline(db=None, llm_router=AsyncMock(), cortex_service=None,
                              config={"entity_goal": "explain unit tests", "goal_validation_interval": 1})
    pipe._current_record = StepHealthRecord(iteration=1)

    await pipe.alignment(_state(), _observe())

    assert verify.await_args.kwargs["step_output"] == ANSWER


@pytest.mark.asyncio
async def test_the_alignment_prompt_carries_the_whole_answer(monkeypatch):
    import src.ai.llm.router as router_mod
    import src.ai.usage_service as usage_mod
    from src.ai.planning.goal_alignment import GoalAlignmentVerifier
    seen = {}

    class _Router:
        def __init__(self, **_kw):
            pass

        async def call_llm(self, **kw):
            seen.update(kw)
            return SimpleNamespace(model_name="m", prompt_tokens=1, completion_tokens=1,
                                   output='{"aligned": true, "confidence": 0.9}')

    monkeypatch.setattr(router_mod, "LLMRouter", _Router)
    monkeypatch.setattr(usage_mod.UsageService, "log_usage",
                        AsyncMock(return_value=SimpleNamespace(calculated_cost=0)))
    long_answer = ANSWER * 20                                 # ~4.4k chars: past the old 2000 cut
    await GoalAlignmentVerifier(None, uuid4()).verify_step_alignment(
        entity_goal="g", task_desc="t", step_output=long_answer, step_name="s")
    assert long_answer in seen["user_prompt"]


def test_a_cut_beyond_the_budget_is_marked():
    limit = CRITIC_OUTPUT_TOKENS * 4
    huge = "y" * (limit + 500)
    cut = bounded_output(huge)
    assert cut.startswith("y" * limit)
    assert "500 more characters cut by the system" in cut
    assert bounded_output(ANSWER) == ANSWER


def test_the_run_result_is_the_answer_not_the_summary():
    state = _state()
    state.apply_observation(_observe())
    assert AgentLoop._final_output(state) == ANSWER


def test_a_snapshot_from_before_the_field_still_restores():
    state = _state()
    state.apply_observation(_observe())
    snap = state.snapshot()
    snap["last_observation"].pop("output")
    restored = AgentState.restore(snap)
    assert restored.last_observation.output == ""
