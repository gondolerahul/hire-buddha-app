"""
Deeper service integration tests (DB-backed; skipped without a database).

Drives the full service surface — ingestion, the episodic/experience/intelligence
domain trees, the dreaming pipeline, and the v2 assembler — with host-free
providers, so coverage reflects the package alone. A ``_StructuredLLM`` returns
prompt-appropriate JSON so the dreaming phases parse and write real nodes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Optional, Sequence
from uuid import uuid4

import pytest

from cortex_memory import (
    CortexService,
    DreamingEngine,
    EpisodicTreeService,
    ExperienceTreeService,
    IntelligenceTreeService,
    MemoryAssemblyService,
)
from cortex_memory.ingestion import CortexIngestionPipeline
from cortex_memory.providers import EmbeddingResult, LLMResult
from cortex_memory.providers_reference import HashEmbeddingProvider

pytestmark = pytest.mark.asyncio


class _StructuredLLM:
    """LLMProvider returning JSON appropriate to each dreaming/ingestion phase."""

    async def complete(self, *, system: str, user: str, model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: Any = None,
                       task_type: Optional[str] = None) -> LLMResult:
        s = system.lower()
        if "observation" in s:
            text = json.dumps([
                {"summary": f"obs {n}", "confidence": 0.9, "category": "performance"}
                for n in range(4)
            ])
        elif "pattern" in s:
            text = json.dumps({"summary": "a pattern", "pattern_strength": 0.85, "supporting": 2})
        elif "rule" in s or "intelligence" in s or "distil" in s:
            text = json.dumps([
                {"summary": "rule one", "rule_type": "instruction", "confidence": 0.9},
            ])
        else:
            text = "A concise summary."
        return LLMResult(text=text, model="structured", input_tokens=10, output_tokens=10)


def _fake_run(company_id: Any, entity_id: Any) -> Any:
    return SimpleNamespace(
        id=uuid4(), entity_id=entity_id, company_id=company_id, user_id=uuid4(),
        created_at=datetime.utcnow(), input_data={"input": "do the task"},
        result_data={"output": "task done"}, context_state={},
        status="COMPLETED", total_cost_usd=0.01, total_tokens=100,
        execution_time_ms=1234,
    )


async def test_ingestion_creates_nodes(db) -> None:
    company = uuid4()
    svc = CortexService(db, company, llm=_StructuredLLM())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="ingest")
    knowledge = await svc.get_knowledge_root(tree.id)
    await db.commit()

    pipeline = CortexIngestionPipeline(
        db, company, llm=_StructuredLLM(),
        cortex=CortexService(db, company, llm=_StructuredLLM()),
    )
    content = "# Title\n\nFirst section body text.\n\n## Sub\n\nMore body text here.\n"
    n = await pipeline.ingest_document(
        tree_id=tree.id, parent_node_id=knowledge.id,
        document_id=uuid4(), content=content, filename="doc.md",
    )
    await db.commit()
    assert n >= 1


async def test_episodic_write_query_recent(db) -> None:
    company, entity = uuid4(), uuid4()
    svc = EpisodicTreeService(db, company, embedding=HashEmbeddingProvider(dim=768))
    for _ in range(3):
        await svc.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()

    recent = await svc.get_recent_episodes(entity, limit=10)
    assert len(recent) >= 3
    ranged = await svc.query_by_time(
        entity, start_date=datetime.utcnow() - timedelta(days=1),
        end_date=datetime.utcnow() + timedelta(days=1), limit=10,
    )
    assert len(ranged) >= 3


async def test_experience_tree_roots(db) -> None:
    company, entity = uuid4(), uuid4()
    svc = ExperienceTreeService(db, company)
    tree = await svc.get_or_create_experience_tree(entity)
    await db.commit()
    assert tree.entity_id == entity
    obs_root = await svc.get_observations_root(entity)
    await db.commit()
    assert obs_root is not None


async def test_dreaming_pipeline(db) -> None:
    company, entity = uuid4(), uuid4()
    # Seed enough episodes for the dreaming threshold.
    episodic = EpisodicTreeService(db, company, embedding=HashEmbeddingProvider(dim=768))
    for _ in range(6):
        await episodic.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()

    engine = DreamingEngine(db, company, llm=_StructuredLLM(), embedding=HashEmbeddingProvider(dim=768))
    result = await engine.dream(entity, force=True)
    await db.commit()
    assert set(result) == {"observations_created", "patterns_created", "rules_created"}
    assert result["observations_created"] >= 1


async def test_assembler_runs(db) -> None:
    company, entity = uuid4(), uuid4()
    # Give it some episodic history to assemble.
    episodic = EpisodicTreeService(db, company, embedding=HashEmbeddingProvider(dim=768))
    await episodic.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()

    assembler = MemoryAssemblyService(
        db, company,
        embedding=HashEmbeddingProvider(dim=768), llm=_StructuredLLM(), child_run_factory=None,
    )
    res = await assembler.assemble_runtime_memory(
        entity_id=entity, task_description="what did we learn?",
        include_domains=["knowledge", "experience", "intelligence", "episodic"],
    )
    assert res is not None
    assert hasattr(res, "formatted_prompt") or hasattr(res, "episodic_context")


async def test_a_failed_domain_is_named_and_the_others_still_read(db, monkeypatch) -> None:
    """MC-06: an empty list from an error is not an empty memory, and a failed
    query does not abort the transaction the later domains read in."""
    from sqlalchemy import text

    company, entity = uuid4(), uuid4()
    episodic = EpisodicTreeService(db, company, embedding=HashEmbeddingProvider(dim=768))
    await episodic.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()

    async def _broken(self, entity_id, task_description):
        await self.db.execute(text("SELECT * FROM mc06_no_such_table"))
        return []

    monkeypatch.setattr(MemoryAssemblyService, "_retrieve_experience", _broken)
    assembler = MemoryAssemblyService(
        db, company,
        embedding=HashEmbeddingProvider(dim=768), llm=_StructuredLLM(), child_run_factory=None,
    )
    res = await assembler.assemble_runtime_memory(
        entity_id=entity, task_description="what did we learn?",
        include_domains=["experience", "episodic"],
    )
    assert set(res.failures) == {"experience"}
    assert "mc06_no_such_table" in res.failures["experience"]
    assert res.experience_suggestions == []
    assert res.episodic_context  # read after the failed query, in the same transaction


async def test_an_empty_memory_reports_no_failures(db) -> None:
    assembler = MemoryAssemblyService(
        db, uuid4(),
        embedding=HashEmbeddingProvider(dim=768), llm=_StructuredLLM(), child_run_factory=None,
    )
    res = await assembler.assemble_runtime_memory(entity_id=uuid4(), task_description="anything")
    assert res.failures == {}
    assert (res.knowledge_refs, res.experience_suggestions, res.intelligence_rules,
            res.episodic_context) == ([], [], [], [])


class _NoVectorEmbedding(HashEmbeddingProvider):
    """A provider that is configured but answers with no vector — the host's
    ``EmbeddingService`` does this when Vertex refuses (expired credentials)."""

    async def embed(self, texts: Sequence[str], *, model: Optional[str] = None) -> EmbeddingResult:
        return EmbeddingResult(vectors=[None] * len(texts))  # type: ignore[list-item]


async def test_an_embedding_outage_is_a_failure_not_an_empty_memory(db) -> None:
    """MC-06, found live: with the query unembeddable, every semantic read
    returned [] as if nothing matched. Each is now named in ``failures``."""
    company, entity = uuid4(), uuid4()
    episodic = EpisodicTreeService(db, company, embedding=HashEmbeddingProvider(dim=768))
    await episodic.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()

    assembler = MemoryAssemblyService(
        db, company, embedding=_NoVectorEmbedding(dim=768), llm=_StructuredLLM(), child_run_factory=None,
    )
    res = await assembler.assemble_runtime_memory(entity_id=entity, task_description="what did we learn?")
    assert set(res.failures) == {"knowledge", "experience", "intelligence", "episodic_topic"}
    assert all("EmbeddingUnavailable" in error for error in res.failures.values())
    assert res.episodic_context  # the recent episodes need no embedding


async def test_no_embedding_provider_is_not_a_failure(db) -> None:
    assembler = MemoryAssemblyService(db, uuid4(), embedding=None, llm=_StructuredLLM(), child_run_factory=None)
    res = await assembler.assemble_runtime_memory(entity_id=uuid4(), task_description="anything")
    assert res.failures == {}


async def test_service_recurse_with_factory(db) -> None:
    company = uuid4()
    created: dict = {}

    async def _factory(*, tree, node_id, task, task_node_id, result_slot, execution_run_id):
        rid = uuid4()
        created["rid"] = rid
        return rid

    svc = CortexService(db, company, llm=_StructuredLLM(), child_run_factory=_factory)
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="recurse")
    working = await svc.get_working_root(tree.id)
    await db.commit()
    task_node_id, child_run_id = await svc.recurse(
        node_id=working.id, task="a sub-task", result_slot="slot1",
    )
    await db.commit()
    assert task_node_id is not None
    assert child_run_id == created.get("rid")


async def test_service_resume_and_roots(db) -> None:
    company = uuid4()
    svc = CortexService(db, company, llm=_StructuredLLM())
    tree = await svc.create_tree(entity_id=uuid4(), user_id=None, task_description="resume")
    await db.commit()
    rtree, viewport, _ckpt = await svc.resume_tree(tree.id)
    assert rtree.id == tree.id and viewport is not None
    assert await svc.get_knowledge_root(tree.id) is not None
    assert await svc.get_working_root(tree.id) is not None
