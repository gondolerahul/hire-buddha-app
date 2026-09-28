"""Tests for the memory assembler."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.ai.memory.assembler import assemble_memory


def _result(**overrides):
    base = dict(formatted_prompt="", intelligence_rules=[], episodic_context=[],
                knowledge_refs=[], experience_suggestions=[])
    return SimpleNamespace(**{**base, **overrides})


@pytest.mark.asyncio
class TestAssembleMemory:

    async def test_none_scope_returns_empty(self):
        """NONE scope returns {} without touching the domains."""
        with patch("src.ai.memory.memory_assembly_service.MemoryAssemblyService") as svc:
            result = await assemble_memory(MagicMock(), uuid4(), uuid4(), memory_scope="NONE")
        assert result == {}
        svc.assert_not_called()

    async def test_publishes_non_empty_keys(self):
        rules = [{"title": "Cite sources", "rule": "Always cite", "confidence": 0.9}]
        episodes = [{"input": "q", "output": "a", "status": "COMPLETED", "at": ""}]
        assembler = MagicMock()
        assembler.assemble_runtime_memory = AsyncMock(return_value=_result(
            formatted_prompt="## Learned Intelligence", intelligence_rules=rules,
            episodic_context=episodes,
        ))
        with patch("src.ai.memory.memory_assembly_service.MemoryAssemblyService",
                   return_value=assembler):
            result = await assemble_memory(
                MagicMock(), uuid4(), uuid4(), task_description="test task",
            )
        assert result == {
            "__memory__": "## Learned Intelligence",
            "__intelligence_rules__": rules,
            "__episodic_memory__": episodes,
        }
        assert assembler.assemble_runtime_memory.call_args.kwargs["task_description"] == "test task"

    async def test_empty_memory_publishes_nothing(self):
        assembler = MagicMock()
        assembler.assemble_runtime_memory = AsyncMock(return_value=_result())
        with patch("src.ai.memory.memory_assembly_service.MemoryAssemblyService",
                   return_value=assembler):
            assert await assemble_memory(MagicMock(), uuid4(), uuid4()) == {}

    async def test_knowledge_only_scope_selects_domains(self):
        assembler = MagicMock()
        assembler.assemble_runtime_memory = AsyncMock(return_value=_result())
        with patch("src.ai.memory.memory_assembly_service.MemoryAssemblyService",
                   return_value=assembler):
            await assemble_memory(MagicMock(), uuid4(), uuid4(), memory_scope="KNOWLEDGE_ONLY")
        assert assembler.assemble_runtime_memory.call_args.kwargs["include_domains"] == [
            "knowledge", "intelligence",
        ]
