"""v1 memory is gone: episodes and documents live only in CORTEX trees.

* A finished run is recorded as an episode in its entity's Episodic Tree
  (the write side the deleted ``MemoryRouter.write_episodic`` never delivered).
* Uploaded documents are ingested into a Knowledge Tree — the entity's, or the
  company-wide tree — instead of the ``document_chunks`` table.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.ai.memory.run_memory import record_episode


def test_v1_modules_are_gone() -> None:
    for mod in ("src.ai.memory.memory_service", "src.ai.memory.legacy_episodic_reader",
                "src.ai.orm.memory"):
        assert importlib.util.find_spec(mod) is None, mod
    from src.ai import models
    assert not hasattr(models, "EpisodicMemory")
    assert not hasattr(models, "DocumentChunk")


# ---------------------------------------------------------------------------
# record_episode
# ---------------------------------------------------------------------------


def _db_returning(run):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = run
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _run(memory: dict | None, **overrides):
    entity = SimpleNamespace(name="research-director",
                             capabilities={"memory": memory} if memory else {})
    base = dict(
        id=uuid4(), entity_id=uuid4(), company_id=uuid4(), entity=entity,
        created_at=None, status="COMPLETED",
        input_data={"input": "What moves EV battery prices?", "__agent_state__": {"iteration": 3}},
        result_data={"output": "Lithium carbonate spot prices."},
        context_state={}, total_cost_usd=0.12, total_tokens=4200, execution_time_ms=9000,
    )
    return SimpleNamespace(**{**base, **overrides})


@pytest.mark.asyncio
async def test_finished_run_becomes_an_episode() -> None:
    run = _run({"enabled": True, "memory_scope": "FULL"})
    db = _db_returning(run)
    tree_id = uuid4()
    with patch("src.ai.memory.episodic_tree_service.EpisodicTreeService") as svc:
        svc.return_value.write_episode = AsyncMock()
        await record_episode(db, run.id, runtime_tree_id=tree_id)

    kwargs = svc.return_value.write_episode.call_args.kwargs
    assert kwargs["entity_id"] == run.entity_id
    assert kwargs["runtime_tree_id"] == tree_id
    # The episode summarises the task and the answer, not inherited plumbing.
    assert kwargs["run"].input_data == "What moves EV battery prices?"
    assert kwargs["run"].result_data == "Lithium carbonate spot prices."
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_no_episode_when_memory_disabled() -> None:
    run = _run(None)
    with patch("src.ai.memory.episodic_tree_service.EpisodicTreeService") as svc:
        await record_episode(_db_returning(run), run.id)
    svc.assert_not_called()


@pytest.mark.asyncio
async def test_episode_failure_does_not_break_the_run() -> None:
    run = _run({"enabled": True})
    db = _db_returning(run)
    with patch("src.ai.memory.episodic_tree_service.EpisodicTreeService") as svc:
        svc.return_value.write_episode = AsyncMock(side_effect=RuntimeError("embedding down"))
        await record_episode(db, run.id)
    db.rollback.assert_awaited()


# ---------------------------------------------------------------------------
# process_document → Knowledge Tree
# ---------------------------------------------------------------------------


async def _process(document, *, total: int, embedded: int):
    from src.ai.core import arq_jobs

    session = MagicMock()
    doc_result = MagicMock()
    doc_result.scalar_one_or_none.return_value = document
    session.execute = AsyncMock(return_value=doc_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    kt = MagicMock()
    tree = SimpleNamespace(id=uuid4())
    kt.get_or_create_knowledge_tree = AsyncMock(return_value=tree)
    kt.get_or_create_company_knowledge_tree = AsyncMock(return_value=tree)
    kt.ingest_document = AsyncMock(return_value=5)
    kt.chunk_embedding_counts = AsyncMock(return_value=(total, embedded))
    with patch.object(arq_jobs, "AsyncSessionLocal", return_value=session_cm), \
         patch("src.ai.memory.knowledge_tree_service.KnowledgeTreeService", return_value=kt):
        await arq_jobs.process_document({}, str(document.id), b"# Title\nbody", "txt", "notes.txt")
    return kt


def _document(entity_id=None):
    return SimpleNamespace(id=uuid4(), company_id=uuid4(), entity_id=entity_id,
                           filename="notes.txt", upload_status="processing")


@pytest.mark.asyncio
async def test_company_document_goes_to_company_tree() -> None:
    doc = _document()
    kt = await _process(doc, total=3, embedded=3)
    kt.get_or_create_company_knowledge_tree.assert_awaited_once()
    kt.get_or_create_knowledge_tree.assert_not_called()
    assert kt.ingest_document.call_args.kwargs["content"] == "# Title\nbody"
    assert doc.upload_status == "completed"


@pytest.mark.asyncio
async def test_entity_document_goes_to_entity_tree() -> None:
    entity_id = uuid4()
    doc = _document(entity_id)
    kt = await _process(doc, total=4, embedded=2)
    kt.get_or_create_knowledge_tree.assert_awaited_once_with(entity_id=entity_id)
    assert doc.upload_status == "partial"


@pytest.mark.asyncio
async def test_unsearchable_document_is_failed() -> None:
    doc = _document()
    await _process(doc, total=3, embedded=0)
    assert doc.upload_status == "failed"
