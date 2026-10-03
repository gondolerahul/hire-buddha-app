"""
ai.llm.types — Shared LLM response types.

Contains the unified LLMResponse dataclass. There is no SDK patch: google-genai
parses a ``finish_reason`` newer than itself (it warns and keeps the value), so
the import-time rewrite of its ``Candidate`` model that lived here is gone
(LP-23).

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified response dataclass — provider-agnostic
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Attachment:
    """A file sent to the model beside the prompt text (LP-24): an image, or
    a PDF where the provider takes one. In a message it is the part
    ``{"inline_data": {"mime_type": ..., "data": <bytes>}}``; each adapter
    translates it. It never enters a prompt string, a span or a log — those
    record :meth:`describe`."""
    mime_type: str
    data: bytes

    def part(self) -> Dict[str, Any]:
        return {"inline_data": {"mime_type": self.mime_type, "data": self.data}}

    def describe(self) -> str:
        return f"[{self.mime_type}, {len(self.data)} bytes]"


def inline_parts(parts: Any) -> List[Dict[str, Any]]:
    """The ``inline_data`` payloads among a message's parts."""
    if not isinstance(parts, list):
        return []
    return [p["inline_data"] for p in parts if isinstance(p, dict) and isinstance(p.get("inline_data"), dict)]


class TextSink(Protocol):
    """Where a call's text goes while it is generated (LP-I7). ``reset`` says
    the text so far is void: a provider attempt was retried, or the router
    moved to the fallback."""

    async def delta(self, text: str) -> None: ...

    async def reset(self) -> None: ...


# ``finish_reason`` of a ReAct loop that ran out of turns while the model was
# still calling tools: the model was cut off mid-task, not finished (LP-19).
FINISH_MAX_TURNS = "MAX_TURNS"


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    output: str
    function_calls: List[Dict[str, Any]] = field(default_factory=list)
    # [{name: str, args: dict}]
    prompt_tokens: int = 0
    # Billable output tokens. Includes thinking tokens, which providers bill
    # at the output rate; ``thinking_tokens`` is that share (LP-06).
    completion_tokens: int = 0
    thinking_tokens: int = 0
    latency_ms: int = 0
    model_name: str = ""
    provider: str = ""
    finish_reason: str = "stop"
    # No ``cost_usd``: a response does not know its price. Cost is the
    # attributed ``usage_logs`` row written from the SKU lookup; a property that
    # always returned 0.0 here invited callers to bill nothing (LP-02).

    @property
    def hit_turn_limit(self) -> bool:
        """The ReAct loop ran out of turns before the model finished (LP-19)."""
        return self.finish_reason == FINISH_MAX_TURNS
