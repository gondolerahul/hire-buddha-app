"""
ai.llm — LLM provider adapters and routing layer.

Provides a provider-agnostic interface for calling LLMs (Gemini, Anthropic,
Azure OpenAI) with automatic routing based on task type configuration.

Key classes:
  - LLMRouter: Main entry point for LLM calls
  - LLMResponse: Unified response dataclass
  - BaseLLMAdapter: Abstract base for provider adapters

Extracted from the monolithic llm_router.py during Phase 10B restructuring.
"""
from src.ai.llm.types import LLMResponse
from src.ai.llm.base import BaseLLMAdapter
from src.ai.llm.router import LLMRouter

__all__ = [
    "LLMRouter",
    "LLMResponse",
    "BaseLLMAdapter",
]
