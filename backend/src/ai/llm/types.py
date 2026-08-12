"""
ai.llm.types — Shared types and SDK compatibility patches.

Contains the unified LLMResponse dataclass and the google-genai
FinishReason monkey-patch.

Extracted from llm_router.py during Phase 10B restructuring.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SDK Compatibility Patch — google-genai v0.4.0 FinishReason enum gap
# ---------------------------------------------------------------------------
# The Gemini API may return finish_reason values (e.g. 'UNEXPECTED_TOOL_CALL')
# that are newer than the installed SDK's Pydantic Literal type definitions.
# This causes a pydantic ValidationError during response deserialization.
# We monkey-patch the SDK types at import time to prevent this crash.
# ---------------------------------------------------------------------------

def _patch_genai_finish_reason():
    """Extend the google-genai SDK's FinishReason Literal to include newer API values."""
    try:
        from google.genai import types as genai_types
        import typing

        # The FinishReason is defined as a Literal type alias in google.genai.types.
        # We need to patch the Candidate model's finish_reason field validator
        # to accept unknown string values gracefully.
        if hasattr(genai_types, 'Candidate'):
            candidate_cls = genai_types.Candidate
            if hasattr(candidate_cls, 'model_fields') and 'finish_reason' in candidate_cls.model_fields:
                field_info = candidate_cls.model_fields['finish_reason']
                permissive_type = typing.Optional[str]

                # Update BOTH the FieldInfo annotation and the class __annotations__
                # Pydantic v2 requires both to be in sync for model_rebuild to work.
                field_info.annotation = permissive_type
                candidate_cls.__annotations__['finish_reason'] = permissive_type
                try:
                    candidate_cls.model_rebuild(force=True)
                    logger.debug("Patched google-genai Candidate.finish_reason to accept any string")
                except Exception:
                    logger.warning("Failed to patch Candidate model, falling back")
    except Exception as e:
        logger.debug(f"google-genai FinishReason patch skipped: {e}")


_patch_genai_finish_reason()


# ---------------------------------------------------------------------------
# Unified response dataclass — provider-agnostic
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    output: str
    function_calls: List[Dict[str, Any]] = field(default_factory=list)
    # [{name: str, args: dict}]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    model_name: str = ""
    provider: str = ""
    finish_reason: str = "stop"

    @property
    def cost_usd(self) -> float:
        """Estimated cost — placeholder for future per-model pricing."""
        return 0.0
