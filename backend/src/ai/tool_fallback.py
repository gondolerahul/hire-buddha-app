"""
tool_fallback.py — Tool Fallback Chains (Phase 9 Hardening)

When a primary tool fails (empty output, error, timeout), the step executor
tries alternative tools from this registry.  Each chain defines:
  - alternatives: ordered list of fallback tool IDs
  - input_transform: optional function to adapt the input for the fallback tool

Usage (from step_executor.py):
    from src.ai.tool_fallback import get_fallback_tool
    alt_tool_id, alt_input = get_fallback_tool("web_search", original_input)
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fallback chain definitions
# ---------------------------------------------------------------------------

TOOL_FALLBACK_CHAINS = {
    "web_search": {
        "alternatives": ["headless_browser"],
        "input_transforms": {
            "headless_browser": "_web_search_to_browser",
        },
    },
    "batch_web_search": {
        "alternatives": ["web_search"],
        "input_transforms": {
            "web_search": "_batch_to_single_search",
        },
    },
    "scraper_tool": {
        "alternatives": ["headless_browser"],
        "input_transforms": {
            "headless_browser": "_scraper_to_browser",
        },
    },
    "headless_browser": {
        "alternatives": ["scraper_tool"],
        "input_transforms": {
            "scraper_tool": "_browser_to_scraper",
        },
    },
}


# ---------------------------------------------------------------------------
# Input transform functions
# ---------------------------------------------------------------------------

def _web_search_to_browser(raw_input: str) -> str:
    """Convert a web_search query to a headless_browser navigation."""
    # Extract the search query from the input
    query = raw_input.strip()
    try:
        data = json.loads(raw_input)
        query = data.get("query", data.get("input", raw_input))
    except (json.JSONDecodeError, TypeError):
        pass

    return json.dumps({
        "url": f"https://www.google.com/search?q={query}",
        "action": "extract_text",
        "wait_for": "body",
    })


def _batch_to_single_search(raw_input: str) -> str:
    """Extract the first query from a batch_web_search input."""
    try:
        data = json.loads(raw_input)
        queries = data.get("queries", [])
        if queries:
            first_query = queries[0] if isinstance(queries[0], str) else queries[0].get("query", "")
            return json.dumps({"query": first_query})
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: use the first line as a query
    lines = raw_input.strip().split('\n')
    return json.dumps({"query": lines[0][:200]}) if lines else raw_input


def _scraper_to_browser(raw_input: str) -> str:
    """Convert a scraper_tool URL to a headless_browser navigation."""
    url = raw_input.strip()
    try:
        data = json.loads(raw_input)
        url = data.get("url", data.get("input", raw_input))
    except (json.JSONDecodeError, TypeError):
        pass

    return json.dumps({
        "url": url,
        "action": "extract_text",
        "wait_for": "body",
    })


def _browser_to_scraper(raw_input: str) -> str:
    """Convert a headless_browser request to a scraper_tool URL."""
    try:
        data = json.loads(raw_input)
        url = data.get("url", "")
        if url:
            return url
    except (json.JSONDecodeError, TypeError):
        pass
    return raw_input


# Registry of transform functions
_TRANSFORM_REGISTRY = {
    "_web_search_to_browser": _web_search_to_browser,
    "_batch_to_single_search": _batch_to_single_search,
    "_scraper_to_browser": _scraper_to_browser,
    "_browser_to_scraper": _browser_to_scraper,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_fallback_tool(
    primary_tool_id: str,
    raw_input: str,
) -> Tuple[Optional[str], str]:
    """
    Get the first available fallback tool for a failed primary tool.

    Returns:
        (fallback_tool_id, transformed_input) or (None, raw_input) if no fallback.
    """
    chain = TOOL_FALLBACK_CHAINS.get(primary_tool_id)
    if not chain:
        return None, raw_input

    alternatives = chain.get("alternatives", [])
    transforms = chain.get("input_transforms", {})

    for alt_tool_id in alternatives:
        transform_name = transforms.get(alt_tool_id)
        if transform_name and transform_name in _TRANSFORM_REGISTRY:
            try:
                transformed = _TRANSFORM_REGISTRY[transform_name](raw_input)
                logger.info(
                    f"Fallback: {primary_tool_id} → {alt_tool_id} "
                    f"(transform: {transform_name})"
                )
                return alt_tool_id, transformed
            except Exception as e:
                logger.warning(f"Input transform {transform_name} failed: {e}")
                # Fall through to return with original input
                return alt_tool_id, raw_input
        else:
            # No transform needed — pass input as-is
            return alt_tool_id, raw_input

    return None, raw_input
