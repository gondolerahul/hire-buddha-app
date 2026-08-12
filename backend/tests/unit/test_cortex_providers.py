"""Host CORTEX provider adapters satisfy the cortex_memory Protocols (`04`).

The host side of the injection boundary: ``ai.memory.cortex_providers`` wraps
``LLMRouter`` / ``EmbeddingService`` / ``UsageService`` / ``ExecutionRun`` to
implement the package's ``LLMProvider`` / ``EmbeddingProvider`` /
``UsageReporter`` / ``RunRegistry``. These checks are structural (no LLM/DB I/O).
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cortex_memory.providers import (
    EmbeddingProvider,
    LLMProvider,
    RunRegistry,
    UsageReporter,
)
from src.ai.memory.cortex_providers import (
    CortexProviders,
    HostEmbeddingProvider,
    HostLLMProvider,
    HostRunRegistry,
    HostUsageReporter,
    build_cortex_providers,
)


def test_host_adapters_satisfy_package_protocols() -> None:
    db = MagicMock()
    cid = uuid4()
    assert isinstance(HostLLMProvider(db, cid), LLMProvider)
    assert isinstance(HostEmbeddingProvider(db, cid), EmbeddingProvider)
    assert isinstance(HostUsageReporter(), UsageReporter)
    assert isinstance(HostRunRegistry(db), RunRegistry)


def test_build_cortex_providers_wires_full_set() -> None:
    providers = build_cortex_providers(MagicMock(), uuid4())
    assert isinstance(providers, CortexProviders)
    assert isinstance(providers.llm, LLMProvider)
    assert isinstance(providers.embedding, EmbeddingProvider)
    assert isinstance(providers.usage, UsageReporter)
    assert isinstance(providers.runs, RunRegistry)
    assert providers.embedding.dimension() == 768


@pytest.mark.asyncio
async def test_host_usage_reporter_is_noop() -> None:
    r = HostUsageReporter()
    assert await r.report_llm(model="m", input_tokens=1, output_tokens=2, cost_usd=0.0) is None
    assert await r.report_embedding(model="m", char_count=3, cost_usd=0.0) is None


@pytest.mark.asyncio
async def test_host_run_registry_bad_id_returns_none() -> None:
    reg = HostRunRegistry(MagicMock())
    assert await reg.get_run("not-a-uuid") is None
