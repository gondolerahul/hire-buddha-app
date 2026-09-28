"""
cortex_memory._textutil — small pure text helpers (vendored, host-free).

These are tiny utility functions the CORTEX services use; vendored into the
package so it carries no dependency on the host's ``ai.shared`` utilities.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, cast

logger = logging.getLogger(__name__)


def truncate_for_storage(data: Any, max_chars: int = 400) -> str:
    """Convert any value to a short readable string for episodic storage."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data[:max_chars]
    try:
        s = json.dumps(data, default=str)
    except Exception:
        s = str(data)
    return s[:max_chars]


def strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return text.strip()


def parse_json_array(text: str, warn_label: str = "LLM output") -> List[Dict[str, Any]]:
    """Parse a JSON array from LLM output (markdown-fence aware). [] on failure."""
    text = strip_markdown_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return cast(List[Dict[str, Any]], result)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return cast(List[Dict[str, Any]], json.loads(match.group()))
        except json.JSONDecodeError:
            pass
    logger.warning(f"Failed to parse JSON array from {warn_label}: {text[:200]}")
    return []


def parse_json_object(text: str, warn_label: str = "LLM output") -> Optional[Dict[str, Any]]:
    """Parse a JSON object from LLM output (markdown-fence aware). None on failure."""
    text = strip_markdown_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return cast(Dict[str, Any], result)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return cast(Dict[str, Any], json.loads(match.group()))
        except json.JSONDecodeError:
            pass
    logger.warning(f"Failed to parse JSON object from {warn_label}: {text[:200]}")
    return None


__all__ = [
    "truncate_for_storage",
    "strip_markdown_fences",
    "parse_json_array",
    "parse_json_object",
]
