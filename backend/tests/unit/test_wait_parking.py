"""A run that calls ``wait_for_event`` parks WAITING_ON_EVENT and resumes with
the event as the waiting step's result (Phase 14 WS3, tech spec §7.9).

The loop's side, with the fakes of ``test_approval_pause.py``: the waits
table, the router and the scheduler are in
tests/integration/test_automation_waits.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.events import capture_test_events
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.schemas.enums import RunStatus
from src.automation import waits

from tests.unit.test_agent_loop_billing_and_fallback import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401


def _entity(tools=("wait_for_event",)):
    return SimpleNamespace(
        id=uuid.uuid4(), company_id=uuid.uuid4(), name="sales", type="SKILL",
        goal="Ask, wait for the reply, follow up", description="fake", identity=None, hierarchy=None,
        logic_gate=None,
        planning={"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "order": 1, "name": "Ask and wait", "type": "ACTION", "required": True},
            {"step_id": "s2", "order": 2, "name": "Follow up", "type": "ACTION", "required": True},
        ]}, "dynamic_planning": {"enabled": False}},
        capabilities={"tools": [{"tool_id": t} for t in tools]},
        governance={"max_cost_usd": 5.0, "timeout_ms": 600_000},
        io_contract=None, observability=None, metadata_extensions=None,
    )


class _Record:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.seen_by_s2: list[str] = []
        self.asked = False      # s1 ran: the tool wrote its wait
        self.waiting = True


class _Asks:
    """s1 asks and calls wait_for_event; s2 reads what s1 ended with. Registered
    as both executors a two-step plan may go to, sharing one record."""

    def __init__(self, name, record):
        self.name, self.record = name, record

    async def execute(self, move, state, db):  # noqa: ARG002
        ids = [str(s["step_id"]) for s in move.plan_fragment]
        self.record.calls.append(ids)
        if "s1" in ids:
            self.record.asked = True
            return ActionResult(success=True, output="asked; waiting", cost_usd=Decimal("0"),
                                completed_step_ids=["s1"])
        self.record.seen_by_s2.append(str(state.context_state.get("s1")))
        return ActionResult(success=True, output="followed up", cost_usd=Decimal("0"), completed_step_ids=ids)


@pytest.fixture
def waiting(monkeypatch):
    executor = _Record()
    originals = {name: EXECUTOR_REGISTRY.get(name) for name in ("SingleStep", "DAG")}
    for name in originals:
        register_executor(_Asks(name, executor))
    bills: list = []
    wait = SimpleNamespace(id=uuid.uuid4(), event_type="email.received",
                           deadline_at=datetime.utcnow() + timedelta(hours=48))

    async def _pending(db, run_id):  # noqa: ARG001
        return wait if executor.asked and executor.waiting else None

    async def _settle(self, run, entity_name):  # noqa: ARG001
        bills.append(run.id)
        return Decimal("0")

    from src.ai.governance.governance_service import GovernanceService
    monkeypatch.setattr(waits, "pending_for_run", _pending)
    monkeypatch.setattr(GovernanceService, "settle_billing", _settle)
    run = _FakeRun(_entity())
    yield SimpleNamespace(run=run, db=_FakeDB(run), executor=executor, bills=bills, wait=wait)
    for original in originals.values():
        if original is not None:
            register_executor(original)


def _loop(db):
    return AgentLoop(db=db, redis=None, critic_pipeline=NoOpCriticPipeline(), max_iterations=10,
                     feature_flags=FeatureFlags(db=None))


@pytest.mark.asyncio
async def test_the_run_parks_waiting_on_event_and_is_not_finished(waiting):
    with capture_test_events() as events:
        outcome = await _loop(waiting.db).run(waiting.run.id)

    assert outcome["status"] == RunStatus.WAITING_ON_EVENT.value == waiting.run.status, (outcome, waiting.executor.calls)
    snapshot = waiting.run.context_state["__agent_state_snapshot__"]
    assert snapshot["awaiting_event"]["wait_id"] == str(waiting.wait.id)
    assert snapshot["awaiting_event"]["step_id"] == "s1"
    assert "s1" in snapshot["completed_step_ids"]            # the asking step is not run again
    assert waiting.executor.calls == [["s1", "s2"]] or waiting.executor.calls == [["s1"]]
    assert waiting.bills == []                                # not settled while it waits
    assert "agent.loop.waiting_on_event" in [e.name for e in events]


async def _resume(waiting, monkeypatch, outcome):
    async def _outcome(db, marker):  # noqa: ARG001
        return outcome

    async def _claim(db, run_id):  # noqa: ARG001
        waiting.run.status = RunStatus.RUNNING.value
        return True

    waiting.executor.waiting = False
    monkeypatch.setattr(waits, "outcome_for", _outcome)
    monkeypatch.setattr(waits, "claim_run", _claim)
    return await _loop(waiting.db).resume_after_wait(waiting.run.id)


@pytest.mark.asyncio
async def test_the_event_becomes_the_waiting_steps_result(waiting, monkeypatch):
    await _loop(waiting.db).run(waiting.run.id)
    text = 'The event you waited for arrived: {"type": "email.received", "data": {"body": "yes"}}'
    outcome = await _resume(waiting, monkeypatch, {"status": "satisfied", "text": text})

    assert outcome["status"] == RunStatus.COMPLETED.value, (outcome, waiting.executor.calls)
    assert waiting.executor.seen_by_s2 == [text]             # the next step sees the event
    assert ["s1"] not in waiting.executor.calls[1:]          # s1 was not dispatched again
    assert waiting.bills == [waiting.run.id]                 # billed once, at the end


@pytest.mark.asyncio
async def test_a_timeout_also_resumes_with_a_notice(waiting, monkeypatch):
    await _loop(waiting.db).run(waiting.run.id)
    outcome = await _resume(waiting, monkeypatch, {"status": "expired", "text": "No email.received event arrived"})
    assert outcome["status"] == RunStatus.COMPLETED.value, (outcome, waiting.executor.calls)
    assert waiting.executor.seen_by_s2 == ["No email.received event arrived"]


@pytest.mark.asyncio
async def test_a_resume_while_the_wait_is_open_does_nothing(waiting, monkeypatch):
    await _loop(waiting.db).run(waiting.run.id)

    async def _open(db, marker):  # noqa: ARG001
        return None

    monkeypatch.setattr(waits, "outcome_for", _open)
    outcome = await _loop(waiting.db).resume_after_wait(waiting.run.id)
    assert outcome == {"run_id": str(waiting.run.id), "status": "WAITING_ON_EVENT", "resumed": False}


def test_only_an_agent_granted_the_tool_is_checked_for_waits():
    assert waits.may_wait(_entity())
    assert not waits.may_wait(_entity(tools=("web_search",)))
    assert not waits.may_wait(None)
