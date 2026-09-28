"""LP-25 — thinking tokens must not starve a capped Gemini answer.

Gemini 2.5+ counts thinking against ``max_output_tokens``. Callers size
``max_tokens`` for the answer, so the adapter adds an explicit thinking
budget on top; before this, a 400-token planner-judge call returned 13
visible tokens and every structured answer failed to parse.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from src.ai.llm.gemini_adapter import DEFAULT_THINKING_BUDGET, GeminiAdapter


def _adapter(model: str = "gemini-2.5-flash", **metadata: Any) -> GeminiAdapter:
    return GeminiAdapter(api_key="", model_name=model, service_metadata=metadata)


def _limits(adapter: GeminiAdapter, max_tokens: Optional[int]) -> Any:
    from google.genai import types
    config = types.GenerateContentConfig()
    adapter._apply_output_limits(config, max_tokens)
    return config


def _budget(config: Any) -> Optional[int]:
    return config.thinking_config.thinking_budget if config.thinking_config else None


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview"])
def test_capped_call_on_a_thinking_model_gets_thinking_on_top(model: str) -> None:
    config = _limits(_adapter(model), 400)
    assert _budget(config) == DEFAULT_THINKING_BUDGET
    assert config.max_output_tokens == 400 + DEFAULT_THINKING_BUDGET


def test_uncapped_call_keeps_dynamic_thinking() -> None:
    config = _limits(_adapter(), None)
    assert config.thinking_config is None
    assert config.max_output_tokens is None


def test_non_thinking_model_is_untouched() -> None:
    config = _limits(_adapter("gemini-2.0-flash"), 400)
    assert config.thinking_config is None
    assert config.max_output_tokens == 400


@pytest.mark.parametrize("configured, expected", [(0, 0), ("2048", 2048), (-5, 0)])
def test_integration_budget_overrides_the_default(configured: Any, expected: int) -> None:
    config = _limits(_adapter(thinking_budget=configured), 400)
    assert _budget(config) == expected
    assert config.max_output_tokens == 400 + expected


def test_configured_budget_applies_to_uncapped_calls_too() -> None:
    config = _limits(_adapter(thinking_budget=512), None)
    assert _budget(config) == 512
    assert config.max_output_tokens is None


def test_invalid_budget_falls_back_to_default() -> None:
    config = _limits(_adapter(thinking_budget="lots"), 400)
    assert _budget(config) == DEFAULT_THINKING_BUDGET


# ---------------------------------------------------------------------------
# generate / ReAct wiring
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, finish_reason: str = "FinishReason.STOP") -> None:
        self.configs: list[Any] = []
        self.finish_reason = finish_reason
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model: str, contents: Any, config: Any) -> Any:
        self.configs.append(config)
        part = SimpleNamespace(text='{"ok": true}', function_call=None)
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]),
                                        finish_reason=self.finish_reason)],
            text='{"ok": true}',
            usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5,
                                           thoughts_token_count=1019),
        )


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "parts": [{"text": "hi"}]}]


@pytest.mark.asyncio
async def test_generate_sends_the_thinking_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _adapter(), _FakeClient()
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    await adapter.generate(system_prompt="s", messages=_messages(), max_tokens=400)
    assert client.configs[0].max_output_tokens == 400 + DEFAULT_THINKING_BUDGET
    assert _budget(client.configs[0]) == DEFAULT_THINKING_BUDGET


@pytest.mark.asyncio
async def test_react_sends_the_thinking_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _adapter(), _FakeClient()
    monkeypatch.setattr(adapter, "_build_client", lambda: client)

    async def no_tools(calls: list[Any]) -> list[Any]:
        return []

    await adapter.generate_with_tools_react(
        system_prompt="s", initial_messages=_messages(), tool_schemas=[],
        execute_tool_fn=no_tools, max_tokens=300,
    )
    assert client.configs[0].max_output_tokens == 300 + DEFAULT_THINKING_BUDGET


@pytest.mark.asyncio
async def test_truncated_answer_is_logged(monkeypatch: pytest.MonkeyPatch,
                                          caplog: pytest.LogCaptureFixture) -> None:
    adapter, client = _adapter(), _FakeClient(finish_reason="FinishReason.MAX_TOKENS")
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    with caplog.at_level(logging.WARNING, logger="src.ai.llm.gemini_adapter"):
        await adapter.generate(system_prompt="s", messages=_messages(), max_tokens=400)
    assert "truncated at max_tokens=400" in caplog.text
    assert "thinking 1019 tokens" in caplog.text


@pytest.mark.asyncio
async def test_complete_answer_is_not_logged(monkeypatch: pytest.MonkeyPatch,
                                             caplog: pytest.LogCaptureFixture) -> None:
    adapter, client = _adapter(), _FakeClient()
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    with caplog.at_level(logging.WARNING, logger="src.ai.llm.gemini_adapter"):
        await adapter.generate(system_prompt="s", messages=_messages(), max_tokens=400)
    assert "truncated" not in caplog.text
