"""LP-19 — a ReAct loop that runs out of turns says so.

Before the fix every adapter's loop ended at ``max_react_turns`` exactly as if
the model had finished, so a model cut off mid-task (possibly with empty
output) looked like a finished step to the critics and the run status.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.ai.llm.anthropic_adapter import AnthropicAdapter
from src.ai.llm.azure_adapter import AzureOpenAIAdapter
from src.ai.llm.gemini_adapter import GeminiAdapter
from src.ai.llm.types import FINISH_MAX_TURNS, LLMResponse
from src.ai.step_executor import llm_step_result


async def _tools(calls: list[dict]) -> list[dict]:
    return [{"tool": c["name"], "output": "ok", "success": True} for c in calls]


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "parts": [{"text": "hi"}]}]


# ── fake provider clients: ``calls_tools`` decides every turn's shape ────────


class _Anthropic:
    def __init__(self, calls_tools: bool):
        self.calls_tools = calls_tools
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **_kw):
        block = (SimpleNamespace(type="tool_use", name="search", input={}, id="t1")
                 if self.calls_tools else SimpleNamespace(type="text", text="done"))
        return SimpleNamespace(content=[block],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class _Azure:
    def __init__(self, calls_tools: bool):
        self.calls_tools = calls_tools
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_kw):
        calls = ([SimpleNamespace(id="t1", function=SimpleNamespace(name="search", arguments=json.dumps({})))]
                 if self.calls_tools else None)
        msg = SimpleNamespace(content=None if self.calls_tools else "done", tool_calls=calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


class _Gemini:
    def __init__(self, calls_tools: bool):
        self.calls_tools = calls_tools
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, **_kw):
        part = (SimpleNamespace(text=None, function_call=SimpleNamespace(name="search", args={}))
                if self.calls_tools else SimpleNamespace(text="done", function_call=None))
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")],
            text=None if self.calls_tools else "done",
            usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1,
                                           thoughts_token_count=0),
        )


def _anthropic(calls_tools):
    a = AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={})
    return a, _Anthropic(calls_tools)


def _azure(calls_tools):
    a = AzureOpenAIAdapter(api_key="", model_name="gpt-x", service_metadata={})
    return a, _Azure(calls_tools)


def _gemini(calls_tools):
    a = GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={})
    return a, _Gemini(calls_tools)


@pytest.mark.asyncio
@pytest.mark.parametrize("make", [_anthropic, _azure, _gemini])
async def test_running_out_of_turns_is_reported(make, monkeypatch):
    adapter, client = make(calls_tools=True)
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    if hasattr(adapter, "_get_deployment"):
        monkeypatch.setattr(adapter, "_get_deployment", lambda: "d")
    resp = await adapter.generate_with_tools_react(
        system_prompt="s", initial_messages=_messages(), tool_schemas=[],
        execute_tool_fn=_tools, max_react_turns=3,
    )
    assert resp.finish_reason == FINISH_MAX_TURNS
    assert resp.hit_turn_limit
    assert len(resp.function_calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("make", [_anthropic, _azure, _gemini])
async def test_a_model_that_finishes_is_not_cut_off(make, monkeypatch):
    adapter, client = make(calls_tools=False)
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    if hasattr(adapter, "_get_deployment"):
        monkeypatch.setattr(adapter, "_get_deployment", lambda: "d")
    resp = await adapter.generate_with_tools_react(
        system_prompt="s", initial_messages=_messages(), tool_schemas=[],
        execute_tool_fn=_tools, max_react_turns=3,
    )
    assert not resp.hit_turn_limit
    assert resp.output == "done"


def test_a_cut_off_step_reports_an_error():
    cut = LLMResponse(output="half", finish_reason=FINISH_MAX_TURNS)
    result = llm_step_result("research", "half", cut, "REACT")
    assert result["output"] == "half"
    assert "cut off" in result["error"]

    done = LLMResponse(output="all")
    assert "error" not in llm_step_result("research", "all", done, "REACT")
