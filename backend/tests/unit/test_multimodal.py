"""Images reach the model as images (P9.10 — LP-24).

The adapters built text parts only. The video gateway worked around it by
base64-encoding a JPEG into the user prompt string (on a task type the API
rejected), so the model got a wall of base64 text and the blob landed in the
prompt everywhere the prompt is recorded.
"""
from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace

import pytest

from src.ai.llm.anthropic_adapter import AnthropicAdapter
from src.ai.llm.azure_adapter import AzureOpenAIAdapter
from src.ai.llm.gemini_adapter import GeminiAdapter
from src.ai.llm.types import Attachment, LLMResponse

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
FRAME = Attachment(mime_type="image/jpeg", data=JPEG)


def _message():
    return [{"role": "user", "parts": [{"text": "What is here?"}, FRAME.part()]}]


def test_gemini_sends_the_bytes_as_a_part():
    _, contents = GeminiAdapter(api_key="", model_name="gemini-2.5-flash", service_metadata={}) \
        ._build_contents("s", _message())
    text, image = contents[0].parts
    assert text.text == "What is here?"
    assert (image.inline_data.mime_type, image.inline_data.data) == ("image/jpeg", JPEG)


def test_anthropic_sends_an_image_block():
    _, messages = AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={}) \
        ._build_messages("s", _message())
    image, text = messages[0]["content"]
    assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(JPEG).decode()}}
    assert text == {"type": "text", "text": "What is here?"}


def test_azure_sends_a_data_url():
    messages = AzureOpenAIAdapter(api_key="", model_name="gpt-4o", service_metadata={}) \
        ._build_messages("s", _message())
    text, image = messages[1]["content"]
    assert text == {"type": "text", "text": "What is here?"}
    assert image["image_url"]["url"] == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


def test_a_text_message_is_unchanged():
    _, messages = AnthropicAdapter(api_key="", model_name="claude-x", service_metadata={}) \
        ._build_messages("s", [{"role": "user", "parts": [{"text": "hi"}]}])
    assert messages == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_the_router_attaches_and_the_span_records_only_a_description(monkeypatch):
    from src.ai.llm import router as router_mod

    seen, spans = {}, []

    class _Adapter:
        async def generate(self, **kw):
            seen.update(kw)
            return LLMResponse(output="a face")

    class _Span:
        def __init__(self, *a, **kw):
            spans.append(kw)

        async def __aenter__(self):
            return SimpleNamespace(set_output=lambda *a, **k: None, set_tokens=lambda *a, **k: None,
                                   update=lambda **k: None)

        async def __aexit__(self, *exc):
            return False

    router = router_mod.LLMRouter(db=None, company_id=uuid.uuid4())

    async def resolve(task_type, model_override=None):
        return _Adapter()

    monkeypatch.setattr(router, "_resolve_adapter", resolve)
    monkeypatch.setattr(router_mod, "_trace_span", _Span)
    await router.call_llm(task_type="vision", system_prompt="s", user_prompt="Describe this frame.",
                          attachments=[FRAME])
    assert seen["messages"][-1]["parts"] == [{"text": "Describe this frame."}, FRAME.part()]
    assert spans[0]["attachments"] == [f"[image/jpeg, {len(JPEG)} bytes]"]
    assert "base64" not in spans[0]["user_prompt"]


@pytest.mark.asyncio
async def test_the_video_gateway_sends_the_frame_as_an_image(monkeypatch):
    from src.gateway import video_gateway

    calls = []

    class _Router:
        def __init__(self, db, company_id):
            pass

        async def call_llm(self, **kw):
            calls.append(kw)
            return LLMResponse(output="One person, smiling.")

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("src.ai.llm.router.LLMRouter", _Router)
    monkeypatch.setattr("src.common.database.AsyncSessionLocal", lambda: _Session())
    session = SimpleNamespace(agent_info={"company_id": str(uuid.uuid4())}, vision_context="")
    await video_gateway.VideoSession._analyze_video_frame(session, JPEG)

    (call,) = calls
    assert call["task_type"] == "vision"
    assert call["attachments"] == [FRAME]
    assert "base64" not in call["user_prompt"]
    assert session.vision_context == "One person, smiling."
