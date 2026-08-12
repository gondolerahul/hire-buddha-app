"""
Mock Gemini Live API client for testing without API key.

Simulates the Gemini Live API WebSocket protocol with pre-recorded responses.
Replace with real implementation in Phase 3.
"""
import logging
import asyncio
from typing import Dict, Any, Optional, Union
import random

logger = logging.getLogger(__name__)


class MockGeminiLiveClient:
    """
    Mock client that simulates Gemini Live API behavior.
    
    Returns pre-programmed responses to test the streaming pipeline
    without requiring a real Gemini API key.
    """
    
    # Pre-recorded response templates
    RESPONSES = [
        "Hello! I'm here to help you. How can I assist you today?",
        "I understand. Let me help you with that.",
        "Thank you for sharing that information. I'll process this for you.",
        "Is there anything else I can help you with?",
        "I appreciate your patience. Let me check on that for you.",
        "Certainly! I'll take care of that right away."
    ]
    
    def __init__(self, system_instruction: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize mock client.
        
        Args:
            system_instruction: System instruction (ignored in mock)
            config: Configuration dict (ignored in mock)
        """
        self.system_instruction = system_instruction
        self.config = config or {}
        self.is_connected = False
        self.response_queue = asyncio.Queue()
        logger.info("MockGeminiLiveClient initialized")
    
    async def connect(self):
        """Simulate connection to Gemini Live API."""
        await asyncio.sleep(0.1)  # Simulate connection delay
        self.is_connected = True
        logger.info("Mock Gemini connection established")
    
    async def disconnect(self):
        """Simulate disconnection."""
        self.is_connected = False
        logger.info("Mock Gemini disconnected")
    
    async def send_audio(self, audio_chunk: Dict[str, Any]):
        """
        Simulate sending audio to Gemini.
        
        Args:
            audio_chunk: Dict with 'data' and 'mime_type'
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Gemini")
        
        # Simulate processing delay
        await asyncio.sleep(0.05)
        
        # Log received audio size
        audio_size = len(audio_chunk.get("data", b""))
        logger.debug(f"Mock Gemini received audio: {audio_size} bytes")
        
        # Randomly trigger a response (every ~5 chunks)
        if random.random() < 0.02:  # 2% chance per chunk
            response_text = random.choice(self.RESPONSES)
            await self._queue_response(response_text)
    
    async def _queue_response(self, text: str):
        """Queue a mock response."""
        # Convert text to mock audio (just repeat the text as bytes for now)
        # In real implementation, this would be actual PCM24 audio
        mock_audio = text.encode('utf-8') * 10  # Simulate audio data
        
        response = {
            "type": "response",
            "text": text,
            "audio": mock_audio,
            "mime_type": "audio/pcm"
        }
        
        await self.response_queue.put(response)
        logger.info(f"Mock Gemini response queued: '{text[:50]}...'")
    
    async def receive(self):
        """
        Receive responses from mock Gemini.
        
        Yields:
            Response dictionaries with 'text' and 'audio'
        """
        while self.is_connected:
            try:
                # Wait for response with timeout
                response = await asyncio.wait_for(
                    self.response_queue.get(),
                    timeout=1.0
                )
                yield response
            except asyncio.TimeoutError:
                # No response available, continue listening
                continue
            except Exception as e:
                logger.error(f"Error receiving from mock Gemini: {e}")
                break
    
    async def send_text(self, text: str):
        """
        Send text message to mock Gemini (for testing).
        
        Args:
            text: Text message
        """
        logger.debug(f"Mock Gemini received text: '{text}'")
        
        # Generate automatic response
        response_text = random.choice(self.RESPONSES)
        await self._queue_response(response_text)


class MockGeminiLiveSession:
    """
    Mock session context manager to match real Gemini Live API interface.
    
    Usage:
        async with client.aio.live.connect(model=..., config=...) as session:
            await session.send_realtime_input(audio=...)
            async for response in session.receive():
                # Process response
    """
    
    def __init__(self, model: str, config: Dict[str, Any]):
        """
        Initialize mock session.
        
        Args:
            model: Model name (ignored in mock)
            config: Configuration dict
        """
        self.model = model
        self.config = config
        self.client = MockGeminiLiveClient(
            system_instruction=config.get("system_instruction", ""),
            config=config
        )
    
    async def __aenter__(self):
        """Enter context manager."""
        await self.client.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        await self.client.disconnect()
    
    async def send(self, *, input: Any = None, end_of_turn: bool = False):
        """
        Send input to mock Gemini (matches real Gemini Live API).
        
        Args:
            input: Content to send (text string or audio dict or list of parts)
            end_of_turn: Whether this is the end of the turn
        """
        input_content = input
        
        if isinstance(input_content, str):
            await self.client.send_text(input_content)
        elif isinstance(input_content, dict) and "data" in input_content:
            await self.client.send_audio(input_content)
        elif isinstance(input_content, dict) and "text" in input_content:
            await self.client.send_text(input_content["text"])
        else:
            logger.warning(f"Mock session received unknown input type: {type(input_content)}")
    
    async def receive(self):
        """
        Receive responses (matches real Gemini Live API).
        
        Yields:
            Mock response objects
        """
        async for response in self.client.receive():
            # Wrap response to match real API structure
            yield MockResponse(response)


class MockResponse:
    """Mock response object to match real Gemini API response structure."""
    
    def __init__(self, response_data: Dict[str, Any]):
        """
        Initialize mock response.
        
        Args:
            response_data: Response data from mock client
        """
        self.server_content = MockServerContent(response_data)


class MockServerContent:
    """Mock server content structure."""
    
    def __init__(self, response_data: Dict[str, Any]):
        """
        Initialize mock server content.
        
        Args:
            response_data: Response data from mock client
        """
        self.model_turn = MockModelTurn(response_data)


class MockModelTurn:
    """Mock model turn structure."""
    
    def __init__(self, response_data: Dict[str, Any]):
        """
        Initialize mock model turn.
        
        Args:
            response_data: Response data from mock client
        """
        self.parts = [MockPart(response_data)]


class MockPart:
    """Mock part structure containing text and/or audio."""
    
    def __init__(self, response_data: Dict[str, Any]):
        """
        Initialize mock part.
        
        Args:
            response_data: Response data from mock client
        """
        self.text = response_data.get("text")
        self.inline_data = MockInlineData(response_data.get("audio"))


class MockInlineData:
    """Mock inline data for audio."""
    
    def __init__(self, audio_data: Optional[bytes]):
        """
        Initialize mock inline data.
        
        Args:
            audio_data: Audio bytes
        """
        self.data = audio_data


class MockGeminiClient:
    """
    Mock Gemini client to match real google.genai.Client interface.
    
    Usage:
        client = MockGeminiClient(api_key="mock")
        async with client.aio.live.connect(model="...", config={...}) as session:
            ...
    """
    
    def __init__(self, api_key: str):
        """
        Initialize mock client.
        
        Args:
            api_key: API key (ignored in mock)
        """
        self.api_key = api_key
        self.aio = MockAsyncClient()
        logger.info("MockGeminiClient created (using mock responses)")
    
    async def connect(self, model: str = "gemini-2.0-flash-exp"):
        """
        Create a mock live session context manager.
        Matches GeminiLiveClient.connect interface.
        """
        return self.aio.live.connect(model=model, config={})


class MockAsyncClient:
    """Mock async client wrapper."""
    
    def __init__(self):
        self.live = MockLiveAPI()


class MockLiveAPI:
    """Mock Live API wrapper."""
    
    def connect(self, model: str, config: Dict[str, Any]):
        """
        Create a mock live session.
        
        Args:
            model: Model name
            config: Configuration dict
            
        Returns:
            MockGeminiLiveSession context manager
        """
        return MockGeminiLiveSession(model, config)
