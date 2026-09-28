"""Dreaming never skips an episode.

Episodes are consumed per episode (``metadata_extra["consolidated_at"]``), and
the consolidation timestamp only advances when a pass actually consolidated.
Previously a pass with too few new episodes still advanced the timestamp, so
those episodes fell behind the watermark and were never consolidated.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

import pytest

from cortex_memory import DreamingEngine, EpisodicTreeService, ExperienceTreeService
from cortex_memory.providers import LLMResult
from cortex_memory.providers_reference import HashEmbeddingProvider
from cortex_memory.tests.test_services import _StructuredLLM, _fake_run

pytestmark = pytest.mark.asyncio


def _emb() -> HashEmbeddingProvider:
    return HashEmbeddingProvider(dim=768)


async def _write_episodes(db: Any, company: Any, entity: Any, n: int) -> None:
    episodic = EpisodicTreeService(db, company, embedding=_emb())
    for _ in range(n):
        await episodic.write_episode(entity_id=entity, run=_fake_run(company, entity))
    await db.commit()


async def _pending(db: Any, company: Any, entity: Any) -> int:
    svc = EpisodicTreeService(db, company, embedding=_emb())
    return len(await svc.get_unconsolidated_episodes(entity, limit=1000))


async def _last_consolidated(db: Any, company: Any, entity: Any) -> Any:
    tree = await ExperienceTreeService(db, company).get_or_create_experience_tree(entity)
    return tree.last_consolidated_at


class _TextLLM:
    def __init__(self, text: Optional[str] = None, fail: bool = False) -> None:
        self.text, self.fail = text, fail

    async def complete(self, *, system: str, user: str, model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: Any = None,
                       task_type: Optional[str] = None) -> LLMResult:
        if self.fail:
            raise RuntimeError("provider down")
        return LLMResult(text=self.text or "", model="stub")


async def test_too_few_episodes_are_kept_for_a_later_pass(db) -> None:
    company, entity = uuid4(), uuid4()
    engine = DreamingEngine(db, company, llm=_StructuredLLM(), embedding=_emb())

    await _write_episodes(db, company, entity, 3)
    result = await engine.dream(entity)
    await db.commit()
    assert result["observations_created"] == 0
    assert await _pending(db, company, entity) == 3
    assert await _last_consolidated(db, company, entity) is None  # gate stays open

    await _write_episodes(db, company, entity, 2)
    result = await engine.dream(entity)
    await db.commit()
    assert result["observations_created"] >= 1
    assert await _pending(db, company, entity) == 0  # all five consolidated
    assert await _last_consolidated(db, company, entity) is not None


async def test_consolidated_episodes_are_not_resent(db) -> None:
    company, entity = uuid4(), uuid4()
    await _write_episodes(db, company, entity, 5)
    engine = DreamingEngine(db, company, llm=_StructuredLLM(), embedding=_emb())
    assert (await engine.dream(entity, force=True))["observations_created"] >= 1
    await db.commit()

    assert await engine._consolidate_episodes(entity) is None  # nothing pending
    await _write_episodes(db, company, entity, 5)
    assert await engine._consolidate_episodes(entity)  # only the new five


async def test_backlog_is_worked_off_oldest_first(db) -> None:
    company, entity = uuid4(), uuid4()
    await _write_episodes(db, company, entity, 6)
    engine = DreamingEngine(db, company, llm=_StructuredLLM(), embedding=_emb())
    engine.BATCH_SIZE, engine.MIN_EPISODES_FOR_DREAMING = 4, 2

    await engine.dream(entity, force=True)
    await db.commit()
    assert await _pending(db, company, entity) == 2
    await engine.dream(entity, force=True)
    await db.commit()
    assert await _pending(db, company, entity) == 0


@pytest.mark.parametrize("llm", [
    _TextLLM(fail=True),                    # provider error
    _TextLLM(text="not json at all"),       # unparseable answer
    None,                                   # no LLM injected
])
async def test_failed_pass_leaves_episodes_pending(db, llm) -> None:
    company, entity = uuid4(), uuid4()
    await _write_episodes(db, company, entity, 5)
    engine = DreamingEngine(db, company, llm=llm, embedding=_emb())

    assert await engine.dream(entity) == {
        "observations_created": 0, "patterns_created": 0, "rules_created": 0,
    }
    await db.commit()
    assert await _pending(db, company, entity) == 5
    assert await _last_consolidated(db, company, entity) is None


async def test_explicit_empty_answer_consumes_the_episodes(db) -> None:
    company, entity = uuid4(), uuid4()
    await _write_episodes(db, company, entity, 5)
    engine = DreamingEngine(db, company, llm=_TextLLM(text="[]"), embedding=_emb())

    await engine.dream(entity)
    await db.commit()
    assert await _pending(db, company, entity) == 0
    assert await _last_consolidated(db, company, entity) is not None


async def test_phases_leave_room_for_thinking_models(db) -> None:
    """Thinking models spend max_tokens on reasoning; a tight budget truncates
    the JSON answer (Gemini 2.5 at 2000 tokens returned 79 visible tokens)."""
    budgets: list[Any] = []

    class _Recording(_StructuredLLM):
        async def complete(self, **kw: Any) -> LLMResult:
            budgets.append(kw.get("max_tokens"))
            return await super().complete(**kw)

    company, entity = uuid4(), uuid4()
    await _write_episodes(db, company, entity, 5)
    await DreamingEngine(db, company, llm=_Recording(), embedding=_emb()).dream(entity, force=True)
    assert budgets and min(budgets) >= 4096
