"""Tests for prompt utility functions — zero LLM dependency."""
import pytest
from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step
from src.ai.schemas import PlanStep, StepType


class TestParseVariables:
    def test_double_brace_replacement(self):
        result = parse_variables("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_single_brace_replacement(self):
        result = parse_variables("Hello {name}", {"name": "World"})
        assert result == "Hello World"

    def test_nested_variable_resolution(self):
        result = parse_variables("{{step_1.output}}", {"step_1": "result text"})
        assert result == "result text"

    def test_missing_variable_preserved(self):
        result = parse_variables("{{missing}}", {"other": "value"})
        assert result == "{{missing}}"

    def test_empty_text(self):
        assert parse_variables("", {"x": "y"}) == ""

    def test_none_text(self):
        assert parse_variables(None, {"x": "y"}) == ""

    def test_multiple_variables(self):
        result = parse_variables("{{a}} and {{b}}", {"a": "X", "b": "Y"})
        assert result == "X and Y"

    def test_dict_variable_resolution(self):
        result = parse_variables("{{step.output}}", {"step": {"output": "val"}})
        assert result == "val"


class TestBuildSandwichPrompt:
    def test_minimal_prompt(self):
        result = build_sandwich_prompt(
            identity="I am an assistant",
            current_task="Do something",
        )
        assert "## Identity & Role" in result
        assert "## Current Task" in result
        assert "Do something" in result

    def test_all_layers_present(self):
        result = build_sandwich_prompt(
            identity="Test agent",
            goal="Achieve X",
            tools=[{"name": "search", "description": "Search the web"}],
            current_task="Find Y",
        )
        assert "## Goal & Objective" in result
        assert "## Available Tools" in result
        assert "search" in result

    def test_no_tools_no_tools_section(self):
        result = build_sandwich_prompt(
            identity="Test",
            current_task="Task",
        )
        assert "## Available Tools" not in result


class TestFilterContextForStep:
    def test_no_policy_returns_full(self):
        ctx = {"a": 1, "b": 2, "c": 3}
        step = PlanStep(name="test", type=StepType.THOUGHT)
        assert filter_context_for_step(step, ctx, None) == ctx

    def test_last_n_policy(self):
        ctx = {"a": 1, "b": 2, "c": 3, "d": 4}
        step = PlanStep(name="test", type=StepType.THOUGHT)
        result = filter_context_for_step(step, ctx, {"type": "LAST_N", "n": 2})
        assert "c" in result
        assert "d" in result

    def test_explicit_policy(self):
        ctx = {"a": 1, "b": 2, "c": 3}
        step = PlanStep(name="test", type=StepType.THOUGHT)
        result = filter_context_for_step(step, ctx, {"type": "EXPLICIT", "explicit_keys": ["a", "c"]})
        assert result == {"a": 1, "c": 3}
