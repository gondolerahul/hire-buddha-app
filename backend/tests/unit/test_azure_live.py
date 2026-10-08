"""Azure OpenAI Realtime works where Gemini Live does (VT-02, HD10).

The factory returned a ``(client, config)`` tuple where the handler expected a
live client; the handler kept the client, which has no ``receive``; the
browser adapter called ``AudioProcessor.pcm24_to_pcm16``, which did not exist;
and the websocket was opened with an argument websockets 13 does not take.
Now the factory's Azure client connects like Gemini's and its session speaks
the Gemini Live shape the callers read. A fake Azure socket stands in.
"""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from src.voice.audio_processor import AudioProcessor
from src.voice.call_guards import END_CALL_TOOL
from src.voice.live_usage import LiveUsage


class _AzureSocket:
    """The Azure Realtime websocket: records what is sent, replays ``events``."""

    def __init__(self, events=()):
        self.sent: list[dict] = []
        self.events = [json.dumps(e) for e in events]
        self.closed = False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for raw in self.events:
            yield raw

    async def close(self):
        self.closed = True


@pytest.fixture
def azure(monkeypatch):
    """The speech_to_speech default is an Azure Realtime deployment; connecting opens the fake socket."""
    socket = _AzureSocket()
    opened: dict = {}

    async def _resolve(self, company_id, task_type):
        return SimpleNamespace(provider_name="azure_openai", model_name="gpt-4o-realtime-preview",
                               service_metadata={"azure_endpoint": "https://hb.openai.azure.com"}), "key"

    async def _connect(url, additional_headers=None):
        opened.update(url=url, headers=additional_headers)
        return socket

    monkeypatch.setattr("src.config.service.ConfigService.resolve_model_for_task", _resolve)
    monkeypatch.setattr("websockets.asyncio.client.connect", _connect)
    return SimpleNamespace(socket=socket, opened=opened)


async def _session(azure, tools=()):
    from src.voice.live_client_factory import LiveClientFactory

    client, provider = await LiveClientFactory(db=None, company_id=None).create_client(
        system_instruction="You are a receptionist.", voice_config={"voice_name": "Aoede"})
    assert provider == "azure_openai" and not isinstance(client, tuple)
    connection = await client.connect(tools=list(tools))
    return connection, await connection.__aenter__()


@pytest.mark.asyncio
async def test_the_factorys_azure_client_connects_like_gemini(azure):
    connection, session = await _session(azure, tools=[END_CALL_TOOL])

    assert azure.opened["headers"] == {"api-key": "key", "Content-Type": "application/json"}
    assert azure.opened["url"].startswith("wss://hb.openai.azure.com/openai/realtime?")
    [update] = azure.socket.sent
    assert update["type"] == "session.update"
    config = update["session"]
    assert config["instructions"] == "You are a receptionist." and config["voice"] == "nova"
    assert config["input_audio_transcription"] == {"model": "whisper-1"}
    assert config["tools"] == [{"type": "function", "name": "end_call",
                                "description": END_CALL_TOOL["description"],
                                "parameters": END_CALL_TOOL["parameters"]}]
    await connection.__aexit__(None, None, None)
    assert azure.socket.closed


@pytest.mark.asyncio
async def test_audio_is_resampled_to_24khz_and_text_asks_for_a_response(azure):
    from google.genai import types as genai_types

    _, session = await _session(azure)
    azure.socket.sent.clear()
    tone = AudioProcessor.generate_silence(100, sample_rate=16000)            # 100 ms at 16 kHz
    await session.send_realtime_input(audio=genai_types.Blob(data=tone, mime_type="audio/pcm;rate=16000"))
    await session.send_realtime_input(audio={"data": tone, "mime_type": "audio/pcm;rate=16000"})
    await session.send_realtime_input(text="[Call connected. Greet the caller.]")

    first, second, item, respond = azure.socket.sent
    assert first["type"] == second["type"] == "input_audio_buffer.append"
    sent = len(base64.b64decode(first["audio"])) + len(base64.b64decode(second["audio"]))
    assert abs(sent - 2 * len(tone) * 3 // 2) <= 8                              # 24 kHz: 1.5x the bytes
    assert item["item"]["content"] == [{"type": "input_text", "text": "[Call connected. Greet the caller.]"}]
    assert respond == {"type": "response.create"}


@pytest.mark.asyncio
async def test_azure_events_read_as_gemini_messages(azure):
    audio = b"\x01\x02" * 480
    azure.socket.events = [json.dumps(e) for e in [
        {"type": "session.created"},
        {"type": "response.created"},
        {"type": "response.audio.delta", "delta": base64.b64encode(audio).decode()},
        {"type": "response.audio_transcript.done", "transcript": "Hello, how can I help?"},
        {"type": "input_audio_buffer.speech_started"},                  # over the model: a barge-in
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Book me in."},
        {"type": "response.function_call_arguments.done", "call_id": "c1", "name": "book",
         "arguments": "{\"when\": \"tomorrow\"}"},
        {"type": "response.done", "response": {"usage": {
            "input_tokens": 120, "output_tokens": 80,
            "input_token_details": {"text_tokens": 100, "audio_tokens": 20},
            "output_token_details": {"text_tokens": 30, "audio_tokens": 50}}}},
        {"type": "input_audio_buffer.speech_started"},                  # into silence: nothing to interrupt
    ]]
    _, session = await _session(azure)

    messages = []
    with pytest.raises(ConnectionError):                                # the socket closed
        async for message in session.receive():
            messages.append(message)

    data, agent, barge_in, caller, tool, done, quiet = messages
    assert data.data == audio and data.server_content is None
    assert agent.server_content.output_transcription.text == "Hello, how can I help?"
    assert barge_in.server_content.interrupted is True
    assert barge_in.voice_activity.voice_activity_type == "ACTIVITY_START"
    assert caller.server_content.input_transcription.text == "Book me in."
    [call] = tool.tool_call.function_calls
    assert (call.id, call.name, call.args) == ("c1", "book", {"when": "tomorrow"})
    assert done.server_content.turn_complete and quiet.server_content is None

    usage = LiveUsage()
    for message in messages:
        usage.add(message.usage_metadata)
    assert usage.reported and (usage.prompt_tokens, usage.response_tokens) == (120, 80)
    assert usage.prompt_by_modality == {"TEXT": 100, "AUDIO": 20}
    assert usage.response_by_modality == {"TEXT": 30, "AUDIO": 50}


@pytest.mark.asyncio
async def test_tool_results_go_back_with_their_ids_and_one_response(azure):
    from google.genai import types as genai_types

    _, session = await _session(azure)
    azure.socket.sent.clear()
    await session.send_tool_response(function_responses=[
        genai_types.FunctionResponse(id="c1", name="book", response={"output": "booked", "success": True}),
        genai_types.FunctionResponse(id="c2", name="end_call", response={"output": "bye", "success": True}),
    ])

    first, second, respond = azure.socket.sent
    assert first["item"] == {"type": "function_call_output", "call_id": "c1",
                             "output": json.dumps({"output": "booked", "success": True})}
    assert second["item"]["call_id"] == "c2"
    assert respond == {"type": "response.create"}


def test_pcm24_to_pcm16_resamples_for_the_browser():
    pcm24 = b"\x10\x00" * 2400                                          # 100 ms at 24 kHz
    pcm16 = AudioProcessor.pcm24_to_pcm16(pcm24)
    assert abs(len(pcm16) - 3200) <= 4                                  # 100 ms at 16 kHz


@pytest.mark.asyncio
async def test_the_stream_handler_runs_a_call_on_azure(azure, monkeypatch):
    """The handler's receive loop, unchanged, on an Azure session: audio, both transcripts, tools."""
    import uuid

    from src.voice.websocket_handler import BaseStreamHandler

    audio = b"\x05\x00" * 960
    azure.socket.events = [json.dumps(e) for e in [
        {"type": "response.created"},
        {"type": "response.audio.delta", "delta": base64.b64encode(audio).decode()},
        {"type": "response.audio_transcript.done", "transcript": "Hello, this is Asha."},
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Hi Asha."},
        {"type": "response.function_call_arguments.done", "call_id": "c9", "name": "book", "arguments": "{}"},
        {"type": "response.done", "response": {"usage": {"input_tokens": 10, "output_tokens": 5}}},
    ]]
    _, session = await _session(azure)
    handler = BaseStreamHandler(websocket=None, db=None)
    handler.session_id, handler.mobile = uuid.uuid4(), None
    handler.gemini_session, handler.is_running = session, True
    played, tools = [], []

    async def _play(data):
        played.append(data)

    async def _tool(call):
        tools.append(call)

    monkeypatch.setattr(handler, "_play_model_audio", _play)
    monkeypatch.setattr(handler, "_handle_tool_call", _tool)

    await handler._receive_from_live_client()          # ends when the socket closes
    await asyncio.sleep(0)

    assert played == [audio] and handler.is_running is False
    assert handler._agent_transcript_buffer.strip() == "Hello, this is Asha."
    assert handler._customer_transcript_buffer.strip() == "Hi Asha."
    assert [fc.id for fc in tools[0].function_calls] == ["c9"]
    assert handler._live_usage.reported and handler._live_usage.prompt_tokens == 10
