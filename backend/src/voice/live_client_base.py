import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, List

# Basic dataclass for tool/function definitions sent to the live client
class LiveToolDeclaration:
    def __init__(self, name: str, description: str, parameters: Dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters


class BaseLiveClient(ABC):
    """
    Abstract base class for all real-time voice streaming clients.
    Implementations handle provider-specific WebSocket protocols (e.g. Gemini BIDI, OpenAI Realtime).
    """

    def __init__(
        self, 
        api_key: str, 
        model_name: str, 
        on_audio_out: Optional[Callable[[bytes], None]] = None,
        on_text_out: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_turn_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        voice_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ):
        self.api_key = api_key
        self.model_name = model_name
        
        # Callbacks to pass data back to the FastAPI websocket handler
        self.on_audio_out = on_audio_out
        self.on_text_out = on_text_out
        self.on_tool_call = on_tool_call
        self.on_turn_complete = on_turn_complete
        self.on_error = on_error
        
        # Configuration
        self.voice_config = voice_config or {}
        self.system_prompt = system_prompt or "You are a helpful AI."
        self.tools = tools or []
        
        # Connection state
        self._connected = False

    @abstractmethod
    async def connect(self):
        """Establish the WebSocket connection to the LLM provider."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Close the WebSocket connection."""
        pass

    @abstractmethod
    async def send_audio(self, pcm_data: bytes):
        """Send a chunk of raw PCM 16-bit 16kHz audio to the model."""
        pass

    @abstractmethod
    async def send_text(self, text: str):
        """Send a text utterance to the model."""
        pass
        
    @abstractmethod
    async def send_tool_response(self, function_responses: list):
        """Send the results of tool calls back to the model."""
        pass
