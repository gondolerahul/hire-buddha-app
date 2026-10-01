"""TL-22…TL-27 — tools that could not work are gone, and stay gone.

``quora`` called an API that does not exist, ``x_ads`` used the wrong auth
scheme, ``youtube_ads`` pinned a stale API version and took ``customer_id`` from
the model; ``xlsx_engine``, the docx templates and the MCP package had no caller.
"""
from __future__ import annotations

from pathlib import Path

import src.ai.tools  # noqa: F401 — registers every tool
from src.ai.social_router import VALID_PLATFORMS
from src.ai.tools.base import ToolRegistry

BACKEND = Path(__file__).resolve().parents[2]


def test_no_tool_of_a_deleted_platform_is_registered() -> None:
    names = set(ToolRegistry._tools)
    for prefix in ("quora_", "x_ads_", "youtube_ads_"):
        assert not [n for n in names if n.startswith(prefix)], prefix


def test_quora_cannot_be_connected() -> None:
    assert "quora" not in VALID_PLATFORMS


def test_the_unwired_modules_are_deleted() -> None:
    for rel in (
        "src/ai/tools/social/quora.py",
        "src/ai/tools/social/x_ads.py",
        "src/ai/tools/social/youtube_ads.py",
        "src/ai/tools/documents/xlsx_engine.py",
        "src/ai/tools/mcp/adapter.py",
        "templates/docx",
    ):
        assert not (BACKEND / rel).exists(), rel
