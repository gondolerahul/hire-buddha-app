"""tests/chaos/conftest.py — shared helpers for chaos cases.

Each chaos case follows the same template:

  1. Set up a baseline that should work.
  2. Inject a fault (DB unreachable, tool 500, missing table, …).
  3. Assert the system DEGRADES gracefully — emits a structured event,
     does not crash, returns a defined error envelope.

Chaos cases all carry ``@pytest.mark.chaos`` (``tests/conftest.py`` marks every
test by its directory) so the default PR-fast lane skips them; nightly runs them
with ``pytest -m chaos``.
"""
