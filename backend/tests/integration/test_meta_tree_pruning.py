"""The meta-intelligence tree archives its least useful rows, not its oldest (P10.5 — MI-15).

Each section was pruned at 200 rows by deleting the least recently updated
ones: a rare anti-pattern that had not recurred lately — the one most worth
remembering — went first and left no record. Real Postgres, rolled back.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

import src.ai.meta.meta_intelligence_tree as tree_mod
from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree

pytestmark = pytest.mark.needs_db


async def _rows(db, tree):
    from src.ai.memory.cortex_models import CortexNode
    section = await tree.section_node("anti_patterns")
    return {r.title: r for r in (await db.execute(
        select(CortexNode).where(CortexNode.parent_id == section.id))).scalars()}


@pytest.mark.asyncio
async def test_over_the_cap_the_least_evidenced_rows_are_archived(db, test_company_id, monkeypatch):
    monkeypatch.setattr(tree_mod, "MAX_ROWS_PER_SECTION", 3)
    tree = MetaIntelligenceTree(db, test_company_id)
    await tree.add_anti_pattern(title="rare but proven", evidence_count=5)   # oldest, well evidenced
    await tree.add_anti_pattern(title="severe once", severity="high")
    await tree.add_anti_pattern(title="seen twice", evidence_count=2)
    await tree.add_anti_pattern(title="noise a")
    await tree.add_anti_pattern(title="noise b")

    rows = await _rows(db, tree)
    assert len(rows) == 5                                   # nothing deleted
    archived = {t for t, r in rows.items() if (r.metadata_extra or {}).get("archived_at")}
    # Least evidence goes first: both one-off rows, though newer than the rest.
    assert archived == {"noise a", "noise b"}
    titles = {r.title for r in await tree.query_anti_patterns(top_k=10)}
    assert titles == {"rare but proven", "severe once", "seen twice"}


@pytest.mark.asyncio
async def test_an_archived_pattern_that_recurs_comes_back(db, test_company_id, monkeypatch):
    monkeypatch.setattr(tree_mod, "MAX_ROWS_PER_SECTION", 1)
    tree = MetaIntelligenceTree(db, test_company_id)
    await tree.add_anti_pattern(title="first")
    await tree.add_anti_pattern(title="second")
    assert {r.title for r in await tree.query_anti_patterns(top_k=10)} == {"second"}

    await tree.add_anti_pattern(title="first", evidence_count=2)   # it recurred
    row = (await _rows(db, tree))["first"]
    assert (row.metadata_extra or {}).get("archived_at") is None
    assert row.metadata_extra["evidence_count"] == 3
    assert "first" in {r.title for r in await tree.query_anti_patterns(top_k=10)}
