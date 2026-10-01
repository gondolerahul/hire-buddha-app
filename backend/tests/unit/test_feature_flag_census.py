"""AK-10 — a declared feature flag must have a reader.

Five ``agent_loop.*`` flags appeared on the admin Feature Flags page and
controlled nothing; a census on 2026-10-01 found 23 such flags across the
kernel, planner, critics, tools and the meta layer. Each was wired at the code
it names or deleted. This census keeps it that way: a key in ``DEFAULTS`` or
``NUMERIC_DEFAULTS`` that no module outside ``feature_flags.py`` mentions fails
the test, unless it is in ``KNOWN_UNREAD`` with the phase that decides it.
"""
from __future__ import annotations

from pathlib import Path

from src.ai.core.feature_flags import DEFAULTS, NUMERIC_DEFAULTS

SRC = Path(__file__).resolve().parents[2] / "src"
FLAGS_MODULE = SRC / "ai" / "core" / "feature_flags.py"

# Declared, not yet read — each waits on a decision recorded in
# docs/current/defect-register/CONSOLIDATED-KERNEL-TOOLS-PLAN.md.
KNOWN_UNREAD: dict[str, str] = {
    # Register 08 (memory) — open items deferred by the product owner.
    "memory.viewport_compact": "register 08, deferred",
    "memory.scope_policy_enforced": "register 08, deferred",
    "memory.embedding_resolver_v2": "register 08, deferred",
    "memory_v2.canonical": "register 08, deferred",
    # TrustLearner has no production caller (PC-11): wire or delete in P7.
    "memory.trust_score_learning": "PC-11, P7",
    # The seven-role Architecture Board has no production caller (MI-20);
    # these gate it and are decided with it in P10.
    "meta_agent.board_routing": "MI-20, P10",
    "meta_agent.spec_critic_required": "MI-20, P10",
    "meta_agent.draft_lifecycle": "MI-20, P10",
    "meta_agent.testdriver_suite_enabled": "MI-20, P10",
    "meta_agent.testdriver_budget_usd": "MI-20, P10",
    "meta_agent.curator_consolidation_enabled": "MI-20, P10",
    "meta_agent.spec_critic_tiebreak": "MI-20, P10",
}


def _source_outside_flags_module() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
        if path != FLAGS_MODULE
    )


def _unread_flags() -> set[str]:
    corpus = _source_outside_flags_module()
    declared = set(DEFAULTS) | set(NUMERIC_DEFAULTS)
    return {
        key for key in declared
        if f'"{key}"' not in corpus and f"'{key}'" not in corpus
    }


def test_every_declared_flag_is_read_or_known() -> None:
    unexpected = sorted(_unread_flags() - set(KNOWN_UNREAD))
    assert not unexpected, (
        "Feature flags declared but read by nothing (wire them where the code "
        f"they name runs, or delete them): {unexpected}"
    )


def test_known_unread_list_is_current() -> None:
    """A flag that gained a reader, or was deleted, leaves KNOWN_UNREAD."""
    stale = sorted(set(KNOWN_UNREAD) - _unread_flags())
    assert not stale, f"Remove from KNOWN_UNREAD — now read or gone: {stale}"
