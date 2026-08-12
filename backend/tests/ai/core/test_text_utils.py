"""Tests for shared text processing utilities."""
import pytest
from src.ai.shared.text_utils import truncate_for_storage


class TestTruncateForStorage:
    """Tests for truncate_for_storage (extracted from memory_service._summarize)."""

    def test_none_returns_empty(self):
        assert truncate_for_storage(None) == ""

    def test_string_passthrough(self):
        assert truncate_for_storage("hello") == "hello"

    def test_string_truncation(self):
        assert truncate_for_storage("hello world", max_chars=5) == "hello"

    def test_dict_serialization(self):
        result = truncate_for_storage({"key": "value"})
        assert result == '{"key": "value"}'

    def test_dict_truncation(self):
        data = {"key": "a" * 500}
        result = truncate_for_storage(data, max_chars=20)
        assert len(result) == 20

    def test_list_serialization(self):
        result = truncate_for_storage([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_integer_serialization(self):
        assert truncate_for_storage(42) == "42"

    def test_nested_dict(self):
        data = {"a": {"b": "c"}}
        result = truncate_for_storage(data)
        assert '"b"' in result

    def test_default_max_chars_is_400(self):
        long_text = "x" * 1000
        result = truncate_for_storage(long_text)
        assert len(result) == 400

    def test_empty_string(self):
        assert truncate_for_storage("") == ""

    def test_empty_dict(self):
        assert truncate_for_storage({}) == "{}"
