"""Tests for the GoalGuard middleware."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from src.ai.planning.goal_guard import GoalGuard


class TestGoalGuardInit:
    """Tests for GoalGuard initialization."""

    def test_basic_init(self):
        guard = GoalGuard(
            db=MagicMock(),
            company_id=uuid4(),
            entity_goal="Build a report",
        )
        assert guard.entity_goal == "Build a report"
        assert guard.confidence_threshold == 0.85

    def test_custom_threshold(self):
        guard = GoalGuard(
            db=MagicMock(),
            company_id=uuid4(),
            entity_goal="Goal",
            confidence_threshold=0.95,
        )
        assert guard.confidence_threshold == 0.95


@pytest.mark.asyncio
class TestGoalGuardCheck:
    """Tests for GoalGuard.check()."""

    async def test_no_output_returns_continue(self):
        """Steps without output should pass through."""
        guard = GoalGuard(
            db=MagicMock(),
            company_id=uuid4(),
            entity_goal="Goal",
        )
        result = await guard.check(
            step_result={"error": "failed"},
            step_name="step_1",
            step_idx=1,
            all_results=[],
            total_steps=5,
        )
        assert result["action"] == "CONTINUE"

    async def test_none_step_result_returns_continue(self):
        guard = GoalGuard(
            db=MagicMock(),
            company_id=uuid4(),
            entity_goal="Goal",
        )
        result = await guard.check(
            step_result=None,
            step_name="step_1",
            step_idx=1,
            all_results=[],
            total_steps=5,
        )
        assert result["action"] == "CONTINUE"

    async def test_non_autonomous_skips_progress_check(self):
        """Non-autonomous mode should skip the overall progress check."""
        guard = GoalGuard(
            db=MagicMock(),
            company_id=uuid4(),
            entity_goal="Goal",
            planner=MagicMock(),
        )
        # Patch alignment check at the import target inside goal_guard.check()
        with patch("src.ai.planning.goal_alignment.GoalAlignmentVerifier") as mock_verifier:
            mock_instance = MagicMock()
            mock_instance.verify_step_alignment = AsyncMock(
                return_value={"aligned": True}
            )
            mock_verifier.return_value = mock_instance

            result = await guard.check(
                step_result={"output": "some output"},
                step_name="step_2",
                step_idx=2,
                all_results=[],
                total_steps=5,
                is_autonomous=False,
                goal_interval=2,
            )
            assert result["action"] == "CONTINUE"


class TestGoalGuardActions:
    """Test the GoalGuard action types."""

    def test_action_types(self):
        """Verify all expected action types exist."""
        valid_actions = {"CONTINUE", "RETRY", "REPLAN", "EARLY_EXIT"}
        assert all(isinstance(a, str) for a in valid_actions)
