"""The duplicate gate refuses when it cannot evaluate (P10.2 — MI-01).

``check_semantic_duplicate`` answered "no duplicate" on any exception, so a
registry-search failure, an embedding error or a database blip turned
duplicate protection off with no signal anywhere.
"""
from __future__ import annotations

import uuid

import pytest

from src.ai.meta import anti_sprawl
from src.ai.meta.anti_sprawl import AntiSprawlGuard


class _BrokenSearch:
    def __init__(self, *_a, **_kw):
        pass

    async def search(self, *_a, **_kw):
        raise ConnectionError("registry search is down")


@pytest.mark.asyncio
async def test_a_broken_search_refuses_the_creation_and_says_so(monkeypatch):
    import src.ai.core.events as events
    import src.ai.meta.registry_search_service as search_mod

    seen = []
    monkeypatch.setattr(search_mod, "RegistrySearchService", _BrokenSearch)
    monkeypatch.setattr(events, "event", lambda name, **kw: seen.append((name, kw)))

    result = await AntiSprawlGuard(db=None, company_id=uuid.uuid4()).check_semantic_duplicate(
        description="summarise a web page", required_tools=["scraper_tool"])

    assert result["is_duplicate"] is True and result["unavailable"] is True
    assert "could not run" in result["message"]
    (name, payload), = seen
    assert name == "gate.failed" and payload["gate"] == "semantic_duplicate"
    assert "ConnectionError" in payload["error"]
    assert anti_sprawl  # module under test imported
