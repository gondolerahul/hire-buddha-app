"""Regression: DreamingEngine cosine/clustering must accept numpy ndarrays.

pgvector loads ``CortexNode.embedding`` columns as numpy ndarrays, not plain
lists. The old guard ``if not a or not b`` in ``_cosine_similarity`` raised

    ValueError: The truth value of an array with more than one element is
    ambiguous. Use a.any() or a.all()

whenever the dreaming pipeline (reached via the ``dreaming_outcome_trigger``
arq job → ``DreamingEngine.dream`` → ``_recognize_patterns`` →
``_cluster_observations``) tried to cluster real embeddings, crashing every
run. These tests pin the behaviour with non-empty ndarrays.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.ai.memory.dreaming_engine import DreamingEngine


def test_cosine_similarity_accepts_nonempty_ndarrays():
    # Non-empty ndarrays previously raised ValueError on `not a`/`not b`.
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([1.0, 2.0, 3.0])

    sim = DreamingEngine._cosine_similarity(a, b)

    assert sim == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_ndarrays():
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])

    assert DreamingEngine._cosine_similarity(a, b) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "a, b",
    [
        (None, np.array([1.0, 2.0])),
        (np.array([1.0, 2.0]), None),
        (np.array([]), np.array([])),
        (np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0])),  # length mismatch
    ],
)
def test_cosine_similarity_degenerate_inputs_return_zero(a, b):
    assert DreamingEngine._cosine_similarity(a, b) == 0.0


def test_cluster_observations_with_ndarray_embeddings():
    """`_cluster_observations` reaches `_cosine_similarity` with ndarray
    embeddings — this is the exact path the failing arq job hits."""
    engine = DreamingEngine.__new__(DreamingEngine)  # no DB needed

    # Two near-identical observations + one orthogonal one.
    obs = [
        SimpleNamespace(id=1, embedding=np.array([1.0, 0.0, 0.0])),
        SimpleNamespace(id=2, embedding=np.array([0.99, 0.01, 0.0])),
        SimpleNamespace(id=3, embedding=np.array([0.0, 0.0, 1.0])),
    ]

    clusters = engine._cluster_observations(obs)

    # The two similar observations cluster together; the orthogonal one alone.
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]
