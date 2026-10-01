"""LP-03 and LP-04 — provider calls retry, time out, and fail honestly.

LP-03: there was no retry, backoff or timeout anywhere in the LLM layer, so one
429 from a provider failed the step. LP-04: the Gemini SDK's finish_reason
validation error was logged as "retrying with raw HTTP" (nothing retried) and,
in the ReAct loop, treated as a normal end of turn.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from src.ai.llm import retry as retry_mod
from src.ai.llm.retry import LLMTimeoutError, call_provider, is_retryable


class _HTTPError(Exception):
    def __init__(self, status: int, retry_after: str | None = None):
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.response = SimpleNamespace(status_code=status,
                                        headers={"retry-after": retry_after} if retry_after else {})


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    from src.common.config import settings
    monkeypatch.setattr(settings, "LLM_CALL_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "LLM_CALL_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(settings, "LLM_RETRY_MAX_DELAY_SECONDS", 30.0)


def _flaky(*errors: BaseException, result: Any = "ok"):
    calls = {"n": 0}

    async def call():
        calls["n"] += 1
        if calls["n"] <= len(errors):
            raise errors[calls["n"] - 1]
        return result
    return call, calls


@pytest.mark.asyncio
async def test_a_rate_limit_is_retried_until_it_succeeds():
    call, calls = _flaky(_HTTPError(429), _HTTPError(503))
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    assert await call_provider(call, what="t", sleep=sleep) == "ok"
    assert calls["n"] == 3 and len(slept) == 2


@pytest.mark.asyncio
async def test_a_client_error_is_not_retried():
    call, calls = _flaky(_HTTPError(400))
    with pytest.raises(_HTTPError):
        await call_provider(call, what="t")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_attempts_are_bounded():
    call, calls = _flaky(*[_HTTPError(429)] * 5)

    async def sleep(_s):
        pass

    with pytest.raises(_HTTPError):
        await call_provider(call, what="t", sleep=sleep)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retry_after_is_honoured():
    call, _ = _flaky(_HTTPError(429, retry_after="7"))
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    await call_provider(call, what="t", sleep=sleep)
    assert slept == [7.0]


@pytest.mark.asyncio
async def test_a_call_that_hangs_times_out(monkeypatch):
    from src.common.config import settings
    monkeypatch.setattr(settings, "LLM_CALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "LLM_CALL_MAX_ATTEMPTS", 2)

    async def hang():
        await asyncio.sleep(10)

    with pytest.raises(LLMTimeoutError, match="no answer within"):
        await call_provider(hang, what="gemini x")


def test_retryable_by_name_when_there_is_no_status():
    class APIConnectionError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    assert is_retryable(APIConnectionError())
    assert not is_retryable(AuthenticationError())
    assert not is_retryable(ValueError("bad"))


# ── adapters: one retry per provider call, never a re-run of the turn's tools ─


class _AzureFlaky:
    """Second model call fails once with 503, then answers."""

    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_kw):
        self.calls += 1
        if self.calls == 2:
            raise _HTTPError(503)
        if self.calls == 1:
            tc = SimpleNamespace(id="t1", function=SimpleNamespace(name="search", arguments="{}"))
            msg = SimpleNamespace(content=None, tool_calls=[tc])
        else:
            msg = SimpleNamespace(content="done", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


@pytest.mark.asyncio
async def test_a_failed_react_turn_retries_the_model_call_not_the_tools(monkeypatch):
    from src.ai.llm.azure_adapter import AzureOpenAIAdapter

    adapter = AzureOpenAIAdapter(api_key="", model_name="gpt-x", service_metadata={})
    client = _AzureFlaky()
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    monkeypatch.setattr(adapter, "_get_deployment", lambda: "d")
    tool_runs: list = []

    async def tools(calls):
        tool_runs.append(calls)
        return [{"tool": c["name"], "output": "ok", "success": True} for c in calls]

    resp = await adapter.generate_with_tools_react(
        system_prompt="s", initial_messages=[{"role": "user", "parts": [{"text": "hi"}]}],
        tool_schemas=[], execute_tool_fn=tools, max_react_turns=5,
    )
    assert resp.output == "done"
    assert client.calls == 3
    assert len(tool_runs) == 1


def test_sdk_clients_do_not_retry_on_their_own():
    from src.ai.llm.azure_adapter import AzureOpenAIAdapter

    for endpoint in ("https://r.openai.azure.com", "https://r.services.ai.azure.com",
                     "https://m.models.ai.azure.com"):
        adapter = AzureOpenAIAdapter(api_key="k", model_name="gpt-x",
                                     service_metadata={"endpoint": endpoint, "azure_endpoint": endpoint})
        assert adapter._build_client().max_retries == 0


# ── LP-04: the Gemini SDK validation error ──────────────────────────────────


class ValidationError(Exception):
    """Named like pydantic's, which is how the adapter recognises it."""


class _GeminiBroken:
    def __init__(self):
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, **_kw):
        raise ValidationError("1 validation error for Candidate finish_reason: Input should be ...")


def _gemini(monkeypatch):
    from src.ai.llm.gemini_adapter import GeminiAdapter

    adapter = GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={})
    monkeypatch.setattr(adapter, "_build_client", lambda: _GeminiBroken())
    return adapter


@pytest.mark.asyncio
async def test_the_gemini_validation_error_fails_a_react_loop(monkeypatch):
    adapter = _gemini(monkeypatch)

    async def tools(_calls):
        return []

    with pytest.raises(RuntimeError, match="finish_reason"):
        await adapter.generate_with_tools_react(
            system_prompt="s", initial_messages=[{"role": "user", "parts": [{"text": "hi"}]}],
            tool_schemas=[], execute_tool_fn=tools,
        )


@pytest.mark.asyncio
async def test_the_gemini_validation_error_does_not_claim_a_retry(monkeypatch, caplog):
    adapter = _gemini(monkeypatch)
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError, match="finish_reason"):
        await adapter.generate(system_prompt="s", messages=[{"role": "user", "parts": [{"text": "hi"}]}])
    assert "retrying" not in caplog.text.lower()
    assert retry_mod  # the module under test is importable
