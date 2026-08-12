"""
Gemini Text Generation Service for WhatsApp and other text-based channels.
(Vertex AI only — no direct AI Studio calls)

Provides:
- Text-only generation (no audio) using Gemini models via Vertex AI
- Conversation history management
- Context-aware responses
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiTextService:
    """
    Gemini text generation service for non-voice channels (Vertex AI only).
    
    Uses the standard Gemini API via Vertex AI for text-only interactions.
    """
    
    # Default model for text generation
    DEFAULT_MODEL = "gemini-2.0-flash"
    
    def __init__(
        self,
        service_metadata: Dict[str, Any],
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024
    ):
        """
        Initialize Gemini text service via Vertex AI.
        
        Args:
            service_metadata: Dict with project_id and region from IntegrationRegistry
            model: Model name to use
            system_instruction: System prompt for the model
            temperature: Generation temperature
            max_tokens: Maximum output tokens
        """
        if not service_metadata or not service_metadata.get("project_id"):
            raise ValueError(
                "service_metadata with project_id is required. "
                "All Google models must be accessed via Vertex AI."
            )
        
        self.service_metadata = service_metadata
        self.model = model or self.DEFAULT_MODEL
        self.system_instruction = system_instruction or "You are a helpful AI assistant."
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Initialize Vertex AI client
        from src.common.genai_factory import build_vertex_genai_client_sync
        self.client = build_vertex_genai_client_sync(
            self.service_metadata,
            http_options={'api_version': 'v1beta'}
        )
        
        logger.info(f"Initialized GeminiTextService via Vertex AI with model {self.model}")
    
    async def generate_response(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a text response using Gemini via Vertex AI.
        
        Args:
            message: Current user message
            conversation_history: Previous conversation turns in Gemini format
            context: Additional context to include
            
        Returns:
            Dict with 'response', 'prompt_tokens', 'completion_tokens', 'latency_ms'
        """
        start_time = datetime.utcnow()
        
        try:
            # Build system instruction with context
            full_system = self.system_instruction
            if context:
                full_system += f"\n\n## Additional Context\n{context}"
            
            # Build contents
            contents = []
            
            # Add conversation history
            if conversation_history:
                for turn in conversation_history:
                    role = turn.get("role", "user")
                    parts = turn.get("parts", [])
                    text = parts[0].get("text", "") if parts else ""
                    if text:
                        contents.append(types.Content(
                            role=role,
                            parts=[types.Part.from_text(text=text)]
                        ))
            
            # Add current message
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)]
            ))
            
            # Configure generation
            config = types.GenerateContentConfig(
                system_instruction=full_system,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens
            )
            
            # Generate response
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config
            )
            
            latency_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # Extract response text
            response_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text += part.text
            
            # Fallback to .text property
            if not response_text and response.text:
                response_text = response.text
            
            # Extract usage
            usage = response.usage_metadata
            prompt_tokens = usage.prompt_token_count if usage else 0
            completion_tokens = usage.candidates_token_count if usage else 0
            
            logger.info(
                f"Generated response in {latency_ms}ms "
                f"(prompt: {prompt_tokens}, completion: {completion_tokens})"
            )
            
            return {
                "response": response_text,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms
            }
            
        except Exception as e:
            logger.error(f"Error generating response: {e}", exc_info=True)
            raise


class GeminiTextServiceFactory:
    """Factory for creating GeminiTextService instances with caching."""
    
    _instances: Dict[str, GeminiTextService] = {}
    
    @classmethod
    def get_service(
        cls,
        service_metadata: Dict[str, Any],
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        **kwargs
    ) -> GeminiTextService:
        """
        Get or create a GeminiTextService instance (Vertex AI only).
        
        Uses caching based on project_id and model to avoid creating
        multiple clients for the same configuration.
        """
        project_id = service_metadata.get("project_id", "default")
        cache_key = f"{project_id}:{model or 'default'}"
        
        if cache_key not in cls._instances:
            cls._instances[cache_key] = GeminiTextService(
                service_metadata=service_metadata,
                model=model,
                system_instruction=system_instruction,
                **kwargs
            )
        
        return cls._instances[cache_key]

    @classmethod
    async def from_company(
        cls,
        db,
        company_id,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        **kwargs
    ) -> GeminiTextService:
        """
        Create a GeminiTextService by resolving the Google integration
        for the given company from IntegrationRegistry.
        """
        from src.config.service import ConfigService
        config_svc = ConfigService(db)
        integration = await config_svc.get_integration_by_provider(company_id, "google")
        if not integration:
            integration = await config_svc.get_integration_by_provider(company_id, "gemini")
        if not integration:
            raise RuntimeError("No Google/Gemini integration configured for this company.")
        meta = integration.service_metadata or {}
        return cls.get_service(
            service_metadata=meta,
            model=model,
            system_instruction=system_instruction,
            **kwargs
        )
    
    @classmethod
    def clear_cache(cls):
        """Clear the service cache."""
        cls._instances.clear()

