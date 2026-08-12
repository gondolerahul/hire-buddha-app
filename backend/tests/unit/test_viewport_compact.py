"""Phase 11 Track 6 — viewport compact rendering + ops-help move."""
from __future__ import annotations

from src.ai.core.prompt_utils import CORTEX_OPS_HELP, build_sandwich_prompt
from src.ai.memory.cortex_service import (
    CORTEX_OPERATIONS_PROMPT,
    NodeSummaryDTO,
    Viewport,
)


def _node(title: str, summary: str = "ok") -> NodeSummaryDTO:
    return NodeSummaryDTO(
        id="n", title=title, summary=summary,
        status="active", node_type="finding", depth=1,
    )


def _viewport(num_children: int = 3) -> Viewport:
    return Viewport(
        current_node=_node("Current Topic"),
        children=[_node(f"child_{i}", "small summary") for i in range(num_children)],
        parent=None,
        breadcrumb=[{"id": "root", "title": "Root"},
                    {"id": "n", "title": "Current Topic"}],
    )


# ---------------------------------------------------------------------------
# Viewport.to_prompt_text — defaults
# ---------------------------------------------------------------------------


def test_viewport_default_excludes_ops_help() -> None:
    text = _viewport(3).to_prompt_text()
    assert "Current Topic" in text
    assert "CORTEX Operations" not in text


def test_viewport_include_ops_help_emits_block() -> None:
    text = _viewport(3).to_prompt_text(include_ops_help=True, max_chars=2000)
    assert "CORTEX Operations" in text


# ---------------------------------------------------------------------------
# Max-chars budget
# ---------------------------------------------------------------------------


def test_viewport_respects_max_chars() -> None:
    text = _viewport(20).to_prompt_text(max_chars=800)
    assert len(text) <= 1100   # allow a small margin for the truncated children block
    assert "Current Topic" in text   # the current node always lands


def test_viewport_emits_more_children_marker_when_truncated() -> None:
    text = _viewport(20).to_prompt_text(max_chars=600)
    assert "more children" in text


# ---------------------------------------------------------------------------
# build_sandwich_prompt — single ops-help injection
# ---------------------------------------------------------------------------


def test_sandwich_prompt_omits_ops_help_when_cortex_disabled() -> None:
    out = build_sandwich_prompt(
        identity="agent", current_task="do thing", cortex_enabled=False,
    )
    assert "CORTEX Operations" not in out


def test_sandwich_prompt_injects_ops_help_when_cortex_enabled() -> None:
    out = build_sandwich_prompt(
        identity="agent", current_task="do thing", cortex_enabled=True,
    )
    assert "CORTEX Operations" in out
    # …and exactly once.
    assert out.count("CORTEX Operations") == 1


def test_legacy_alias_still_resolves() -> None:
    # cortex_service.CORTEX_OPERATIONS_PROMPT is aliased to the new name.
    assert CORTEX_OPERATIONS_PROMPT is CORTEX_OPS_HELP
