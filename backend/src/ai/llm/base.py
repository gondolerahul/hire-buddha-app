"""
ai.llm.base — Abstract base class for LLM provider adapters.

All provider-specific adapters (Gemini, Anthropic, Azure OpenAI) inherit
from BaseLLMAdapter and implement generate() and generate_with_tools_react().

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.ai.llm.types import LLMResponse


class BaseLLMAdapter(ABC):
    """Base class for all LLM provider adapters."""

    def __init__(self, api_key: str, model_name: str, service_metadata: Dict[str, Any]):
        self.api_key = api_key
        self.model_name = model_name
        self.service_metadata = service_metadata or {}

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        """Single-turn generation."""
        ...

    @abstractmethod
    async def generate_with_tools_react(
        self,
        system_prompt: str,
        initial_messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
        execute_tool_fn,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_react_turns: int = 10,
        **kwargs,
    ) -> LLMResponse:
        """
        Full REACT loop: calls generate, executes tool calls, continues until
        no more tool calls or max turns reached.
        execute_tool_fn: async callable(function_calls: list) -> list of tool results
        """
        ...

    def get_tool_declarations(self, tool_schemas: List[Dict]) -> Any:
        """Convert generic JSON Schema tool defs to provider-specific format."""
        return tool_schemas  # Default: pass through as-is
