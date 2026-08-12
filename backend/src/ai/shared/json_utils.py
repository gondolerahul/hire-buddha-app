"""
ai.shared.json_utils — Shared JSON parsing utilities for LLM output.

Deduplicates the JSON extraction logic that was copy-pasted across
dreaming_engine.py, goal_alignment.py, and other LLM consumers.
"""
import json
import re
from typing import Any, Dict, List, Optional

import logging
logger = logging.getLogger(__name__)


def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text.strip()


def parse_json_array(text: str, warn_label: str = "LLM output") -> List[Dict]:
    """Parse JSON array from LLM output, handling markdown fences.

    Returns empty list on failure (never raises).
    """
    text = strip_markdown_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: extract array via regex
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse JSON array from {warn_label}: {text[:200]}")
    return []


def parse_json_object(text: str, warn_label: str = "LLM output") -> Optional[Dict]:
    """Parse JSON object from LLM output, handling markdown fences.

    Returns None on failure (never raises).
    """
    text = strip_markdown_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: extract object via regex
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse JSON object from {warn_label}: {text[:200]}")
    return None
