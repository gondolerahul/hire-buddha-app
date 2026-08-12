"""Phase 11 Track 6 — DomainTreeBase + per-domain retrieval weights."""
from __future__ import annotations

import pytest

from src.ai.memory.domains import (
    DEFAULT_DOMAIN_WEIGHTS,
    EpisodicWeights,
    ExperienceWeights,
    IntelligenceWeights,
    KnowledgeWeights,
    score_signals,
)


# ---------------------------------------------------------------------------
# score_signals — pure function
# ---------------------------------------------------------------------------


def test_score_with_all_signals_returns_weighted_average() -> None:
    weights = {"semantic": 1.0, "recency": 1.0, "user_match": 0.0, "success": 0.0}
    signals = {"semantic": 0.8, "recency": 0.4, "user_match": 0.9, "success": 1.0}
    # denominator = 2 (only semantic and recency carry weight)
    # numerator   = 0.8 + 0.4 = 1.2
    assert score_signals(weights, signals) == pytest.approx(0.6)


def test_score_missing_signal_treated_as_zero() -> None:
    weights = {"semantic": 1.0, "recency": 0.5, "user_match": 0.0, "success": 0.0}
    score = score_signals(weights, {"semantic": 1.0})
    # numerator = 1.0; denominator = 1.5
    assert score == pytest.approx(1.0 / 1.5)


def test_score_zero_weights_is_zero() -> None:
    assert score_signals({"semantic": 0, "recency": 0, "user_match": 0, "success": 0},
                         {"semantic": 1, "recency": 1}) == 0.0


# ---------------------------------------------------------------------------
# Domain weights — pinning the canonical table
# ---------------------------------------------------------------------------


def test_domain_weight_registry_complete() -> None:
    assert set(DEFAULT_DOMAIN_WEIGHTS) == {
        "knowledge", "experience", "intelligence", "episodic",
    }


def test_knowledge_weights_prioritise_semantic() -> None:
    # Knowledge has the highest semantic weight and zero user_match/success.
    assert KnowledgeWeights["semantic"] == 1.0
    assert KnowledgeWeights["user_match"] == 0.0
    assert KnowledgeWeights["success"] == 0.0


def test_experience_weights_carry_success_signal() -> None:
    assert ExperienceWeights["success"] > 0.0
    assert ExperienceWeights["user_match"] > 0.0


def test_intelligence_weights_no_user_match() -> None:
    assert IntelligenceWeights["user_match"] == 0.0
    assert IntelligenceWeights["success"] == 0.0


def test_episodic_weights_lean_on_recency_and_user_match() -> None:
    assert EpisodicWeights["recency"] >= EpisodicWeights["semantic"]
    assert EpisodicWeights["user_match"] > 0.0


# ---------------------------------------------------------------------------
# Comparative behaviour — same signals, different weights → different ordering
# ---------------------------------------------------------------------------


def test_per_domain_weights_produce_different_orderings() -> None:
    # Item A is semantically strong but old.
    # Item B is mildly relevant but very recent and matches the user.
    item_a = {"semantic": 0.9, "recency": 0.1, "user_match": 0.1, "success": 0.0}
    item_b = {"semantic": 0.5, "recency": 0.9, "user_match": 0.9, "success": 0.6}
    # Knowledge ranking prefers A; Episodic ranking should prefer B.
    assert score_signals(KnowledgeWeights, item_a) > score_signals(KnowledgeWeights, item_b)
    assert score_signals(EpisodicWeights, item_b) > score_signals(EpisodicWeights, item_a)
