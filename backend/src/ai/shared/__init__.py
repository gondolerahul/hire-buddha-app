"""
ai.shared — Cross-cutting utilities shared across all AI domains.
"""

from src.ai.shared.text_utils import truncate_for_storage, summarize_text
from src.ai.shared.json_utils import parse_json_object, parse_json_array, strip_markdown_fences

__all__ = [
    "truncate_for_storage",
    "summarize_text",
    "parse_json_object",
    "parse_json_array",
    "strip_markdown_fences",
]
