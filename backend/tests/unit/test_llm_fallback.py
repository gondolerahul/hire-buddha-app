"""A task default's fallback integration is used when the default is exhausted
(P9.12 — LP-08, D25).

``routing_mode`` ('single' | 'router') was stored, returned and rendered, and
read by nothing — there was no second provider. Now a task default may name a
fallback integration: when the default's call fails after its retries, the
router calls the fallback; a ReAct loop falls back only before its first tool
ran; and after three exhausted failures a breaker sends calls straight to the
fallback for a minute.
"""
from __future__ import annotations

import uuid

import pytest

from src.ai.llm import router as router_mod
from src.ai.llm.retry import LLMTimeoutError
from src.ai.llm.types import LLMResponse


class _Adapter:
    def __init__(self, name, fail=None, tool_first=False):
        self.provider, self.model_name, self.fail, self.tool_first = name, f"{name}-model", fail, tool_first
        self.calls = 0

    async def generate(self, **kw):
        self.calls += 1
        if self.fail:
            raise self.fail
        return LLMResponse(output=f"from {self.provider}", model_name=self.model_name)

    async def generate_with_tools_react(self, execute_tool_fn=None, **kw):
        self.calls += 1
        if self.tool_first:
            await execute_tool_fn([{"id": "c1", "name": "search", "args": {}}])
        if self.fail:
            raise self.fail
        return LLMResponse(output=f"from {self.provider}", model_name=self.model_name)


@pytest.fixture(autouse=True)
def fresh_breaker():
    router_mod._BREAKER.reset()
    yield
    router_mod._BREAKER.reset()


def _router(monkeypatch, primary, fallback):
    router = router_mod.LLMRouter(db=None, company_id=uuid.uuid4())

    async def resolve(task_type, model_override=None):
        return primary

    async def resolve_fallback(task_type):
        return fallback

    monkeypatch.setattr(router, "_resolve_adapter", resolve)
    monkeypatch.setattr(router, "_resolve_fallback", resolve_fallback)
    return router


async def _call(router, **kw):
    return await router.call_llm(task_type="text_generation", system_prompt="s", user_prompt="u", **kw)


async def _tools(calls):
    return [{"tool": c["name"], "output": "ok", "success": True} for c in calls]


@pytest.mark.asyncio
async def test_an_exhausted_default_falls_back(monkeypatch):
    primary, fallback = _Adapter("vertex", fail=LLMTimeoutError("no answer")), _Adapter("azure")
    resp = await _call(_router(monkeypatch, primary, fallback))
    assert resp.output == "from azure" and resp.model_name == "azure-model"  # billed as the fallback


@pytest.mark.asyncio
async def test_a_request_error_does_not_fall_back(monkeypatch):
    primary, fallback = _Adapter("vertex", fail=ValueError("400 bad request")), _Adapter("azure")
    with pytest.raises(ValueError):
        await _call(_router(monkeypatch, primary, fallback))
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_without_a_fallback_the_error_stands(monkeypatch):
    with pytest.raises(LLMTimeoutError):
        await _call(_router(monkeypatch, _Adapter("vertex", fail=LLMTimeoutError("x")), None))


@pytest.mark.asyncio
async def test_an_override_never_falls_back(monkeypatch):
    primary, fallback = _Adapter("vertex", fail=LLMTimeoutError("x")), _Adapter("azure")
    with pytest.raises(LLMTimeoutError):
        await _call(_router(monkeypatch, primary, fallback), model_override="gemini-2.5-pro")
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_a_react_loop_falls_back_only_before_a_tool_ran(monkeypatch):
    react = dict(task_type="text_generation", system_prompt="s", user_prompt="u", tool_schemas=[],
                 execute_tool_fn=_tools)
    early = _router(monkeypatch, _Adapter("vertex", fail=LLMTimeoutError("x")), _Adapter("azure"))
    assert (await early.call_llm_react(**react)).output == "from azure"

    fallback = _Adapter("azure")
    late = _router(monkeypatch, _Adapter("vertex", fail=LLMTimeoutError("x"), tool_first=True), fallback)
    with pytest.raises(LLMTimeoutError):
        await late.call_llm_react(**react)
    assert fallback.calls == 0  # the tool would run twice


@pytest.mark.asyncio
async def test_the_breaker_skips_a_failing_default_for_a_minute(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(router_mod, "_monotonic", lambda: clock[0])
    primary, fallback = _Adapter("vertex", fail=LLMTimeoutError("x")), _Adapter("azure")
    router = _router(monkeypatch, primary, fallback)
    for _ in range(3):
        await _call(router)
    assert primary.calls == 3

    await _call(router)
    assert primary.calls == 3 and fallback.calls == 4  # open: straight to the fallback

    clock[0] += 61
    primary.fail = None
    assert (await _call(router)).output == "from vertex"  # tried again, and it is closed
    await _call(router)
    assert primary.calls == 5
