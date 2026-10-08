"""
Azure OpenAI GPT-4 Realtime Audio Adapter

Implements real-time bidirectional speech-to-speech streaming using the
Azure OpenAI GPT-4 Realtime API (WebSocket-based).

This is a separate adapter from the standard AzureOpenAIAdapter in llm_router.py
because the Realtime API uses a persistent WebSocket connection rather than
standard HTTP request/response.

Reference: https://learn.microsoft.com/en-us/azure/ai-services/openai/realtime-audio-reference
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import copy
import json
import logging
import re
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default GPT-4 Realtime model name
GPT4_REALTIME_MODEL = "gpt-4o-realtime-preview"
# Default audio format for input/output
DEFAULT_INPUT_AUDIO_FORMAT = "pcm16"     # 16-bit PCM
DEFAULT_OUTPUT_AUDIO_FORMAT = "pcm16"
DEFAULT_SAMPLE_RATE = 24000              # 24kHz (Azure Realtime requirement)


class AzureRealtimeConfig:
    """Configuration for an Azure OpenAI Realtime session."""

    def __init__(
        self,
        system_prompt: str,
        voice: str = "alloy",
        input_audio_format: str = DEFAULT_INPUT_AUDIO_FORMAT,
        output_audio_format: str = DEFAULT_OUTPUT_AUDIO_FORMAT,
        language: str = "en-US",
        temperature: float = 0.8,
        max_response_tokens: Optional[int] = None,
        turn_detection: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
        input_transcription_model: Optional[str] = "whisper-1",
    ):
        self.system_prompt = system_prompt
        # The caller's words as text, for the transcript and the guards.
        self.input_transcription_model = input_transcription_model
        self.voice = voice
        self.input_audio_format = input_audio_format
        self.output_audio_format = output_audio_format
        self.language = language
        self.temperature = temperature
        self.max_response_tokens = max_response_tokens
        # Default VAD (Voice Activity Detection) config
        self.turn_detection = turn_detection or {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
        }
        self.tools = tools or []

    def to_session_update(self) -> Dict:
        """Build the session.update payload for Azure Realtime API."""
        session: Dict[str, Any] = {
            "modalities": ["text", "audio"],
            "instructions": self.system_prompt,
            "voice": self.voice,
            "input_audio_format": self.input_audio_format,
            "output_audio_format": self.output_audio_format,
            "turn_detection": self.turn_detection,
            "temperature": self.temperature,
        }
        if self.input_transcription_model:
            session["input_audio_transcription"] = {"model": self.input_transcription_model}
        if self.max_response_tokens:
            session["max_response_output_tokens"] = self.max_response_tokens
        if self.tools:
            session["tools"] = self.tools
            session["tool_choice"] = "auto"
        return session


class AzureRealtimeEvent:
    """Represents a single event from the Azure Realtime API."""
    def __init__(self, data: Dict):
        self.event_type: str = data.get("type", "")
        self.raw: Dict = data

    @property
    def is_audio_delta(self) -> bool:
        return self.event_type == "response.audio.delta"

    @property
    def is_text_delta(self) -> bool:
        return self.event_type == "response.text.delta" or self.event_type == "response.audio_transcript.delta"

    @property
    def is_function_call(self) -> bool:
        return self.event_type in (
            "response.function_call_arguments.done",
            "response.output_item.done",
        ) and self.raw.get("item", {}).get("type") == "function_call"

    @property
    def is_turn_done(self) -> bool:
        return self.event_type == "response.done"

    @property
    def is_error(self) -> bool:
        return self.event_type == "error"

    @property
    def audio_delta_bytes(self) -> Optional[bytes]:
        """Decode base64 audio delta."""
        if self.is_audio_delta:
            b64 = self.raw.get("delta", "")
            if b64:
                return base64.b64decode(b64)
        return None

    @property
    def text_delta(self) -> str:
        return self.raw.get("delta", "")

    @property
    def function_call_info(self) -> Optional[Tuple[str, str, Dict]]:
        """Returns (call_id, name, args) for function calls."""
        if self.event_type == "response.function_call_arguments.done":
            item = self.raw
            call_id = item.get("call_id", "")
            name = item.get("name", "")
            args_str = item.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except Exception:
                args = {"raw": args_str}
            return call_id, name, args
        return None


class AzureRealtimeClient:
    """
    Azure OpenAI GPT-4 Realtime WebSocket client.

    Manages a persistent WebSocket connection to the Azure Realtime API
    for bidirectional speech-to-speech streaming.

    Usage:
        client = AzureRealtimeClient(api_key="...", azure_endpoint="...", model="gpt-4o-realtime-preview")
        async with client.connect(config) as session:
            # Send audio
            await session.send_audio(pcm_bytes)
            # Receive events
            async for event in session.receive():
                if event.is_audio_delta:
                    play(event.audio_delta_bytes)
                elif event.is_text_delta:
                    print(event.text_delta)
    """

    def __init__(
        self,
        api_key: str,
        azure_endpoint: str,
        model: str = GPT4_REALTIME_MODEL,
        api_version: str = "2025-04-01-preview",
        service_metadata: Optional[Dict] = None,
    ):
        self.api_key = api_key
        self.azure_endpoint = azure_endpoint.rstrip("/")
        self.model = model
        self.api_version = api_version
        self.service_metadata = service_metadata or {}
        self._ws = None
        self._config: Optional[AzureRealtimeConfig] = None

    def _build_ws_url(self) -> str:
        """Construct the WebSocket URL for Azure Realtime API."""
        # Convert HTTPS endpoint to WSS
        base = self.azure_endpoint.replace("https://", "wss://").replace("http://", "ws://")
        deployment = self.service_metadata.get("deployment_name", self.model)
        return f"{base}/openai/realtime?api-version={self.api_version}&deployment={deployment}"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def connect(self, config: AzureRealtimeConfig) -> "AzureRealtimeSession":
        """
        Establish a WebSocket connection and return a session object.
        The session is used to send audio and receive events.
        """
        try:
            # The asyncio client takes ``additional_headers``; the legacy
            # top-level ``websockets.connect`` of 13.x does not (VT-02).
            from websockets.asyncio.client import connect as ws_connect
        except ImportError:
            raise RuntimeError("websockets>=13 is required for Azure Realtime")

        url = self._build_ws_url()
        headers = self._get_headers()
        logger.info(f"Connecting to Azure Realtime API: {url}")

        ws = await ws_connect(url, additional_headers=headers)
        session = AzureRealtimeSession(ws=ws, config=config, model=self.model)
        await session.initialize()
        return session


class AzureRealtimeSession:
    """
    Active Azure Realtime API session over a WebSocket connection.
    Created by AzureRealtimeClient.connect().
    """

    def __init__(self, ws, config: AzureRealtimeConfig, model: str):
        self._ws = ws
        self._config = config
        self.model = model
        self._session_id: Optional[str] = None
        self._closed = False
        self._transcript_buffer = ""
        self._audio_buffer = bytearray()

    async def initialize(self):
        """Send session.update to configure the session."""
        await self._ws.send(json.dumps({
            "type": "session.update",
            "session": self._config.to_session_update(),
        }))
        logger.info("Azure Realtime session initialized")

    async def send_audio(self, pcm_bytes: bytes):
        """
        Send raw PCM audio bytes to the API.
        Encodes to base64 and sends as input_audio_buffer.append event.
        """
        if self._closed:
            return
        b64 = base64.b64encode(pcm_bytes).decode("utf-8")
        await self._ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": b64,
        }))

    async def send_text(self, text: str):
        """Send a text message to trigger a text-modality response."""
        if self._closed:
            return
        await self._ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        }))
        await self._create_response()

    async def commit_audio(self):
        """Signal end of audio input (manual turn detection mode)."""
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await self._create_response()

    async def send_function_result(self, call_id: str, result: str):
        """Send a function call result back to the model."""
        await self.send_function_results([(call_id, result)])

    async def send_function_results(self, results: List[Tuple[str, str]]):
        """Send several results, then ask for one response to all of them."""
        for call_id, result in results:
            await self._ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result,
                }
            }))
        await self._create_response()

    async def _create_response(self):
        """Trigger the model to generate a response."""
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def receive(self) -> AsyncGenerator[AzureRealtimeEvent, None]:
        """
        Async generator that yields AzureRealtimeEvents as they arrive.
        The caller should handle each event type appropriately.
        """
        try:
            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)
                    event = AzureRealtimeEvent(data)

                    if event.is_error:
                        logger.error(f"Azure Realtime API error: {data}")

                    yield event

                    if event.is_turn_done:
                        logger.debug("Azure Realtime: response.done received")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse Azure Realtime message: {e}")
        except Exception as e:
            if not self._closed:
                logger.error(f"Azure Realtime WebSocket error: {e}")
            return

    async def close(self):
        """Close the WebSocket connection."""
        if not self._closed:
            self._closed = True
            try:
                await self._ws.close()
            except Exception:
                pass
            logger.info("Azure Realtime session closed")


# ---------------------------------------------------------------------------
# Factory function — integrates with LLM Router via task defaults
# ---------------------------------------------------------------------------

async def create_azure_realtime_client(
    company_id,
    db,
    config: Optional[AzureRealtimeConfig] = None,
) -> Tuple[AzureRealtimeClient, AzureRealtimeConfig]:
    """
    Resolve the speech_to_speech model from task defaults and return a
    configured AzureRealtimeClient + AzureRealtimeConfig.

    Use this in websocket_handler when the configured speech_to_speech
    model is Azure OpenAI (GPT-4 Realtime).

    Raises RuntimeError if the configured provider is not azure_openai.
    """
    from src.config.service import ConfigService
    config_svc = ConfigService(db)
    integration, api_key = await config_svc.resolve_model_for_task(
        company_id=company_id,
        task_type="speech_to_speech",
    )
    if not integration:
        raise RuntimeError("No speech_to_speech model configured in task defaults")
    if integration.provider_name.lower() not in ("azure_openai", "azure"):
        raise RuntimeError(
            f"Azure Realtime adapter requires provider 'azure_openai', "
            f"got '{integration.provider_name}'. Use the Gemini Live adapter instead."
        )

    meta = integration.service_metadata or {}
    azure_endpoint = meta.get("azure_endpoint", "")
    if not azure_endpoint:
        raise ValueError("service_metadata.azure_endpoint is required for Azure Realtime")

    realtime_client = AzureRealtimeClient(
        api_key=api_key or "",
        azure_endpoint=azure_endpoint,
        model=integration.model_name or GPT4_REALTIME_MODEL,
        api_version=meta.get("api_version", "2025-04-01-preview"),
        service_metadata=meta,
    )
    return realtime_client, config or AzureRealtimeConfig(system_prompt="")


# ---------------------------------------------------------------------------
# The Gemini Live session shape (VT-02)
# ---------------------------------------------------------------------------
# The stream handler and the browser adapter drive a live model through the
# google-genai Live session: ``send_realtime_input(audio=Blob | text=...)``,
# ``receive()`` yielding server messages (``data``, ``server_content``,
# ``tool_call``, ``usage_metadata``) and ``send_tool_response()``. The factory
# hands them an :class:`AzureLiveClient`, whose ``connect(tools=...)`` enters
# like ``client.aio.live.connect`` and yields an :class:`AzureLiveSession`
# speaking that shape, so a call runs the same code on either provider.
# Azure Realtime takes and returns PCM16 at 24 kHz; the 16 kHz audio the
# callers send is resampled on the way in, and its 24 kHz output is what they
# already expect from Gemini.

_RATE = re.compile(r"rate=(\d+)")
_AUDIO_DELTA = ("response.audio.delta", "response.output_audio.delta")
_AGENT_TRANSCRIPT = ("response.audio_transcript.done", "response.output_audio_transcript.done")


def _message(**fields: Any) -> SimpleNamespace:
    """One server message, shaped like google-genai's ``LiveServerMessage``."""
    base: Dict[str, Any] = {"data": None, "text": None, "server_content": None,
                            "tool_call": None, "usage_metadata": None, "voice_activity": None}
    base.update(fields)
    return SimpleNamespace(**base)


def _content(**fields: Any) -> SimpleNamespace:
    base: Dict[str, Any] = {"interrupted": False, "turn_complete": False,
                            "input_transcription": None, "output_transcription": None}
    base.update(fields)
    return SimpleNamespace(**base)


def _usage(usage: Optional[Dict[str, Any]]) -> Optional[SimpleNamespace]:
    """A ``response.done`` usage block as Gemini's ``usage_metadata`` (VT-05 bills it)."""
    if not usage:
        return None

    def details(block: Optional[Dict[str, Any]]) -> List[SimpleNamespace]:
        return [SimpleNamespace(modality=modality.upper(), token_count=int((block or {}).get(f"{modality}_tokens") or 0))
                for modality in ("text", "audio") if (block or {}).get(f"{modality}_tokens")]

    return SimpleNamespace(
        prompt_token_count=int(usage.get("input_tokens") or 0),
        response_token_count=int(usage.get("output_tokens") or 0),
        prompt_tokens_details=details(usage.get("input_token_details")),
        response_tokens_details=details(usage.get("output_token_details")),
    )


def _blob(audio: Any) -> Tuple[bytes, str]:
    if isinstance(audio, dict):
        return audio.get("data") or b"", str(audio.get("mime_type") or "")
    return getattr(audio, "data", None) or b"", str(getattr(audio, "mime_type", "") or "")


def to_azure_tools(declarations: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Gemini function declarations (``name``, ``description``, JSON-schema
    ``parameters``) as Azure Realtime function tools."""
    return [
        {"type": "function", "name": d["name"], "description": d.get("description", ""),
         "parameters": d.get("parameters") or {"type": "object", "properties": {}}}
        for d in declarations or [] if isinstance(d, dict) and d.get("name")
    ]


class AzureLiveSession:
    """An :class:`AzureRealtimeSession` with the Gemini Live session's methods."""

    def __init__(self, session: "AzureRealtimeSession"):
        self._session = session
        self._resample_state: Any = None
        self._responding = False

    async def send_realtime_input(self, *, audio: Any = None, text: Optional[str] = None) -> None:
        if audio is not None:
            data, mime = _blob(audio)
            match = _RATE.search(mime)
            rate = int(match.group(1)) if match else 16000
            if data and rate != DEFAULT_SAMPLE_RATE:
                data, self._resample_state = audioop.ratecv(
                    data, 2, 1, rate, DEFAULT_SAMPLE_RATE, self._resample_state)
            if data:
                await self._session.send_audio(data)
        if text:
            await self._session.send_text(text)

    async def send_tool_response(self, *, function_responses: List[Any]) -> None:
        outputs = []
        for response in function_responses:
            get = response.get if isinstance(response, dict) else (lambda k, r=response: getattr(r, k, None))
            outputs.append((str(get("id") or ""), json.dumps(get("response") or {}, default=str)))
        await self._session.send_function_results(outputs)

    def translate(self, event: AzureRealtimeEvent) -> Optional[SimpleNamespace]:
        """One Azure event as a Gemini-shaped message, or None for one the callers ignore."""
        kind, raw = event.event_type, event.raw
        if kind == "response.created":
            self._responding = True
        elif kind in _AUDIO_DELTA:
            data = base64.b64decode(raw.get("delta") or "")
            return _message(data=data) if data else None
        elif kind in _AGENT_TRANSCRIPT:
            text = raw.get("transcript") or ""
            return _message(server_content=_content(output_transcription=SimpleNamespace(text=text))) if text else None
        elif kind == "conversation.item.input_audio_transcription.completed":
            text = raw.get("transcript") or ""
            return _message(server_content=_content(input_transcription=SimpleNamespace(text=text))) if text else None
        elif kind == "input_audio_buffer.speech_started":
            # Server VAD cuts the model off when the caller talks over it: that
            # is Gemini's ``interrupted``. Speech into silence interrupts nothing.
            interrupted, self._responding = self._responding, False
            return _message(server_content=_content(interrupted=interrupted) if interrupted else None,
                            voice_activity=SimpleNamespace(voice_activity_type="ACTIVITY_START"))
        elif kind == "input_audio_buffer.speech_stopped":
            return _message(voice_activity=SimpleNamespace(voice_activity_type="ACTIVITY_END"))
        elif kind == "response.function_call_arguments.done":
            info = event.function_call_info
            if info:
                call_id, name, args = info
                return _message(tool_call=SimpleNamespace(
                    function_calls=[SimpleNamespace(id=call_id, name=name, args=args)]))
        elif kind == "response.done":
            self._responding = False
            body = raw.get("response") or {}
            return _message(server_content=_content(turn_complete=True),
                            usage_metadata=_usage(body.get("usage")))
        return None

    async def receive(self) -> AsyncGenerator[SimpleNamespace, None]:
        async for event in self._session.receive():
            message = self.translate(event)
            if message is not None:
                yield message
        # The socket closed. Gemini's receive() raises here; ending quietly
        # would have the callers' ``while running: async for ...`` spin.
        raise ConnectionError("Azure Realtime connection closed")

    async def close(self) -> None:
        await self._session.close()


class _AzureLiveConnection:
    """What :meth:`AzureLiveClient.connect` returns: entered, it is the session."""

    def __init__(self, client: AzureRealtimeClient, config: AzureRealtimeConfig):
        self._client = client
        self._config = config
        self._session: Optional[AzureRealtimeSession] = None

    async def __aenter__(self) -> AzureLiveSession:
        self._session = await self._client.connect(self._config)
        return AzureLiveSession(self._session)

    async def __aexit__(self, *exc: Any) -> None:
        if self._session is not None:
            await self._session.close()


class AzureLiveClient:
    """The Azure branch of ``LiveClientFactory``: connects like ``GeminiLiveClient``."""

    def __init__(self, client: AzureRealtimeClient, config: AzureRealtimeConfig):
        self.client = client
        self.config = config

    async def connect(self, model: Optional[str] = None,
                      tools: Optional[List[Dict[str, Any]]] = None) -> _AzureLiveConnection:
        config = copy.copy(self.config)
        config.tools = to_azure_tools(tools)
        return _AzureLiveConnection(self.client, config)
