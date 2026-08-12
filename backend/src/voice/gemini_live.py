"""
Real Gemini Live API Client for production use.

Integrates with google.genai SDK for real-time bidirectional audio
streaming. Supports two backends:
  - Vertex AI (default) — for standard models
  - AI Studio / Gemini Developer API — for Live/Native Audio models
    not yet available on Vertex AI (uses ADC, no API key)
"""
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Try to import google-genai SDK
try:
    import google.genai as genai
    GENAI_AVAILABLE = True
    logger.info("google.genai SDK available")
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google.genai SDK not installed - will fall back to mock")


class GeminiLiveClient:
    """
    Real Gemini Live API client for production streaming.

    Supports two backends:
      - Vertex AI (default) — uses project_id + region from service_metadata
      - AI Studio (use_ai_studio=True) — uses ADC, no API key needed

    Supports Gemini 2.0 Flash, Gemini 2.5 Flash Native Audio, and
    Gemini 3.1 Flash Live models.
    Voice name, speaking rate, and pitch are sourced from VoiceConfig
    (typically loaded from the agent's AgentPersona by AgentContextLoader).
    """

    # P2.3 — Model capability registry
    MODEL_CAPABILITIES = {
        "gemini-2.0-flash-exp": {
            "native_audio": False,
            "supports_thinking": False,
        },
        "gemini-2.5-flash-preview-native-audio-01": {
            "native_audio": True,
            "supports_thinking": False,  # DO NOT set thinking_config — causes 60-90s silence
        },
        "gemini-2.5-flash-live-001": {
            "native_audio": True,
            "supports_thinking": False,
        },
        # AI Studio-only models (not available on Vertex AI)
        "gemini-3.1-flash-live-preview": {
            "native_audio": True,
            "supports_thinking": True,
        },
        "gemini-2.5-flash-native-audio-preview-12-2025": {
            "native_audio": True,
            "supports_thinking": True,
        },
    }

    def __init__(
        self,
        system_instruction: str,
        service_metadata: Dict[str, Any],
        generation_config: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        voice_config: Optional[Any] = None,   # VoiceConfig or dict
        model_name: Optional[str] = None,     # Resolved dynamically from task defaults
        use_ai_studio: bool = False,          # Use AI Studio (Gemini Developer API) instead of Vertex AI
        api_key: Optional[str] = None,        # API key for AI Studio mode
    ):
        self.system_instruction = system_instruction
        self.service_metadata = service_metadata
        self.generation_config = generation_config or {}
        self.conversation_history = conversation_history or []
        self.use_ai_studio = use_ai_studio
        # model_name resolved externally by LiveClientFactory; stored for connect()
        self._resolved_model = model_name

        # Resolve VoiceConfig — accept both VoiceConfig objects and plain dicts
        self._voice_name = "Aoede"
        self._language_code = "en-US"
        self._speaking_rate = 1.0
        self._pitch = 0.0
        if voice_config:
            if hasattr(voice_config, "voice_name"):
                self._voice_name = voice_config.voice_name
                self._language_code = voice_config.language_code
                self._speaking_rate = voice_config.speaking_rate
                self._pitch = voice_config.pitch
            elif isinstance(voice_config, dict):
                self._voice_name = voice_config.get("voice_name", "Aoede")
                self._language_code = voice_config.get("language_code", "en-US")
                self._speaking_rate = voice_config.get("speaking_rate", 1.0)
                self._pitch = voice_config.get("pitch", 0.0)

        if not GENAI_AVAILABLE:
            raise RuntimeError("google.genai SDK not available. Install with: pip install google-genai")

        if self.use_ai_studio:
            from src.common.genai_factory import build_ai_studio_genai_client_sync
            self.client = build_ai_studio_genai_client_sync(api_key=api_key)
            logger.info(
                f"Gemini Live client initialized via AI Studio/ADC "
                f"(voice={self._voice_name}, model={self._resolved_model})"
            )
        else:
            from src.common.genai_factory import build_vertex_genai_client_sync
            self.client = build_vertex_genai_client_sync(self.service_metadata)
            logger.info(
                f"Gemini Live client initialized via Vertex AI "
                f"(voice={self._voice_name}, model={self._resolved_model})"
            )

    def _is_native_audio(self, model: str) -> bool:
        return self.MODEL_CAPABILITIES.get(model, {}).get("native_audio", False)

    def create_session_config(
        self,
        model: str = "gemini-2.0-flash-exp",
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Create Gemini Live session configuration.

        For Gemini 2.5 Flash Native Audio models, the config is enhanced with:
          - VAD (voice activity detection) settings
          - Proactivity (agent can initiate turn after silence)
          - audio_speech_config for prosody control

        For Gemini 2.0 Flash Exp, returns the standard 2.0 config.

        IMPORTANT: response_modalities and speech_config MUST live inside
        generation_config — placing them at top-level causes silent ignoring.
        """
        if self._is_native_audio(model):
            return self._create_native_audio_config(tools=tools)
        return self._create_standard_config(tools=tools)

    def _create_standard_config(self, tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Gemini 2.0 Flash standard config — SDK v1.71.0 top-level fields."""
        config: Dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": self._voice_name}
                }
            },
            # Phase 1: VAD tuning — HIGH start sensitivity for fast barge-in,
            # LOW end sensitivity to avoid cutting off during natural pauses.
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,
                    "start_of_speech_sensitivity": "START_SENSITIVITY_HIGH",
                    "end_of_speech_sensitivity": "END_SENSITIVITY_LOW",
                    "prefix_padding_ms": 100,
                    "silence_duration_ms": 1000,
                }
            },
            "output_audio_transcription": {},
            "input_audio_transcription": {},
        }
        if self.system_instruction:
            config["system_instruction"] = self.system_instruction
        # Phase 3: Tool declarations for function calling
        if tools:
            config["tools"] = [{"function_declarations": tools}]
            logger.info(f"Registered {len(tools)} tool(s) in Gemini Live session config")
        return config

    def _create_native_audio_config(self, tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Gemini 2.5+ / 3.1 Flash Native Audio config.

        SDK v1.71.0 LiveConnectConfig accepts response_modalities,
        speech_config, system_instruction etc. at the top level.
        """
        config: Dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": self._voice_name}
                }
            },
            # Phase 1: VAD tuning — HIGH start sensitivity for fast barge-in,
            # LOW end sensitivity to avoid cutting off during natural pauses.
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,
                    "start_of_speech_sensitivity": "START_SENSITIVITY_HIGH",
                    "end_of_speech_sensitivity": "END_SENSITIVITY_LOW",
                    "prefix_padding_ms": 100,
                    "silence_duration_ms": 1000,
                }
            },
            "output_audio_transcription": {},
            "input_audio_transcription": {},
        }
        if self.system_instruction:
            config["system_instruction"] = self.system_instruction
        # Phase 3: Tool declarations for function calling
        if tools:
            config["tools"] = [{"function_declarations": tools}]
            logger.info(f"Registered {len(tools)} tool(s) in native audio session config")
        return config

    async def connect(self, model: Optional[str] = None, tools: Optional[List[Dict]] = None):
        """
        Create a live session context manager.
        Uses self._resolved_model if model not explicitly passed.
        Auto-selects the appropriate session config for the model.
        Optionally includes tool declarations for function calling.
        """
        target_model = model or self._resolved_model
        if not target_model:
            raise RuntimeError(
                "No model resolved for GeminiLiveClient. "
                "The speech_to_speech task default must be configured."
            )
        config = self.create_session_config(model=target_model, tools=tools)
        return self.client.aio.live.connect(model=target_model, config=config)


class GeminiLiveSession:
    """
    Wrapper for Gemini Live session with helper methods.
    
    Provides a cleaner interface for sending/receiving audio.
    """
    
    def __init__(self, session):
        """
        Initialize session wrapper.
        
        Args:
            session: Underlying Gemini Live session from client.aio.live.connect()
        """
        self.session = session
        self.is_active = True
    
    async def send_audio(self, audio_data: bytes, mime_type: str = "audio/pcm"):
        """
        Send audio chunk to Gemini.
        
        Args:
            audio_data: PCM16 audio bytes (16kHz, 16-bit, mono)
            mime_type: MIME type (default: audio/pcm)
        """
        if not self.is_active:
            logger.warning("Attempted to send audio to inactive session")
            return
        
        try:
            await self.session.send({
                "data": audio_data,
                "mime_type": mime_type
            })
        except Exception as e:
            logger.error(f"Error sending audio to Gemini: {e}")
            raise
    
    async def send_text(self, text: str):
        """
        Send text message to Gemini.
        
        Args:
            text: Text message
        """
        if not self.is_active:
            logger.warning("Attempted to send text to inactive session")
            return
        
        try:
            await self.session.send(text)
        except Exception as e:
            logger.error(f"Error sending text to Gemini: {e}")
            raise
    
    async def receive(self):
        """
        Receive responses from Gemini.
        
        Yields:
            Response objects with audio and/or text
        """
        try:
            async for response in self.session.receive():
                yield response
        except Exception as e:
            logger.error(f"Error receiving from Gemini: {e}")
            self.is_active = False
            raise
    
    async def close(self):
        """Close the session."""
        self.is_active = False
        # Session cleanup handled by context manager


def get_gemini_client(
    service_metadata: Dict[str, Any],
    system_instruction: str = "",
    generation_config: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    model_name: Optional[str] = None,
    use_ai_studio: bool = False,
) -> GeminiLiveClient:
    """
    Create a GeminiLiveClient.

    Supports two backends:
      - Vertex AI (default): requires service_metadata with project_id
      - AI Studio (use_ai_studio=True): uses ADC, no API key or project_id needed

    Args:
        service_metadata: Dict with project_id and region from IntegrationRegistry
        system_instruction: System instruction
        generation_config: Generation parameters
        conversation_history: Conversation history for context
        model_name: Model name resolved from task defaults
        use_ai_studio: If True, use AI Studio (Gemini Developer API) via ADC

    Returns:
        GeminiLiveClient instance

    Raises:
        ValueError: If Vertex AI mode and service_metadata missing project_id
        RuntimeError: If google.genai SDK not available
    """
    if not use_ai_studio:
        if not service_metadata or not service_metadata.get("project_id"):
            raise ValueError(
                "service_metadata with project_id is required for Vertex AI mode. "
                "Set use_ai_studio=True for AI Studio mode or configure project_id."
            )

    return GeminiLiveClient(
        service_metadata=service_metadata or {},
        system_instruction=system_instruction,
        generation_config=generation_config,
        conversation_history=conversation_history,
        model_name=model_name,
        use_ai_studio=use_ai_studio,
    )

