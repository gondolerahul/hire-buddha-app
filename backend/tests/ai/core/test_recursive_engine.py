"""Tests for the GoalNode decomposition DTO.

The RecursiveReasoningEngine (the engine_type=="RECURSIVE" implementation) was
deleted in C13: engine_type is gone and the loop maps goal-only AGENTs onto the
planner. GoalNode remains a CORTEX schema DTO.
"""
from decimal import Decimal
from src.ai.schemas import GoalNode


class TestGoalNodeIntegration:
    """Tests for GoalNode structure used by recursive engine."""

    def test_basic_goal_node(self):
        root = GoalNode(goal="Research AI", depth=0)
        assert root.goal == "Research AI"
        assert root.depth == 0
        assert root.children == []
        assert root.status == "pending"

    def test_goal_node_tree_structure(self):
        root = GoalNode(goal="Research AI", depth=0)
        child1 = GoalNode(goal="Find papers", depth=1, parent=root)
        child2 = GoalNode(goal="Analyze trends", depth=1, parent=root)
        root.children = [child1, child2]

        assert len(root.children) == 2
        assert not root.is_leaf()
        assert child1.is_leaf()

    def test_goal_node_to_dict(self):
        root = GoalNode(goal="Test goal", depth=0, confidence=0.8, status="completed")
        root.result = "Success"
        d = root.to_dict()
        assert d["goal"] == "Test goal"
        assert d["depth"] == 0
        assert d["confidence"] == 0.8
        assert d["status"] == "completed"
        assert d["result"] == "Success"

    def test_nested_to_dict(self):
        root = GoalNode(goal="Parent", depth=0)
        child = GoalNode(goal="Child", depth=1, parent=root)
        root.children = [child]
        d = root.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["goal"] == "Child"

    def test_cost_ceiling_as_decimal(self):
        """Verify cost ceiling works with Decimal arithmetic."""
        ceiling = Decimal("1.50")
        cost = Decimal("0.75")
        assert cost < ceiling
        cost += Decimal("0.80")
        assert cost >= ceiling
