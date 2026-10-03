"""
ai.llm.base — Abstract base class for LLM provider adapters.

All provider-specific adapters (Gemini, Anthropic, Azure OpenAI) inherit
from BaseLLMAdapter and implement generate() and generate_with_tools_react().

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from src.ai.llm.types import LLMResponse


def call_id(provider_id: Optional[str], turn: int, index: int) -> str:
    """A tool call's id: the provider's, else one made for the turn (LP-17)."""
    return provider_id or f"call_{turn}_{index}"


def pair_tool_results(function_calls: List[Dict[str, Any]],
                      results: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Each tool result with the call it answers, by position.

    ``execute_tool_fn`` returns one result per call, in order. Gemini and
    Anthropic used to find a result's call by tool *name*, so two calls to one
    tool in a turn — the normal case for a search — were answered with the
    first call's id twice (LP-17). A result also names the tool that *ran*,
    which may be a fallback, so the call's own name and id are what go back.
    """
    if len(results) != len(function_calls):
        raise RuntimeError(f"tool executor returned {len(results)} results for {len(function_calls)} calls")
    return list(zip(function_calls, results))


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
        """Single-turn generation. ``text_sink`` (a ``TextSink``), when given,
        receives the answer's text as it is produced (LP-I7)."""
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
        top_p: float = 1.0,
        **kwargs,
    ) -> LLMResponse:
        """
        Full REACT loop: calls generate, executes tool calls, continues until
        no more tool calls or max turns reached.
        execute_tool_fn: async callable(function_calls: list) -> list of tool results,
        one per call in the same order. Every call carries an ``id``.
        """
        ...

    def get_tool_declarations(self, tool_schemas: List[Dict]) -> Any:
        """Convert generic JSON Schema tool defs to provider-specific format."""
        return tool_schemas  # Default: pass through as-is
