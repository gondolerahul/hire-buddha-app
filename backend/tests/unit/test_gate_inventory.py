"""Every gate says when it could not decide, and an open one says why (GH-21, GH-03).

Almost every control failed open, silently: a gate that could not evaluate and
a gate that passed looked the same. ``src/common/gates.py`` lists each gate and
what it does when it cannot decide; each failure path calls ``gate_failed``,
which emits ``gate.failed``. This test holds the list and the code together.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.ai.core.events import capture_test_events
from src.ai.governance.rate_limiter import RedisRateLimiter
from src.common.gates import GATES

SRC = Path(__file__).resolve().parents[2] / "src"
CALL = re.compile(r"""gate_failed\(\s*["']([a-z_]+)["']""")


def _calls() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for py in SRC.rglob("*.py"):
        for name in CALL.findall(py.read_text(encoding="utf-8")):
            found.setdefault(name, []).append(str(py.relative_to(SRC)))
    return found


def test_every_gate_failure_names_a_listed_gate_and_every_listed_gate_has_one():
    calls = _calls()
    assert set(calls) <= set(GATES), f"unlisted gates: {sorted(set(calls) - set(GATES))}"
    assert set(GATES) <= set(calls), f"listed gates nothing reports: {sorted(set(GATES) - set(calls))}"


def test_a_gate_that_fails_open_says_why():
    for name, gate in GATES.items():
        assert gate.fails in ("closed", "open"), name
        assert gate.what.strip(), name
        if gate.fails == "open":
            assert gate.why_open.strip(), f"{name} fails open without saying why"


# ── the rate limiter fails closed by default (GH-03) ────────────────────────


class _DeadPipeline:
    def __getattr__(self, _name):
        return lambda *a, **k: None

    async def execute(self):
        raise ConnectionError("redis unreachable")


class _DeadRedis:
    def pipeline(self):
        return _DeadPipeline()


@pytest.mark.asyncio
@pytest.mark.parametrize("redis", [None, _DeadRedis()])
async def test_the_rate_limiter_refuses_when_it_cannot_count(redis):
    with capture_test_events() as events:
        allowed = await RedisRateLimiter(redis).check_and_consume("runs:company_1", limit=5, window_seconds=60)
    assert allowed is False
    [failed] = [e for e in events if e.name == "gate.failed"]
    assert failed.payload["gate"] == "rate_limiter" and failed.payload["decision"] == "closed"


@pytest.mark.asyncio
async def test_a_caller_that_chooses_to_fail_open_is_recorded_as_open():
    with capture_test_events() as events:
        assert await RedisRateLimiter(None).check_and_consume("k", 1, 60, fail_open=True) is True
    [failed] = [e for e in events if e.name == "gate.failed"]
    assert failed.payload["decision"] == "open"
