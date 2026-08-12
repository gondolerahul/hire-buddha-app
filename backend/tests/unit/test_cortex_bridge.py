"""
Unit tests for src.ai.cortex_bridge
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.ai.memory.cortex_bridge import CortexBridge


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.pubsub = MagicMock(return_value=AsyncMock())
    return r


@pytest.fixture
def bridge(mock_db, mock_redis):
    return CortexBridge(
        db=mock_db,
        company_id=uuid4(),
        usage_service=MagicMock(),
        redis=mock_redis,
    )


class TestContextSizeTracking:
    """Tests for the incremental context size counter (PERF-3)."""

    def test_initial_size_is_zero(self, bridge):
        assert bridge._context_size_bytes == 0

    def test_update_context_size_add(self, bridge):
        bridge.update_context_size("step_1", old_value="", new_value="hello world")
        assert bridge._context_size_bytes == len("hello world")

    def test_update_context_size_replace(self, bridge):
        bridge.update_context_size("step_1", old_value="", new_value="short")
        bridge.update_context_size("step_1", old_value="short", new_value="much longer value")
        assert bridge._context_size_bytes == len("much longer value")

    def test_update_context_size_clamps_negative(self, bridge):
        bridge._context_size_bytes = 5
        bridge.update_context_size("k", old_value="a" * 100, new_value="")
        assert bridge._context_size_bytes == 0

    def test_reset_context_size(self, bridge):
        bridge.reset_context_size({"a": "hello", "b": "world"})
        assert bridge._context_size_bytes == len("hello") + len("world")


class TestBuildTaskDescription:

    def test_builds_from_entity(self, bridge):
        entity = MagicMock()
        entity.name = "TestAgent"
        entity.goal = "Summarize documents"
        entity.identity = {"system_prompt": "You are helpful."}
        entity.io_contract = {"output_schema": {"type": "string"}}

        desc = bridge.build_task_description(entity, {"input": "test data"})
        assert isinstance(desc, str)
        assert len(desc) > 0


class TestBufferAndFlush:

    def test_buffer_node_adds_to_buffer(self, bridge):
        bridge.buffer_node(
            parent_id=uuid4(),
            node_type="step",
            title="Test Step",
            content="Result data",
        )
        assert len(bridge._write_buffer) == 1

    @pytest.mark.asyncio
    async def test_flush_buffer_writes_and_clears(self, bridge):
        bridge.buffer_node(parent_id=uuid4(), node_type="step", title="S1")
        bridge.buffer_node(parent_id=uuid4(), node_type="step", title="S2")

        with patch.object(bridge.cortex, 'write', AsyncMock()):
            count = await bridge.flush_buffer(bridge.cortex)
            assert count == 2
            assert len(bridge._write_buffer) == 0

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_returns_zero(self, bridge):
        count = await bridge.flush_buffer(bridge.cortex)
        assert count == 0


class TestRefreshViewport:

    @pytest.mark.asyncio
    async def test_cache_hit_skips_navigate(self, bridge, mock_redis):
        """Should use cached viewport when Redis has it."""
        mock_redis.get = AsyncMock(return_value=b"cached viewport text")
        tree = MagicMock()
        tree.resume_cursor_id = None
        tree.root_node_id = uuid4()
        tree.id = uuid4()
        context = {}

        with patch.object(bridge.cortex, 'navigate', AsyncMock()) as nav:
            await bridge.refresh_viewport(bridge.cortex, tree, context)
            nav.assert_not_called()
        assert context.get("__cortex_viewport__") == "cached viewport text"

    @pytest.mark.asyncio
    async def test_cache_miss_calls_navigate(self, bridge, mock_redis):
        """Should call navigate and cache result on miss."""
        mock_redis.get = AsyncMock(return_value=None)
        viewport = MagicMock()
        viewport.to_prompt_text.return_value = "fresh viewport"
        tree = MagicMock()
        tree.resume_cursor_id = None
        tree.root_node_id = uuid4()
        tree.id = uuid4()
        context = {}

        with patch.object(bridge.cortex, 'navigate', AsyncMock(return_value=viewport)):
            await bridge.refresh_viewport(bridge.cortex, tree, context)
        assert context["__cortex_viewport__"] == "fresh viewport"
        mock_redis.set.assert_called_once()


class TestWriteCheckpoint:

    @pytest.mark.asyncio
    async def test_uses_incremental_counter(self, bridge):
        """Should use _context_size_bytes // 4 instead of O(n) scan."""
        bridge._context_size_bytes = 4000  # = 1000 estimated tokens
        tree = MagicMock()
        tree.id = uuid4()

        with patch.object(bridge.cortex, 'check_and_compact', AsyncMock()) as compact:
            await bridge.write_checkpoint(bridge.cortex, tree, {}, "step_1")
            compact.assert_called_once_with(tree.id, 1000)
