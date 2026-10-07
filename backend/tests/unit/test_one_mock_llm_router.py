"""TS-13: the test suite has one LLM double.

Two ``MockLLMRouter`` classes with different interfaces used to exist
(``tests/harness/mock_llm.py`` and ``tests/fixtures/llm_fixture.py``); which
one a test got depended on its conftest.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]


def test_mock_llm_router_is_defined_once() -> None:
    defs = [
        path.relative_to(TESTS).as_posix()
        for path in TESTS.rglob("*.py")
        if re.search(r"^class MockLLMRouter\b", path.read_text(encoding="utf-8"), re.M)
    ]
    assert defs == ["harness/mock_llm.py"]
