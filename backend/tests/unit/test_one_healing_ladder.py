"""One healing ladder for every tool call (P8.6 — EP-22).

A model's tool calls (the REACT path) went through ``ToolResilience`` only when
``tools.resilience_v2_enabled`` was on; off, they got no reformat retry and no
fallback — a reliability level chosen by a flag, unlike a TOOL_CALL step's
calls. The flag and the unhealed branch are gone.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_a_model_tool_call_is_healed_whatever_the_flags_say(monkeypatch):
    import src.ai.step_executor as se
    from src.ai.core.feature_flags import DEFAULTS, FeatureFlags
    from src.ai.governance.tool_access import ToolAccess
    from src.ai.schemas import PlanStep, StepType
    from src.ai.tool_executor import ToolResult
    from src.ai.tools.resilience import ToolResilience

    healed: list[str] = []

    async def _heal(self, *, function_call, **_kw):
        healed.append(function_call["name"])
        return ToolResult(tool=function_call["name"], args={}, output="ok", success=True)

    class _Router:
        def __init__(self, **_kw):
            pass

        async def call_llm_react(self, *, execute_tool_fn, **_kw):
            await execute_tool_fn([{"name": "web_search", "args": {"query": "tides"}}])
            return SimpleNamespace(output="done", prompt_tokens=1, completion_tokens=1, latency_ms=1,
                                   provider="p", model_name="m", hit_turn_limit=False)

    monkeypatch.setattr(ToolResilience, "run_function_call", _heal)
    monkeypatch.setattr(se, "LLMRouter", _Router)
    monkeypatch.setattr(FeatureFlags, "is_on", AsyncMock(return_value=False))   # every flag off
    monkeypatch.setattr(ToolAccess, "load", AsyncMock(return_value=ToolAccess(company_id=None, grants={})))
    db = MagicMock(commit=AsyncMock(), add=MagicMock(), execute=AsyncMock(side_effect=RuntimeError("no db")))
    svc = se.StepExecutorService(db=db, redis=None, company_id=uuid4(), usage_service=MagicMock(), cortex_bridge=None)
    svc._log_usage, svc._charge_tool, svc._log_tool_call = AsyncMock(), AsyncMock(), MagicMock()
    svc._skill_files = AsyncMock(return_value=[])
    svc._maybe_summarize_context = AsyncMock(side_effect=lambda _r, _e, ctx: ctx)
    run = SimpleNamespace(id=uuid4(), company_id=uuid4(), user_id=None, total_cost_usd=0, depth=0, max_depth=None)
    entity = SimpleNamespace(id=uuid4(), name="w", type="AGENT", company_id=run.company_id, goal="g",
                             capabilities={}, planning={}, logic_gate={}, identity={}, io_contract={},
                             governance={}, metadata_extensions={})
    await svc._execute_thought(run, entity, PlanStep(step_id="s1", name="find", type=StepType.THOUGHT), {"input": "x"})

    assert healed == ["web_search"]
    assert "tools.resilience_v2_enabled" not in DEFAULTS
