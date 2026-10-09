"""A step's text reaches the run page while it is generated (P9.13 — LP-I7, D26).

Streaming existed only in the voice path: for a long generation the user
watched a spinner for the whole call. Gemini now streams into a text sink;
Anthropic and Azure hand each turn's text over when it completes; the step
executor publishes throttled ``step_delta`` frames on the run's channel.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ai.core import agent_loop_sse
from src.ai.core.agent_loop_sse import StepTextStream
from src.ai.llm.gemini_adapter import GeminiAdapter
from src.ai.llm.retry import LLMTimeoutError


class _Sink:
    def __init__(self):
        self.events: list = []

    async def delta(self, text):
        self.events.append(text)

    async def reset(self):
        self.events.append("<reset>")


def _chunk(text=None, call=None, finish=None, usage=None):
    part = SimpleNamespace(text=text, function_call=call, thought=False)
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason=finish)],
                           usage_metadata=usage)


class _Streaming:
    """generate_content_stream yields the chunks; the first ``fail`` attempts
    break mid-stream."""

    def __init__(self, chunks, fail=0):
        self.chunks, self.fail, self.attempts = chunks, fail, 0
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content_stream=self._stream,
                                                          generate_content=self._whole))

    async def _whole(self, **_kw):
        raise AssertionError("a sink was given: the call must stream")

    async def _stream(self, **_kw):
        self.attempts += 1
        attempt = self.attempts

        async def gen():
            for i, chunk in enumerate(self.chunks):
                if attempt <= self.fail and i == 1:
                    raise LLMTimeoutError("stream stalled")
                yield chunk
        return gen()


USAGE = SimpleNamespace(prompt_token_count=5, candidates_token_count=3, thoughts_token_count=1)


@pytest.mark.asyncio
async def test_gemini_streams_into_the_sink_and_returns_the_whole_answer(monkeypatch):
    adapter = GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={})
    client = _Streaming([_chunk("The "), _chunk("answer."), _chunk(finish="STOP", usage=USAGE)])
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    sink = _Sink()
    resp = await adapter.generate(system_prompt="s", messages=[{"role": "user", "parts": [{"text": "q"}]}],
                                  text_sink=sink)
    assert sink.events == ["The ", "answer."]
    assert resp.output == "The answer."
    assert (resp.prompt_tokens, resp.completion_tokens, resp.thinking_tokens) == (5, 4, 1)


@pytest.mark.asyncio
async def test_a_retried_stream_resets_the_sink(monkeypatch):
    from src.ai.llm import retry

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(retry.asyncio, "sleep", no_sleep)
    adapter = GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={})
    client = _Streaming([_chunk("Half "), _chunk("done."), _chunk(finish="STOP", usage=USAGE)], fail=1)
    monkeypatch.setattr(adapter, "_build_client", lambda: client)
    sink = _Sink()
    resp = await adapter.generate(system_prompt="s", messages=[{"role": "user", "parts": [{"text": "q"}]}],
                                  text_sink=sink)
    assert sink.events == ["Half ", "<reset>", "Half ", "done."]
    assert resp.output == "Half done."


@pytest.mark.asyncio
async def test_a_streamed_react_turn_still_calls_its_tools(monkeypatch):
    adapter = GeminiAdapter(api_key="", model_name="gemini-2.0-flash", service_metadata={})
    turns = [
        [_chunk("Let me look. "), _chunk(call=SimpleNamespace(name="search", args={"q": "x"}, id=None)),
         _chunk(finish="STOP", usage=USAGE)],
        [_chunk("Found it."), _chunk(finish="STOP", usage=USAGE)],
    ]

    class _Turns(_Streaming):
        async def _stream(self, **_kw):
            chunks = turns[self.attempts]
            self.attempts += 1

            async def gen():
                for chunk in chunks:
                    yield chunk
            return gen()

    monkeypatch.setattr(adapter, "_build_client", lambda: _Turns([]))
    ran = []

    async def tools(calls):
        ran.extend(c["name"] for c in calls)
        return [{"tool": c["name"], "output": "ok", "success": True} for c in calls]

    sink = _Sink()
    resp = await adapter.generate_with_tools_react(
        system_prompt="s", initial_messages=[{"role": "user", "parts": [{"text": "q"}]}],
        tool_schemas=[], execute_tool_fn=tools, text_sink=sink)
    assert ran == ["search"]
    assert sink.events == ["Let me look. ", "Found it."]
    assert resp.output == "Let me look. Found it."


@pytest.mark.asyncio
async def test_anthropic_hands_over_each_turn_whole(monkeypatch):
    from src.ai.llm.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={})

    async def create(**_kw):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="All done.")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(adapter, "_build_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    sink = _Sink()
    await adapter.generate_with_tools_react(system_prompt="s", initial_messages=[{"role": "user", "parts": [{"text": "q"}]}],
                                            tool_schemas=[], execute_tool_fn=None, text_sink=sink)
    assert sink.events == ["All done."]


class _Redis:
    def __init__(self):
        self.frames = []

    async def xadd(self, key, fields, **_):
        self.frames.append((key, json.loads(fields["data"])))

    async def expire(self, *_):
        pass


@pytest.mark.asyncio
async def test_the_step_stream_publishes_throttled_frames(monkeypatch):
    redis, clock = _Redis(), [100.0]
    monkeypatch.setattr(agent_loop_sse, "_SSE_REDIS", redis)
    monkeypatch.setattr(agent_loop_sse, "_monotonic", lambda: clock[0])
    stream = StepTextStream("run-1", "research")

    await stream.delta("a")          # first frame goes at once
    await stream.delta("b")          # within 0.25 s: buffered
    await stream.delta("c")
    clock[0] += 0.3
    await stream.delta("d")          # past the interval: b+c+d
    await stream.reset()
    await stream.delta("x" * 500)    # past the size bound
    await stream.close()

    bodies = [b for _, b in redis.frames]
    assert {c for c, _ in redis.frames} == {"run_events:run-1"}
    assert bodies == [
        {"type": "step_delta", "step": "research", "text": "a"},
        {"type": "step_delta", "step": "research", "text": "bcd"},
        {"type": "step_delta", "step": "research", "reset": True},
        {"type": "step_delta", "step": "research", "text": "x" * 500},
        {"type": "step_delta", "step": "research", "done": True},
    ]


@pytest.mark.asyncio
async def test_a_fallback_voids_the_defaults_partial_text(monkeypatch):
    import uuid

    from src.ai.llm import router as router_mod
    from src.ai.llm.types import LLMResponse

    router_mod._BREAKER.reset()

    class _Failing:
        model_name = "a"

        async def generate(self, text_sink=None, **_kw):
            await text_sink.delta("partial")
            raise LLMTimeoutError("x")

    class _Spare:
        model_name = "b"

        async def generate(self, text_sink=None, **_kw):
            await text_sink.delta("whole")
            return LLMResponse(output="whole")

    router = router_mod.LLMRouter(db=None, company_id=uuid.uuid4())

    async def resolve(task_type, model_override=None):
        return _Failing()

    async def resolve_fallback(task_type):
        return _Spare()

    monkeypatch.setattr(router, "_resolve_adapter", resolve)
    monkeypatch.setattr(router, "_resolve_fallback", resolve_fallback)
    sink = _Sink()
    await router.call_llm(task_type="text_generation", system_prompt="s", user_prompt="u", text_sink=sink)
    assert sink.events == ["partial", "<reset>", "whole"]
    router_mod._BREAKER.reset()
