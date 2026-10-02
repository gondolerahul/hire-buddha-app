"""A retry runs differently from the attempt it repeats (P7.1 — PC-06).

``pick_retry`` chose among seven strategies and ``RetryExecutor`` wrote the
remedy onto the queued dict — ``force_model_escalation``,
``prompt_rewrite_hint``, ``use_fallback_tool``, ``ask_user`` — which the loop
dropped when it rehydrated the dict into a ``Move``. Every retry ran as
``RETRY_AS_IS``: same model, same prompt, same tool. Now the remedy is a
``directive`` on the copy of each step the retry dispatches, and the step
executor honours it.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState, Budget
from src.ai.core.strategist import Move
from src.ai.planning.failure_tags import FailureTag
from src.ai.planning.retry_strategies import RetryExecutor, RetryStrategy, pick_retry
from src.ai.planning.step_health_record import StepHealthRecord
from src.ai.schemas import PlanStep, StepType
from src.ai.schemas.enums import EntityType


def _state() -> AgentState:
    bud = Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000)
    bud.consume(usd=Decimal("0.1"))
    return AgentState(run_id=uuid4(), entity_id=uuid4(), company_id=uuid4(),
                      entity_type=EntityType.AGENT, budget=bud)


def _record(tag: FailureTag, suggestion: str = "") -> StepHealthRecord:
    return StepHealthRecord(step_id="s1", iteration=1, move_id="m1", post_critic_verdict="REVISE",
                            post_critic_tags=[tag], post_critic_suggestion=suggestion)


def _retry_step(tag: FailureTag, step: dict, suggestion: str = "") -> PlanStep:
    """The step the loop dispatches for the retry, through the queue and back."""
    from src.ai.core.agent_loop import AgentLoop
    from src.ai.core.executors.single_step import SingleStepExecutor
    state = _state()
    record = _record(tag, suggestion)
    move = Move(move_id="m1", goal_id=None, executor="SingleStep", plan_fragment=[step], rationale="first")
    queued = RetryExecutor().build(pick_retry(record, state), move, record)
    assert queued is not None
    retry_move = AgentLoop._move_from_retry(MagicMock(), queued, state)
    [fragment_step] = retry_move.plan_fragment
    return SingleStepExecutor._coerce_step(fragment_step)


THOUGHT = {"step_id": "s1", "name": "write", "type": "THOUGHT", "target": {"prompt_template": "{{input}}"}}
SEARCH = {"step_id": "s1", "name": "find", "type": "TOOL_CALL",
          "target": {"tool_id": "web_search", "prompt_template": "{{input}}"}}


def test_the_remedy_survives_the_queue():
    assert _retry_step(FailureTag.HALLUCINATION, THOUGHT).directive.escalate_model is True
    assert _retry_step(FailureTag.WRONG_FORMAT, THOUGHT, "answer in JSON").directive.prompt_hint == "answer in JSON"
    assert _retry_step(FailureTag.TOOL_FAILURE, SEARCH).directive.use_fallback_tool is True
    assert _retry_step(FailureTag.NEEDS_CLARIFICATION, THOUGHT, "which year?").directive.ask_user == "which year?"


def test_a_tool_retry_with_no_fallback_rewrites_the_prompt_instead():
    calc = {**SEARCH, "target": {"tool_id": "calculator"}}
    directive = _retry_step(FailureTag.TOOL_FAILURE, calc, "check the numbers").directive
    assert not directive.use_fallback_tool and "different tool" in directive.prompt_hint
    assert directive.strategy == RetryStrategy.RETRY_DIFFERENT_PROMPT.value


# ── the step executor honours the directive ──────────────────────────────────


class _Router:
    calls: list[dict] = []

    def __init__(self, **_kw):
        pass

    async def call_llm_react(self, **kw):
        _Router.calls.append(kw)
        return SimpleNamespace(output="done", prompt_tokens=1, completion_tokens=1, latency_ms=1,
                               provider="fake", model_name="fake", hit_turn_limit=False)


def _service(monkeypatch):
    import src.ai.step_executor as se
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.governance.tool_access import ToolAccess

    _Router.calls = []
    monkeypatch.setattr(se, "LLMRouter", _Router)
    monkeypatch.setattr(FeatureFlags, "is_on", AsyncMock(return_value=False))
    monkeypatch.setattr(ToolAccess, "load", AsyncMock(return_value=ToolAccess(company_id=None, grants={})))
    db = MagicMock(commit=AsyncMock(), add=MagicMock(), execute=AsyncMock(side_effect=RuntimeError("no db")))
    svc = se.StepExecutorService(db=db, redis=None, company_id=uuid4(), usage_service=MagicMock(),
                                 cortex_bridge=None)
    svc._log_usage = AsyncMock()
    svc._charge_tool = AsyncMock()
    svc._skill_files = AsyncMock(return_value=[])
    svc._maybe_summarize_context = AsyncMock(side_effect=lambda _r, _e, ctx: ctx)
    return svc


def _run_and_entity(model_name=None):
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), user_id=None, total_cost_usd=0, depth=0, max_depth=None)
    entity = SimpleNamespace(id=uuid4(), name="writer", type="AGENT", company_id=run.company_id, goal="write",
                             capabilities={}, planning={}, identity={}, io_contract={}, governance={},
                             metadata_extensions={},
                             logic_gate={"reasoning_config": {"model_name": model_name} if model_name else {}})
    return run, entity


@pytest.mark.asyncio
async def test_an_escalated_retry_runs_on_the_reasoning_model_with_the_correction(monkeypatch):
    svc = _service(monkeypatch)
    run, entity = _run_and_entity()
    await svc._execute_thought(run, entity, PlanStep(**THOUGHT), {"input": "a poem"})
    retry = _retry_step(FailureTag.HALLUCINATION, THOUGHT, "cite only the brief")
    await svc._execute_thought(run, entity, retry, {"input": "a poem"})

    first, again = _Router.calls
    assert first["task_type"] == "text_generation" and "## Correction" not in first["user_prompt"]
    assert again["task_type"] == "thinking"
    assert again["user_prompt"].endswith("## Correction\ncite only the brief")


@pytest.mark.asyncio
async def test_an_entitys_own_model_is_kept_when_escalating(monkeypatch):
    svc = _service(monkeypatch)
    run, entity = _run_and_entity(model_name="gemini-2.5-pro")
    await svc._execute_thought(run, entity, _retry_step(FailureTag.HALLUCINATION, THOUGHT), {"input": "x"})
    [call] = _Router.calls
    assert call["model_override"] == "gemini-2.5-pro" and call["task_type"] == "text_generation"


@pytest.mark.asyncio
async def test_a_tool_retry_starts_at_the_fallback(monkeypatch):
    import src.ai.step_executor as se
    from src.ai.tools.resilience import ToolResilience
    from src.ai.tool_executor import ToolResult

    svc = _service(monkeypatch)
    svc._log_tool_call = MagicMock()
    seen: list[str] = []

    async def _run(self, *, tool_id, raw_input, **_kw):
        seen.append(tool_id)
        return ToolResult(tool=tool_id, args={}, output="page", success=True)

    monkeypatch.setattr(ToolResilience, "run", _run)
    run, entity = _run_and_entity()
    await svc._execute_tool_call(run, entity, PlanStep(**SEARCH), {"input": "cats"})
    await svc._execute_tool_call(run, entity, _retry_step(FailureTag.TOOL_FAILURE, SEARCH), {"input": "cats"})
    assert seen == ["web_search", "headless_browser"]
    assert se.step_directive(PlanStep(**SEARCH)) is None


@pytest.mark.asyncio
async def test_ask_user_puts_the_question_to_a_person_first():
    from src.ai.core.step_engine import StepEngine

    engine = StepEngine.__new__(StepEngine)
    engine.db = MagicMock()
    engine._governance = MagicMock(ask_user=AsyncMock(return_value="the 2025 figures"),
                                   evaluate_hitl=AsyncMock())
    ran: list[PlanStep] = []

    async def _execute_step(run, entity, step, ctx):
        ran.append(step)
        return {"step": step.name, "output": "ok"}

    engine._step_executor = SimpleNamespace(_execute_step=_execute_step)
    engine._enforce_cost_cap = AsyncMock()
    run, entity = _run_and_entity()
    entity.observability = {}
    step = _retry_step(FailureTag.NEEDS_CLARIFICATION, THOUGHT, "which year?")
    await engine._execute_step_wrapper(run, entity, step, {})

    engine._governance.ask_user.assert_awaited_once()
    assert engine._governance.ask_user.await_args.args[2] == "which year?"
    [sent] = ran
    assert sent.directive.ask_user is None and "The user answered: the 2025 figures" in sent.directive.prompt_hint

    engine._governance.ask_user = AsyncMock(side_effect=Exception("declined"))
    with pytest.raises(Exception, match="declined"):
        await engine._execute_step_wrapper(run, entity, step, {})
    assert len(ran) == 1  # the step did not run on a guess
