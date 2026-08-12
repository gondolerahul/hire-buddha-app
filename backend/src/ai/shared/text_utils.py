"""
ai.shared.text_utils — Shared text processing utilities.

Phase 10C: Extracts the private _summarize function from memory_service.py
to fix the cross-module private import in episodic_tree_service.py.
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def truncate_for_storage(data: Any, max_chars: int = 400) -> str:
    """Convert any value to a short readable string for episodic storage.

    Extracted from ``memory_service._summarize`` to eliminate cross-module
    private function imports.

    Args:
        data: Any Python value (dict, str, list, etc.)
        max_chars: Maximum character length for the output

    Returns:
        Truncated string representation
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data[:max_chars]
    try:
        s = json.dumps(data, default=str)
    except Exception:
        s = str(data)
    return s[:max_chars]


async def summarize_text(db, company_id, text: str, max_tokens: int = 200) -> str:
    """Summarize text using a cheap LLM call.

    Args:
        db: AsyncSession
        company_id: UUID for LLM routing
        text: Text to summarize (truncated to 4000 chars)
        max_tokens: Max output tokens

    Returns:
        Summarized text string
    """
    try:
        from src.ai.llm.router import LLMRouter
        llm = LLMRouter(db=db, company_id=company_id)
        response = await llm.call_llm(
            task_type="text_generation",
            system_prompt="Summarize the following text concisely.",
            user_prompt=text[:4000],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return response.output
    except Exception as e:
        logger.warning(f"Text summarization failed: {e}")
        return text[:max_tokens * 4]  # Rough fallback: ~4 chars per token
