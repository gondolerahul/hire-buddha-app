"""Cross-entity composition graph — Phase 12 `06` §4.2.

DB-gated (skips without Postgres). Exercises record_composition / query_compositions
on the MetaIntelligenceTree, including the incremental-mean accumulation and the
lazy creation of the new section on a tree built before it existed.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.needs_db


@pytest.mark.asyncio
async def test_record_and_query_compositions(db, test_company_id) -> None:
    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree

    tree = MetaIntelligenceTree(db, test_company_id)
    parent = uuid.uuid4()
    child_a = uuid.uuid4()
    child_b = uuid.uuid4()

    # Two outcomes on the same edge → running mean.
    await tree.record_composition(parent_id=parent, child_id=child_a, outcome_score=1.0)
    await tree.record_composition(parent_id=parent, child_id=child_a, outcome_score=0.0)
    # A weaker edge.
    await tree.record_composition(parent_id=parent, child_id=child_b, outcome_score=0.2)

    edges = await tree.query_compositions(parent_id=parent)
    assert len(edges) == 2
    by_child = {e["child_id"]: e for e in edges}
    assert by_child[str(child_a)]["count"] == 2
    assert abs(by_child[str(child_a)]["outcome_score"] - 0.5) < 1e-6
    # Sorted best-first: child_a (0.5) before child_b (0.2).
    assert edges[0]["child_id"] == str(child_a)


@pytest.mark.asyncio
async def test_query_filters_by_child(db, test_company_id) -> None:
    from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree

    tree = MetaIntelligenceTree(db, test_company_id)
    p1, p2, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await tree.record_composition(parent_id=p1, child_id=child, outcome_score=0.9)
    await tree.record_composition(parent_id=p2, child_id=child, outcome_score=0.7)

    edges = await tree.query_compositions(child_id=child)
    assert {e["parent_id"] for e in edges} == {str(p1), str(p2)}
