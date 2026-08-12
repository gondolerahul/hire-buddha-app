"""
Unit tests for src.ai.text_extractor
"""
import os
import tempfile
import pytest

from src.ai.text_extractor import extract_text_from_file


class TestExtractTextFromFile:
    """Tests for the text extraction utility."""

    def test_extract_plain_text(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("Hello world\nLine two")
        result = extract_text_from_file(str(f))
        assert "Hello world" in result
        assert "Line two" in result

    def test_extract_csv(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("name,age\nAlice,30\nBob,25")
        result = extract_text_from_file(str(f))
        assert "Alice" in result
        assert "30" in result

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "binary.xyz"
        f.write_bytes(b"\x00\x01\x02")
        result = extract_text_from_file(str(f))
        # Should return a fallback message, not crash
        assert isinstance(result, str)

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = extract_text_from_file(str(f))
        assert isinstance(result, str)

    def test_explicit_mime_type(self, tmp_path):
        f = tmp_path / "no_ext"
        f.write_text("plain text content")
        result = extract_text_from_file(str(f), mime_type="text/plain")
        assert "plain text content" in result

    def test_missing_file_returns_error(self):
        result = extract_text_from_file("/nonexistent/path.txt")
        assert isinstance(result, str)  # Should not raise
