"""tests/chaos/conftest.py — shared helpers for chaos cases.

Each chaos case follows the same template:

  1. Set up a baseline that should work.
  2. Inject a fault (DB unreachable, tool 500, missing table, …).
  3. Assert the system DEGRADES gracefully — emits a structured event,
     does not crash, returns a defined error envelope.

Chaos cases all carry ``@pytest.mark.chaos`` so the default PR-fast
lane skips them; nightly runs them with ``pytest -m chaos``.
"""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test under tests/chaos as @pytest.mark.chaos so a
    contributor doesn't have to remember to add the decorator."""
    for item in items:
        if "tests/chaos" in str(item.fspath):
            item.add_marker(pytest.mark.chaos)
