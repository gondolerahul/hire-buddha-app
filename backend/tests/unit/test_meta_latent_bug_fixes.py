"""Regression tests for three latent bugs surfaced by the C12 mypy --strict
pass over ``backend/src/ai/meta`` (Phase 12 stage-1 consolidation).

Each bug was masked at runtime (the resulting exception was swallowed), so the
broken code path silently produced a degraded result instead of raising. These
tests pin the *behaviour* of the fixed path so a re-introduction of the original
signature/await/column mismatch fails loudly instead of going quiet again.

  1. (Curator CREATE gate — its tests went with the Curator, MI-20.)
  2. RegistrySearchService IO-compat — ``db.get`` was used synchronously on an
     AsyncSession (coroutine → AttributeError → scoring broken).
  3. PlatformSchemaCompiler model endpoints — the query referenced columns that
     do not exist on IntegrationRegistry (AttributeError → discovery returned []).
"""
from __future__ import annotations

import inspect
from typing import Any, List, Optional
from uuid import UUID, uuid4

import pytest

from src.ai.meta.platform_schema_compiler import PlatformSchemaCompiler
from src.ai.meta.registry_search_service import (
    MatchCandidate,
    MatchType,
    RegistrySearchService,
    SearchRequest,
)


# ---------------------------------------------------------------------------
# Bug 2 — IO-compat scoring awaits AsyncSession.get
# ---------------------------------------------------------------------------


class _FakeEntity:
    io_contract = {
        "input_schema": {"properties": {"a": {}, "b": {}}},
        "output_schema": {"properties": {"x": {}}},
    }


class _FakeAsyncDB:
    """AsyncSession stand-in whose ``get`` is a coroutine (as the real one is)."""

    def __init__(self, entity: Any) -> None:
        self._entity = entity
        self.get_calls = 0

    async def get(self, model: Any, pk: Any) -> Any:
        self.get_calls += 1
        return self._entity


def test_score_io_compatibility_is_async() -> None:
    # A sync method on an AsyncSession is the bug; the fix makes both the
    # scoring method and its phase wrapper coroutines.
    assert inspect.iscoroutinefunction(RegistrySearchService._score_io_compatibility)
    assert inspect.iscoroutinefunction(RegistrySearchService._phase15_io_contract)


@pytest.mark.asyncio
async def test_score_io_compatibility_awaits_db_get() -> None:
    db = _FakeAsyncDB(_FakeEntity())
    svc = RegistrySearchService(db=db, company_id=uuid4())  # type: ignore[arg-type]
    request = SearchRequest(
        intent="x",
        io_schema={
            "input": {"properties": {"a": {}}},
            "output": {"properties": {"x": {}}},
        },
    )

    score = await svc._score_io_compatibility(uuid4(), request)

    # input "a" and output "x" are both covered -> perfect compatibility.
    assert score == 1.0
    assert db.get_calls == 1


@pytest.mark.asyncio
async def test_phase15_io_contract_mutates_candidate_score() -> None:
    db = _FakeAsyncDB(_FakeEntity())
    svc = RegistrySearchService(db=db, company_id=uuid4())  # type: ignore[arg-type]
    request = SearchRequest(
        intent="x",
        io_schema={
            "input": {"properties": {"a": {}}},
            "output": {"properties": {"x": {}}},
        },
    )
    candidate = MatchCandidate(
        entity_id=uuid4(),
        entity_name="cand",
        entity_type="SKILL",
        match_type=MatchType.CREATE,
        structural_score=0.5,
        io_score=0.5,
        semantic_score=0.0,
        execution_score=0.5,
        combined_score=0.1,
    )

    await svc._phase15_io_contract(request, [candidate])

    assert candidate.io_score == 1.0


# ---------------------------------------------------------------------------
# Bug 3 — model-endpoint discovery queries real IntegrationRegistry columns
# ---------------------------------------------------------------------------


class _FakeInteg:
    provider_name = "anthropic"
    model_name = "claude-3-5-sonnet"
    service_category = "LLM"
    service_sku = "claude-3-5-sonnet-in"


class _FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeExecDB:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.executed_query: Any = None

    async def execute(self, query: Any) -> _FakeScalarResult:
        # Building ``query`` already dereferenced the IntegrationRegistry
        # columns; a missing column would raise before we ever get here.
        self.executed_query = query
        return _FakeScalarResult(self._rows)


@pytest.mark.asyncio
async def test_compile_model_endpoints_maps_real_columns() -> None:
    db = _FakeExecDB([_FakeInteg()])
    compiler = PlatformSchemaCompiler(db=db, company_id=uuid4())  # type: ignore[arg-type]

    endpoints = await compiler._compile_model_endpoints()

    assert db.executed_query is not None  # query built without AttributeError
    assert endpoints == [
        {
            "provider": "anthropic",
            "model_name": "claude-3-5-sonnet",
            "category": "LLM",
            "service_sku": "claude-3-5-sonnet-in",
        }
    ]
