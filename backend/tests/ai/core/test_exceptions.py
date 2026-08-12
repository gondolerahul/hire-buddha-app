"""Tests for the exception hierarchy."""
import pytest
from src.ai.core.exceptions import (
    AgentError, UncertaintySignal, GoalDriftError,
    ParallelStepError, StepTimeoutError, MetaAgentAbort,
    EntityNotFoundError, PlanningError, CortexError, ToolExecutionError,
)


class TestAgentError:
    def test_base_error(self):
        err = AgentError("something broke")
        assert str(err) == "something broke"
        assert isinstance(err, Exception)


class TestUncertaintySignal:
    def test_basic_creation(self):
        sig = UncertaintySignal("What do you mean?", confidence=0.3)
        assert sig.question == "What do you mean?"
        assert sig.confidence == 0.3
        assert sig.alternatives == []

    def test_with_alternatives(self):
        sig = UncertaintySignal("Unclear", alternatives=["A", "B"])
        assert sig.alternatives == ["A", "B"]

    def test_is_agent_error(self):
        assert issubclass(UncertaintySignal, AgentError)


class TestParallelStepError:
    def test_formats_failures(self):
        err = ParallelStepError([("step_1", "timeout"), ("step_3", "crash")])
        assert "2 parallel step(s) failed" in str(err)
        assert err.failures == [("step_1", "timeout"), ("step_3", "crash")]


class TestStepTimeoutError:
    def test_format(self):
        err = StepTimeoutError("Research", 30000)
        assert "Research" in str(err)
        assert "30000" in str(err)
        assert err.step_name == "Research"
        assert err.timeout_ms == 30000


class TestEntityNotFoundError:
    def test_includes_entity_id(self):
        err = EntityNotFoundError("abc-123", "deleted")
        assert "abc-123" in str(err)
        assert err.entity_id == "abc-123"


class TestToolExecutionError:
    def test_includes_tool_name(self):
        err = ToolExecutionError("web_search", "network timeout")
        assert "web_search" in str(err)
        assert "network timeout" in str(err)
        assert err.tool_name == "web_search"


class TestSubclassing:
    def test_all_are_agent_errors(self):
        for cls in [GoalDriftError, PlanningError, CortexError, MetaAgentAbort]:
            assert issubclass(cls, AgentError)

    def test_catchable_as_agent_error(self):
        with pytest.raises(AgentError):
            raise GoalDriftError("drifted")
