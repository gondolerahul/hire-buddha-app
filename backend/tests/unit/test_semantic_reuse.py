"""A strong semantic match can decide reuse (P10.4 — MI-09).

The semantic score weighs 0.35 and ADAPT needs 0.60, so a perfect semantic
match on its own scored 0.35 and was classified CREATE: the search's most
expensive signal could never change a decision.
"""
from __future__ import annotations

import uuid

import pytest

from src.ai.meta.registry_search_service import MatchCandidate, MatchType, RegistrySearchService, SearchRequest


def _candidate(semantic: float) -> MatchCandidate:
    combined = semantic * RegistrySearchService.SEMANTIC_WEIGHT
    return MatchCandidate(entity_id=uuid.uuid4(), entity_name="Support triage", entity_type="AGENT",
                          match_type=MatchType.CREATE, structural_score=0.0, io_score=0.0,
                          semantic_score=semantic, execution_score=0.0, combined_score=combined)


def _classify(candidate):
    svc = RegistrySearchService(db=None, company_id=uuid.uuid4())
    (c,) = svc._classify_candidates([candidate], SearchRequest(intent="triage support email"))
    return c.match_type


def test_a_near_identical_meaning_is_at_least_adapt():
    assert _classify(_candidate(0.9)) == MatchType.ADAPT
    assert _classify(_candidate(0.5)) == MatchType.CREATE


@pytest.mark.asyncio
async def test_a_near_identical_meaning_is_a_duplicate_for_the_gate(monkeypatch):
    import src.ai.meta.registry_search_service as search_mod
    from src.ai.meta.anti_sprawl import AntiSprawlGuard

    class _Search(RegistrySearchService):
        async def search(self, request, top_k=5, include_templates=True):
            return [_candidate(0.97)]

    monkeypatch.setattr(search_mod, "RegistrySearchService", _Search)
    result = await AntiSprawlGuard(db=None, company_id=uuid.uuid4()).check_semantic_duplicate(
        description="triage support email", required_tools=[])
    assert result["is_duplicate"] is True and not result.get("unavailable")
