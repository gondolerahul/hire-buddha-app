"""Curator consolidation merge plans — Phase 12 `06` §4.1.

Hermetic: the pure plan-selection logic. Locks in winner selection, the
min-cluster / min-similarity gates, and the always-HITL posture.
"""
from __future__ import annotations

from src.ai.meta.consolidation import EntityRef, build_merge_plan, select_winner


def _cluster(n=5):
    return [EntityRef(entity_id=f"e{i}", name=f"agent {i}", version=1, usage_count=i)
            for i in range(n)]


def test_select_winner_prefers_usage_then_version_then_recency() -> None:
    ents = [
        EntityRef(entity_id="a", usage_count=5, version=1, updated_at="2026-01-01"),
        EntityRef(entity_id="b", usage_count=5, version=3, updated_at="2026-01-01"),
        EntityRef(entity_id="c", usage_count=2, version=9, updated_at="2026-06-01"),
    ]
    assert select_winner(ents).entity_id == "b"  # usage tie → higher version


def test_build_plan_picks_winner_and_losers() -> None:
    plan = build_merge_plan(_cluster(5), 0.95)
    assert plan is not None
    assert plan.winner_id == "e4"  # highest usage_count
    assert set(plan.loser_ids) == {"e0", "e1", "e2", "e3"}
    assert plan.requires_hitl is True
    assert plan.reference_repoints == plan.loser_ids
    assert plan.rule_forks == plan.loser_ids


def test_below_min_cluster_returns_none() -> None:
    assert build_merge_plan(_cluster(4), 0.95) is None


def test_below_min_similarity_returns_none() -> None:
    assert build_merge_plan(_cluster(6), 0.85) is None


def test_custom_thresholds() -> None:
    plan = build_merge_plan(_cluster(3), 0.92, min_cluster=3, min_similarity=0.9)
    assert plan is not None
    assert len(plan.loser_ids) == 2
