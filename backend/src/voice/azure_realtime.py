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
import base64
import json
import logging
import time
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
    ):
        self.system_prompt = system_prompt
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
            import websockets
        except ImportError:
            raise RuntimeError("websockets package not installed. Run: pip install websockets>=12.0")

        url = self._build_ws_url()
        headers = self._get_headers()
        logger.info(f"Connecting to Azure Realtime API: {url}")

        ws = await websockets.connect(url, additional_headers=headers)
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
