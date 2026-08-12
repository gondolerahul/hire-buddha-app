"""Introspection meta-tools — Phase 12 `06` §3.1.

Covers agent_introspect (read-only state snapshot from the materialised
context) and agent_reflect (run-scoped + candidate persistence), plus the
meta-cognition matrix defaults that gate their auto-injection. DB writes are
best-effort and exercised only via the run-scoped path here.
"""
from __future__ import annotations

import json

import pytest

from src.ai.meta.platform_schema_compiler import resolve_meta_cognition
from src.ai.tools.meta.agent_introspect import AgentIntrospectTool
from src.ai.tools.meta.agent_reflect import AgentReflectTool


# --------------------------------------------------------------------------- #
# agent_introspect
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_introspect_reads_agent_state() -> None:
    ctx = {
        "__agent_state__": {
            "iteration": 3,
            "budget_pressure": 0.42,
            "open_subgoals": ["find sources", "summarise"],
        },
        "__intelligence__": [{"rule": "prefer cheap tools"}],
        "__cortex_cursor__": "node-123",
    }
    out = json.loads(await AgentIntrospectTool().run_with_context("{}", ctx))
    assert out["iteration"] == 3
    assert out["budget_pressure"] == 0.42
    assert out["open_subgoals"] == ["find sources", "summarise"]
    assert out["applicable_rules"] == [{"rule": "prefer cheap tools"}]
    assert out["viewport_cursor"] == "node-123"
    assert "recent_failures" not in out  # not requested


@pytest.mark.asyncio
async def test_introspect_falls_back_to_execution_metadata() -> None:
    ctx = {"__execution_metadata__": {"iteration": 7, "budget_pressure": 0.9}}
    out = json.loads(await AgentIntrospectTool().run_with_context("{}", ctx))
    assert out["iteration"] == 7
    assert out["budget_pressure"] == 0.9


@pytest.mark.asyncio
async def test_introspect_empty_context_is_safe() -> None:
    out = json.loads(await AgentIntrospectTool().run_with_context("", None))
    assert out["applicable_rules"] == []


@pytest.mark.asyncio
async def test_introspect_failures_noop_without_entity() -> None:
    # include_failures requested but no entity_id → empty list, no DB touch.
    out = json.loads(
        await AgentIntrospectTool().run_with_context(
            json.dumps({"include_failures": True}), {}
        )
    )
    assert out["recent_failures"] == []


# --------------------------------------------------------------------------- #
# agent_reflect
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reflect_persists_run_scoped() -> None:
    ctx: dict = {}
    out = json.loads(
        await AgentReflectTool().run_with_context(
            json.dumps({"learning": "batch the searches", "kind": "strategy", "confidence": 0.8}),
            ctx,
        )
    )
    assert out["reflected"] is True
    assert out["kind"] == "strategy"
    assert out["confidence"] == 0.8
    assert out["persisted_run_scoped"] is True
    # The reflection is readable by later steps in the same run.
    assert ctx["__reflections__"][0]["learning"] == "batch the searches"
    # No CORTEX tree in context → candidate write is skipped, not failed.
    assert out["persisted_candidate"] is False


@pytest.mark.asyncio
async def test_reflect_requires_learning() -> None:
    out = json.loads(await AgentReflectTool().run_with_context(json.dumps({"kind": "strategy"}), {}))
    assert "error" in out


@pytest.mark.asyncio
async def test_reflect_normalises_kind_and_confidence() -> None:
    out = json.loads(
        await AgentReflectTool().run_with_context(
            json.dumps({"learning": "x", "kind": "bogus", "confidence": 5}), {}
        )
    )
    assert out["kind"] == "observation"  # unknown kind → observation
    assert out["confidence"] == 1.0  # clamped into [0, 1]


# --------------------------------------------------------------------------- #
# meta-cognition matrix defaults (§1)
# --------------------------------------------------------------------------- #
class _Entity:
    def __init__(self, etype: str, caps=None, meta_ext=None) -> None:
        self.type = etype
        self.capabilities = caps or {}
        self.planning = {}
        self.logic_gate = {}
        self.metadata_extensions = meta_ext or {}


@pytest.mark.parametrize(
    "etype,introspect,reflect",
    [
        ("ACTION", False, False),
        ("SKILL", True, False),
        ("AGENT", True, True),
        ("PROCESS", True, True),
    ],
)
def test_matrix_defaults(etype: str, introspect: bool, reflect: bool) -> None:
    cfg = resolve_meta_cognition(_Entity(etype))
    assert cfg["self_introspection"] is introspect
    assert cfg["reflection"] is reflect


def test_matrix_explicit_override() -> None:
    ent = _Entity("ACTION", caps={"meta_cognition": {"self_introspection": True}})
    cfg = resolve_meta_cognition(ent)
    assert cfg["self_introspection"] is True  # explicit wins over the type default
