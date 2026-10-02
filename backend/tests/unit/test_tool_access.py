"""One resolution point decides whether a tool may run (P3.1).

TL-50 — the model could call any registered tool, not only the entity's.
TL-10 — tenant tools were unreachable (no company in the lookup).
TL-12 / TX-03 — ``usage: PLANNED`` hid a tool from the model but it still ran.
TL-13 — the EXPERIMENTAL/DRAFT opt-in was not on the execution path.
TL-14 — ``is_enabled = false`` disabled nothing.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.schemas.capabilities import Capabilities, ToolGrant
from src.ai.schemas.strict_keys import unknown_keys
from src.ai.tool_executor import ToolExecutor
from src.ai.governance.tool_access import ToolAccess, ToolDenied
from src.ai.tools.base import Tool, ToolRegistry, ToolStatus
from src.ai.tools.resilience import ToolResilience


class _Spy(Tool):
    description = "spy"

    def __init__(self, name: str, output: str = "ok", status: ToolStatus = ToolStatus.ACTIVE):
        self.name = name
        self.status = status
        # A registered tool is frozen (TX-02): the spy's state lives in a dict.
        self.state = {"output": output, "calls": 0}

    @property
    def calls(self) -> int:
        return self.state["calls"]

    async def run(self, input_data: str) -> str:
        self.state["calls"] += 1
        return self.state["output"]


@pytest.fixture
def spies():
    made = {
        "granted": _Spy("p31_granted"),
        "other": _Spy("p31_other"),
        "planned": _Spy("p31_planned"),
        "fallback": _Spy("p31_fallback"),
        "exp": _Spy("p31_exp", status=ToolStatus.EXPERIMENTAL),
    }
    for t in made.values():
        ToolRegistry.register(t)
    yield made
    for t in made.values():
        ToolRegistry._tools.pop(t.name, None)


def _entity(*grants, etype: str = "ACTION", meta: dict | None = None):
    return SimpleNamespace(
        name="probe", type=etype,
        capabilities={"tools": list(grants), "meta_cognition": meta or {}},
        planning={}, logic_gate={}, metadata_extensions={},
    )


def _flags(on: bool = False):
    flags = AsyncMock()
    flags.is_on = AsyncMock(return_value=on)
    return flags


async def _access(*grants, company=None, flags_on=False, db=None, **kw) -> ToolAccess:
    return await ToolAccess.load(db, company or uuid4(), _entity(*grants, **kw),
                                 feature_flags=_flags(flags_on))


# ── TL-50: execution, not only advertisement, is limited to the grants ──────


@pytest.mark.asyncio
async def test_the_model_cannot_call_a_tool_the_entity_was_not_granted(spies):
    access = await _access({"tool_id": "p31_granted"})
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p31_other", "args": {"input": "x"}}], access=access,
    )
    assert spies["other"].calls == 0
    assert tr.success is False and tr.skipped is True
    assert "not granted" in tr.output


@pytest.mark.asyncio
async def test_a_refusal_names_the_entitys_tools_not_the_catalogue(spies):
    access = await _access({"tool_id": "p31_granted"})
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "email_send", "args": {}}], access=access,
    )
    assert "p31_granted" in tr.output
    assert "web_search" not in tr.output and "sandbox_code" not in tr.output


@pytest.mark.asyncio
async def test_a_granted_tool_runs(spies):
    access = await _access({"tool_id": "p31_granted"})
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p31_granted", "args": {"input": "x"}}], access=access,
    )
    assert tr.success is True and spies["granted"].calls == 1


@pytest.mark.asyncio
async def test_a_plan_step_cannot_run_an_ungranted_tool(spies):
    access = await _access({"tool_id": "p31_granted"})
    [tr] = await ToolExecutor.execute_tools([{"tool": "p31_other", "input": "x"}], access=access)
    assert spies["other"].calls == 0 and tr.skipped is True


def test_there_is_no_entry_point_without_access():
    import inspect
    for fn in (ToolExecutor.execute_from_function_calls, ToolExecutor.execute_tools):
        param = inspect.signature(fn).parameters["access"]
        assert param.default is inspect.Parameter.empty
    assert not hasattr(ToolExecutor, "get_tool_schemas")


@pytest.mark.asyncio
async def test_the_platform_meta_tools_are_granted_by_level():
    """The meta-cognition tools the platform injects resolve without a grant."""
    access = await _access(etype="AGENT")
    assert {"agent_introspect", "agent_reflect"} <= set(access.llm_tool_ids())
    assert not isinstance(access.resolve("agent_introspect"), ToolDenied)
    assert isinstance(access.resolve("meta_entity_creator"), ToolDenied)


# ── TL-12 / TX-03: "planned" means the model may not call it ────────────────


@pytest.mark.asyncio
async def test_a_planned_tool_is_neither_offered_to_nor_callable_by_the_model(spies):
    access = await _access({"tool_id": "p31_planned", "usage": "PLANNED"})
    assert access.schemas() == []
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p31_planned", "args": {"input": "x"}}], access=access,
    )
    assert spies["planned"].calls == 0 and "plan step" in tr.output
    [tr] = await ToolExecutor.execute_tools([{"tool": "p31_planned", "input": "x"}], access=access)
    assert tr.success is True and spies["planned"].calls == 1


def test_the_builders_usage_is_stored_as_the_grant():
    caps = Capabilities.model_validate({"tools": [
        {"tool_id": "a", "usage": "PLANNED"}, {"tool_id": "b", "usage": "AUTONOMOUS"},
        {"tool_id": "c", "rate_limit_per_run": 3},
    ]}).model_dump()
    assert caps["tools"] == [
        {"tool_id": "a", "llm_callable": False, "plan_callable": True, "rate_limit_per_run": None, "timeout_seconds": None},
        {"tool_id": "b", "llm_callable": True, "plan_callable": True, "rate_limit_per_run": None, "timeout_seconds": None},
        {"tool_id": "c", "llm_callable": True, "plan_callable": True, "rate_limit_per_run": 3, "timeout_seconds": None},
    ]
    assert unknown_keys(Capabilities, {"tools": [{"tool_id": "a", "usage": "BOTH"}]}) == []
    assert unknown_keys(Capabilities, {"tools": [{"tool_id": "a", "uasge": "BOTH"}]}) == ["tools[0].uasge"]
    assert ToolGrant.model_validate("plain_id").tool_id == "plain_id"


# ── TL-10: a company's own tools resolve for that company only ──────────────


@pytest.mark.asyncio
async def test_a_tenant_tool_resolves_for_its_company_and_no_other():
    mine, theirs = uuid4(), uuid4()
    tool = _Spy("p31_tenant_only")
    ToolRegistry.register_tenant_tool(mine, tool)
    try:
        for_mine = await _access({"tool_id": "p31_tenant_only"}, company=mine)
        for_theirs = await _access({"tool_id": "p31_tenant_only"}, company=theirs)
        assert for_mine.resolve("p31_tenant_only") is tool
        assert [s["name"] for s in for_mine.schemas()] == ["p31_tenant_only"]
        denied = for_theirs.resolve("p31_tenant_only")
        assert isinstance(denied, ToolDenied) and denied.reason == "not_registered"
    finally:
        ToolRegistry._tenant_tools.pop(str(mine), None)


# ── TL-13: the opt-in is on the execution path ──────────────────────────────


@pytest.mark.asyncio
async def test_an_experimental_tool_needs_the_companys_opt_in_to_run(spies):
    off = await _access({"tool_id": "p31_exp"})
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p31_exp", "args": {"input": "x"}}], access=off,
    )
    assert spies["exp"].calls == 0 and "tools.experimental.p31_exp" in tr.output
    on = await _access({"tool_id": "p31_exp"}, flags_on=True)
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p31_exp", "args": {"input": "x"}}], access=on,
    )
    assert tr.success is True and spies["exp"].calls == 1


# ── TL-14: the admin kill switch disables the tool ──────────────────────────


@pytest.mark.asyncio
async def test_a_tool_switched_off_by_an_admin_does_not_run(spies):
    db = MagicMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = ["p31_granted"]
    db.execute = AsyncMock(return_value=rows)
    access = await _access({"tool_id": "p31_granted"}, db=db)
    assert access.schemas() == []
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p31_granted", "args": {"input": "x"}}], access=access,
    )
    assert spies["granted"].calls == 0 and "switched off" in tr.output
    sql = str(db.execute.await_args.args[0])
    assert "is_enabled IS false" in sql and "company_id IS NULL" in sql


# ── Resilience: a fallback resolves like any call; a refusal is not healed ──


@pytest.mark.asyncio
async def test_a_fallback_the_entity_was_not_granted_does_not_run(spies):
    spies["granted"].state["output"] = "Error: upstream exploded"
    access = await _access({"tool_id": "p31_granted"})
    reformat = AsyncMock(return_value=None)
    res = ToolResilience(reformat_fn=reformat, access=access,
                         fallback_table=lambda *_a: ("p31_fallback", "x"))
    tr = await res.run(tool_id="p31_granted", raw_input="x")
    assert spies["fallback"].calls == 0
    assert tr.success is False


@pytest.mark.asyncio
async def test_a_granted_fallback_runs(spies):
    spies["granted"].state["output"] = "Error: upstream exploded"
    access = await _access({"tool_id": "p31_granted"}, {"tool_id": "p31_fallback"})
    res = ToolResilience(reformat_fn=AsyncMock(return_value=None), access=access,
                         fallback_table=lambda *_a: ("p31_fallback", "x"))
    tr = await res.run(tool_id="p31_granted", raw_input="x")
    assert spies["fallback"].calls == 1 and tr.success is True


@pytest.mark.asyncio
async def test_a_refused_call_is_not_retried_or_rerouted(spies):
    access = await _access({"tool_id": "p31_granted"})
    reformat = AsyncMock(return_value='{"input": "y"}')
    res = ToolResilience(reformat_fn=reformat, access=access,
                         fallback_table=lambda *_a: ("p31_granted", "x"))
    tr = await res.run_function_call(function_call={"name": "p31_other", "args": {"input": "x"}})
    assert tr.skipped is True
    reformat.assert_not_awaited()
    assert spies["granted"].calls == 0 and spies["other"].calls == 0
