"""Tests for context state utilities."""
import pytest
from src.ai.core.context_utils import store_step_output, sanitize_context_for_persistence


class TestStoreStepOutput:
    def test_stores_by_name_and_id(self):
        ctx = {}
        store_step_output(ctx, "Research", "step_1", "findings text")
        assert ctx["Research"] == "findings text"
        assert ctx["step_1"] == "findings text"

    def test_same_name_and_id_no_duplicate(self):
        ctx = {}
        store_step_output(ctx, "step_1", "step_1", "output")
        assert ctx["step_1"] == "output"
        assert len(ctx) == 1

    def test_empty_step_id_skips_id_store(self):
        ctx = {}
        store_step_output(ctx, "Research", "", "output")
        assert ctx["Research"] == "output"
        assert "" not in ctx


class TestSanitizeContext:
    def test_strips_sensitive_keys(self):
        ctx = {"input": "hello", "api_key": "secret123", "output": "world"}
        result = sanitize_context_for_persistence(ctx)
        assert "api_key" not in result
        assert result["input"] == "hello"
        assert result["output"] == "world"

    def test_empty_context(self):
        assert sanitize_context_for_persistence({}) == {}

    def test_none_context(self):
        assert sanitize_context_for_persistence(None) is None

    def test_strips_model_override(self):
        ctx = {"__model_override": "gpt-4", "data": "value"}
        result = sanitize_context_for_persistence(ctx)
        assert "__model_override" not in result
        assert result["data"] == "value"

    def test_case_insensitive_sensitive_keys(self):
        ctx = {"API_KEY": "secret", "normal": "ok"}
        result = sanitize_context_for_persistence(ctx)
        assert "API_KEY" not in result
        assert result["normal"] == "ok"
