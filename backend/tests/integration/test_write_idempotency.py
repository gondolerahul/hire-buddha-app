"""A write happens once per run (P6.5 — TL-39).

No write tool carried an idempotency key, so a retried, re-planned or resumed
step re-posted, re-sent and re-created; ``tool_interaction_logs.idempotency_key``
was never written. Now a call that writes is keyed by its run, tool and
arguments, and the run's earlier successful call with that key answers it.
Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict

import pytest

from src.ai.governance.idempotency import write_key
from src.ai.governance.tool_access import _calls_so_far
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.orm.execution import ToolInteractionLog
from src.ai.step_executor import log_tool_call
from src.ai.tool_executor import ToolExecutor
from src.ai.tools.base import Tool, ToolOutput, ToolParams

pytestmark = pytest.mark.needs_db


@pytest.fixture(autouse=True)
def _writes_run_now(monkeypatch):
    """These tests are about replaying a write (TL-39), not about holding it for
    a person (SH-E4, connector_actions): the approval rule is off here."""
    from src.common.config import settings

    monkeypatch.setattr(settings, "CONNECTOR_ACTION_APPROVAL", False)


def test_only_a_write_in_a_run_has_a_key():
    run = uuid.uuid4()
    assert write_key(run, "web_search", {"query": "x"}) is None
    assert write_key(run, "social_api", {"platform": "twitter", "operation": "describe"}) is None
    assert write_key(run, "social_api", {"platform": "twitter", "operation": "search"}) is None
    assert write_key(None, "email_send", {"to": "a"}) is None
    post = write_key(run, "social_api", {"platform": "twitter", "operation": "create_post", "payload": {"text": "hi"}})
    assert post and post == write_key(run, "social_api", {"payload": {"text": "hi"}, "operation": "create_post",
                                                          "platform": "twitter"})        # order does not matter
    assert post != write_key(run, "social_api", {"platform": "twitter", "operation": "create_post",
                                                 "payload": {"text": "hello"}})
    assert post != write_key(uuid.uuid4(), "social_api", {"platform": "twitter", "operation": "create_post",
                                                          "payload": {"text": "hi"}})     # another run


class _SendParams(ToolParams):
    to: str
    body: str


class _Send(Tool):
    name = "email_send"            # a write (resilience.WRITE_TOOLS)
    description = "sends"
    Params = _SendParams

    def __init__(self):
        object.__setattr__(self, "sent", [])

    async def execute(self, params: Any, ctx: Dict[str, Any]) -> ToolOutput:
        self.sent.append(params.to)
        return ToolOutput(output=f"sent to {params.to}")


class _Access:
    def __init__(self, tool):
        self.tool, self.recorded = tool, []

    def resolve(self, name, via):
        return self.tool

    def timeout_for(self, name, tool):
        return tool.timeout_seconds

    def record(self, name):
        self.recorded.append(name)


@pytest.fixture
async def run(db, monkeypatch):
    import src.common.database as database

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(database, "AsyncSessionLocal", _session)

    from src.auth.models import Company
    c = Company(name=f"p65-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="ACTION", status="ACTIVE", name="sender")
    db.add(ent)
    await db.flush()
    r = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={})
    db.add(r)
    await db.flush()
    return r


async def _call(db, run, tool, access, args):
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "email_send", "args": args}], {"company_id": str(run.company_id), "run_id": str(run.id)},
        access=access)
    log_tool_call(db, run.id, "send", access, tr, args, tr.latency_ms)
    await db.flush()
    return tr


@pytest.mark.asyncio
async def test_the_same_write_twice_in_a_run_writes_once(db, run):
    tool = _Send()
    access = _Access(tool)
    first = await _call(db, run, tool, access, {"to": "a@b.c", "body": "hi"})
    again = await _call(db, run, tool, access, {"to": "a@b.c", "body": "hi"})
    assert tool.sent == ["a@b.c"]
    assert (first.replayed, again.replayed, again.output, again.units) == (False, True, "sent to a@b.c", 0)
    assert first.idempotency_key == again.idempotency_key
    assert access.recorded == ["email_send"]                          # a replay is not a call
    assert (await _calls_so_far(db, run.id)) == {"email_send": 1}


@pytest.mark.asyncio
async def test_a_different_write_or_a_failed_one_is_not_replayed(db, run):
    tool = _Send()
    access = _Access(tool)
    await _call(db, run, tool, access, {"to": "a@b.c", "body": "hi"})
    await _call(db, run, tool, access, {"to": "x@y.z", "body": "hi"})
    db.add(ToolInteractionLog(run_id=run.id, tool_id="email_send", tool_name="email_send", success=False,
                              output_result="Error: down",
                              idempotency_key=write_key(run.id, "email_send", {"to": "q@r.s", "body": "hi"})))
    await db.flush()
    await _call(db, run, tool, access, {"to": "q@r.s", "body": "hi"})
    assert tool.sent == ["a@b.c", "x@y.z", "q@r.s"]
