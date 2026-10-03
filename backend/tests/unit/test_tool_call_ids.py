"""Tool results go back to the call they answer, on every provider (P9.8 — LP-17),
and ``top_p`` reaches every ReAct loop (LP-20).

Gemini and Anthropic paired a result with its call by tool *name*. Two calls to
one tool in a turn — the normal case for a search — were answered with the
first call's id twice (Anthropic rejects that) or with the wrong name when a
fallback tool ran (Gemini). ``top_p`` was honoured by ``generate`` only.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.ai.llm.anthropic_adapter import AnthropicAdapter
from src.ai.llm.azure_adapter import AzureOpenAIAdapter
from src.ai.llm.base import pair_tool_results
from src.ai.llm.gemini_adapter import GeminiAdapter


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "parts": [{"text": "compare"}]}]


async def _tools(calls: list[dict]) -> list[dict]:
    # The second call was answered by a fallback tool: the result names it.
    return [{"tool": "search" if i == 0 else "search_fallback", "output": f"result of {c['args']['q']}",
             "success": True} for i, c in enumerate(calls)]


class _Turns:
    """A fake client: turn one calls ``search`` twice, turn two answers."""

    def __init__(self):
        self.requests: list[dict] = []

    def turn(self, kw) -> int:
        self.requests.append(kw)
        return len(self.requests)


class _Anthropic(_Turns):
    def __init__(self):
        super().__init__()
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        if self.turn({**kw, "messages": list(kw["messages"])}) == 1:
            content = [SimpleNamespace(type="tool_use", name="search", input={"q": "a"}, id="tu_a"),
                       SimpleNamespace(type="tool_use", name="search", input={"q": "b"}, id="tu_b")]
        else:
            content = [SimpleNamespace(type="text", text="done")]
        return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class _Azure(_Turns):
    def __init__(self):
        super().__init__()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        if self.turn({**kw, "messages": list(kw["messages"])}) == 1:
            calls = [SimpleNamespace(id=i, function=SimpleNamespace(name="search", arguments=json.dumps({"q": q})))
                     for i, q in (("c_a", "a"), ("c_b", "b"))]
            msg = SimpleNamespace(content=None, tool_calls=calls)
        else:
            msg = SimpleNamespace(content="done", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


class _Gemini(_Turns):
    def __init__(self, ids=(None, None)):
        super().__init__()
        self.ids = ids
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, **kw):
        if self.turn({**kw, "contents": list(kw["contents"])}) == 1:
            parts = [SimpleNamespace(text=None, function_call=SimpleNamespace(name="search", args={"q": q}, id=i))
                     for q, i in zip(("a", "b"), self.ids)]
            text = None
        else:
            parts, text = [SimpleNamespace(text="done", function_call=None)], "done"
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason="STOP")],
            text=text,
            usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0),
        )


async def _run(adapter, client, monkeypatch, **kw):
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    return await adapter.generate_with_tools_react(
        system_prompt="s", initial_messages=_messages(), tool_schemas=[], execute_tool_fn=_tools, **kw)


@pytest.mark.asyncio
async def test_anthropic_answers_each_tool_use_with_its_own_id(monkeypatch):
    client = _Anthropic()
    resp = await _run(AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={}), client, monkeypatch)
    results = client.requests[1]["messages"][-1]["content"]
    assert [(r["tool_use_id"], r["content"]) for r in results] == [("tu_a", "result of a"), ("tu_b", "result of b")]
    assert [c["id"] for c in resp.function_calls] == ["tu_a", "tu_b"]


@pytest.mark.asyncio
async def test_azure_answers_each_call_with_its_id(monkeypatch):
    client = _Azure()
    adapter = AzureOpenAIAdapter(api_key="", model_name="gpt-4o", service_metadata={})
    monkeypatch.setattr(adapter, "_get_deployment", lambda: "d")
    await _run(adapter, client, monkeypatch)
    tool_msgs = [m for m in client.requests[1]["messages"] if m.get("role") == "tool"]
    assert [(m["tool_call_id"], m["content"]) for m in tool_msgs] == [("c_a", "result of a"), ("c_b", "result of b")]


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [(None, None), ("g_a", "g_b")])
async def test_gemini_answers_in_call_order_with_the_calls_name_and_id(ids, monkeypatch):
    client = _Gemini(ids)
    resp = await _run(GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={}),
                      client, monkeypatch)
    answer = client.requests[1]["contents"][-1].parts
    got = [(p.function_response.name, p.function_response.id, p.function_response.response["output"])
           for p in answer]
    assert got == [("search", ids[0], "result of a"), ("search", ids[1], "result of b")]
    assert len({c["id"] for c in resp.function_calls}) == 2  # every call has its own id


def test_a_missing_result_is_an_error_not_a_misfit():
    with pytest.raises(RuntimeError, match="1 results for 2 calls"):
        pair_tool_results([{"id": "a"}, {"id": "b"}], [{"output": "x"}])


@pytest.mark.asyncio
async def test_top_p_reaches_every_react_loop(monkeypatch):
    anthropic, azure, gemini = _Anthropic(), _Azure(), _Gemini()
    await _run(AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={}), anthropic, monkeypatch,
               top_p=0.5)
    az = AzureOpenAIAdapter(api_key="", model_name="gpt-4o", service_metadata={})
    monkeypatch.setattr(az, "_get_deployment", lambda: "d")
    await _run(az, azure, monkeypatch, top_p=0.5)
    await _run(GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={}), gemini, monkeypatch,
               top_p=0.5)
    assert anthropic.requests[0]["top_p"] == 0.5
    assert azure.requests[0]["top_p"] == 0.5
    assert gemini.requests[0]["config"].top_p == 0.5


@pytest.mark.asyncio
async def test_a_default_top_p_is_not_sent_to_claude(monkeypatch):
    """Newer Claude models refuse temperature and top_p together."""
    client = _Anthropic()
    await _run(AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={}), client, monkeypatch)
    assert "top_p" not in client.requests[0]


@pytest.mark.asyncio
async def test_the_router_forwards_top_p(monkeypatch):
    import uuid

    from src.ai.llm.router import LLMRouter

    seen = {}

    class _Adapter:
        async def generate_with_tools_react(self, **kw):
            seen.update(kw)
            from src.ai.llm.types import LLMResponse
            return LLMResponse(output="ok")

    router = LLMRouter(db=None, company_id=uuid.uuid4())

    async def resolve(task_type, model_override=None):
        return _Adapter()

    monkeypatch.setattr(router, "_resolve_adapter", resolve)
    await router.call_llm_react(task_type="text_generation", system_prompt="s", user_prompt="u",
                                tool_schemas=[], execute_tool_fn=_tools, top_p=0.3)
    assert seen["top_p"] == 0.3
