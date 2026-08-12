"""
Unit tests for src.ai.step_executor
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.ai.step_executor import StepExecutorService
from src.ai.schemas import StepType, PlanStep


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def executor(mock_db):
    return StepExecutorService(
        db=mock_db,
        redis=AsyncMock(),
        company_id=uuid4(),
        usage_service=MagicMock(),
        cortex_bridge=MagicMock(),
    )


class TestExecuteStepRouting:

    @pytest.mark.asyncio
    async def test_routes_thought(self, executor):
        """Should dispatch THOUGHT type to _execute_thought."""
        step = MagicMock(spec=PlanStep)
        step.type = StepType.THOUGHT
        step.name = "think"

        with patch.object(executor, '_execute_thought',
                          AsyncMock(return_value={"step": "think", "output": "done"})) as mock:
            result = await executor._execute_step(MagicMock(), MagicMock(), step, {})
            mock.assert_called_once()
            assert result["output"] == "done"

    @pytest.mark.asyncio
    async def test_routes_tool_call(self, executor):
        """Should dispatch TOOL_CALL type to _execute_tool_call."""
        step = MagicMock(spec=PlanStep)
        step.type = StepType.TOOL_CALL
        step.name = "search"

        with patch.object(executor, '_execute_tool_call',
                          AsyncMock(return_value={"step": "search", "output": "results"})) as mock:
            result = await executor._execute_step(MagicMock(), MagicMock(), step, {})
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_child_invocation_not_inline(self, executor):
        """CHILD_ENTITY_INVOCATION no longer runs inline: child entities are
        dispatched as their own runs by the loop's ChildEntityExecutor
        (create_child_run + async suspend/resume). Reaching the inline step
        path is a routing bug and raises."""
        from src.ai.core.exceptions import AgentError

        step = MagicMock(spec=PlanStep)
        step.type = StepType.CHILD_ENTITY_INVOCATION
        step.name = "invoke_child"

        with pytest.raises(AgentError):
            await executor._execute_step(MagicMock(), MagicMock(), step, {})

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self, executor):
        """Should return error dict for unknown step type."""
        step = MagicMock(spec=PlanStep)
        step.type = "UNKNOWN_TYPE"

        result = await executor._execute_step(MagicMock(), MagicMock(), step, {})
        assert "error" in result


class TestIsFormatError:

    def test_detects_json_parse_error(self, executor):
        output = '{"error": "invalid json: Expecting value at line 1"}'
        assert executor._is_format_error(output.lower(), {"invalid json", "json", "parse"}) is True

    def test_ignores_infra_error(self, executor):
        output = '{"error": "API key not configured"}'
        assert executor._is_format_error(output.lower(), {"json", "parse"}) is False

    def test_ignores_non_error(self, executor):
        output = '{"status": "success", "data": "some result"}'
        assert executor._is_format_error(output.lower(), {"json", "parse"}) is False


class TestShouldExit:

    def test_returns_false_no_conditions(self, executor):
        step = MagicMock(spec=PlanStep)
        step.exit_conditions = []
        step.name = "step_1"
        assert executor._should_exit(step, {}) is False
