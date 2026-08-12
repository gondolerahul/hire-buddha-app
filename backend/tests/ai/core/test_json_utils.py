"""Tests for shared JSON parsing utilities."""
import pytest
from src.ai.shared.json_utils import parse_json_array, parse_json_object, strip_markdown_fences


class TestStripMarkdownFences:
    def test_strips_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_strips_plain_fence(self):
        text = '```\n[1, 2, 3]\n```'
        assert strip_markdown_fences(text) == '[1, 2, 3]'

    def test_no_fence_passthrough(self):
        text = '{"key": "value"}'
        assert strip_markdown_fences(text) == '{"key": "value"}'


class TestParseJsonObject:
    def test_valid_json(self):
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_invalid_returns_none(self):
        assert parse_json_object("not json") is None

    def test_embedded_json(self):
        text = 'Here is the result: {"score": 85, "pass": true} end'
        result = parse_json_object(text)
        assert result["score"] == 85

    def test_array_returns_none(self):
        assert parse_json_object('[1, 2, 3]') is None


class TestParseJsonArray:
    def test_valid_array(self):
        assert parse_json_array('[1, 2, 3]') == [1, 2, 3]

    def test_fenced_array(self):
        assert parse_json_array('```json\n["a", "b"]\n```') == ["a", "b"]

    def test_invalid_returns_empty(self):
        assert parse_json_array("not json") == []

    def test_embedded_array(self):
        text = 'Sub-goals: ["research", "analyze", "report"] done'
        result = parse_json_array(text)
        assert result == ["research", "analyze", "report"]
