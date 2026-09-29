"""A HITL approval must show the reviewer what they are approving (PO-05).

The approval row's ``context_snapshot`` used to hold only the step name and a
message. It now carries what the step is about to do — its resolved prompt, its
tool, the run's input — and, for AFTER_STEP checkpoints, what the step produced.
The pending-approvals list returns it so the panel can render it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.ai.governance.governance_service import GovernanceService
from src.ai.governance.hitl_snapshot import MAX_FIELD_CHARS
from src.ai.schemas import PlanStep


class _FakePubSub:
    async def subscribe(self, *_):
        pass

    async def unsubscribe(self, *_):
        pass

    async def get_message(self, **_):
        return None

    async def aclose(self):
        pass


class _FakeRedis:
    def pubsub(self):
        return _FakePubSub()

    async def publish(self, *_):
        pass


class _FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = obj.id or uuid.uuid4()

    async def execute(self, stmt):
        # The wait re-reads the row (still PENDING) and, at the deadline,
        # conditionally marks it — one row updated.
        return SimpleNamespace(scalar_one_or_none=lambda: "PENDING", rowcount=1)


def _checkpoint(trigger_type: str, **extra) -> dict:
    # A 1 ms window with auto-approve: the wait loop ends at once and the run goes on.
    return {"trigger_type": trigger_type, "step_ref": "Draft email", "timeout_ms": 1,
            "auto_approve_on_timeout": True, **extra}


def _step() -> PlanStep:
    return PlanStep(
        step_id="step_2", name="Draft email", type="TOOL_CALL",
        description="Write the outreach email",
        target={"tool_id": "email_send", "prompt_template": "Email {{lead}} about {{topic}}"},
    )


async def _fire(checkpoint: dict, phase: str, step_result=None) -> dict:
    db = _FakeDB()
    svc = GovernanceService(db, _FakeRedis())
    run = SimpleNamespace(id=uuid.uuid4(), total_cost_usd=0.42)
    entity = SimpleNamespace(name="outreach-agent", display_name="Outreach Agent", governance={})
    context = {"input": "Reach out to Acme", "lead": "jane@acme.test", "topic": "renewal"}
    await svc.evaluate_hitl(run, entity, _step(), context, phase,
                            governance_dict={"hitl_checkpoints": [checkpoint]},
                            step_result=step_result)
    assert len(db.added) == 1, "the checkpoint should have fired"
    return db.added[0].context_snapshot


@pytest.mark.asyncio
async def test_before_step_snapshot_shows_what_the_step_will_do():
    snap = await _fire(_checkpoint("BEFORE_STEP", message="Check the email first"), "BEFORE")
    assert snap["message"] == "Check the email first"
    assert snap["entity_name"] == "Outreach Agent"
    assert snap["step_name"] == "Draft email"
    assert snap["tool_id"] == "email_send"
    assert snap["step_prompt"] == "Email jane@acme.test about renewal"  # resolved, not the template
    assert snap["run_input"] == "Reach out to Acme"
    assert snap["phase"] == "BEFORE"
    assert "step_output" not in snap
    assert "step_id" not in snap  # plan topology stays out


@pytest.mark.asyncio
async def test_after_step_snapshot_shows_what_the_step_produced():
    snap = await _fire(_checkpoint("AFTER_STEP"), "AFTER",
                       step_result={"output": "Hi Jane, your renewal is due."})
    assert snap["step_output"] == "Hi Jane, your renewal is due."
    assert snap["phase"] == "AFTER"


@pytest.mark.asyncio
async def test_cost_threshold_snapshot_carries_the_cost():
    snap = await _fire({"trigger_type": "COST_THRESHOLD", "threshold": 0.4, "timeout_ms": 1,
                        "auto_approve_on_timeout": True}, "BEFORE")
    assert snap["run_cost_usd"] == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_large_output_is_clipped():
    snap = await _fire(_checkpoint("AFTER_STEP"), "AFTER", step_result={"output": "x" * 10_000})
    assert snap["step_output"].startswith("x" * MAX_FIELD_CHARS)
    assert snap["step_output"].endswith("[6000 more characters]")


@pytest.mark.asyncio
async def test_pending_list_returns_the_snapshot(monkeypatch):
    from src.ai import router as ai_router_module
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    approval = SimpleNamespace(
        id=uuid.uuid4(), run_id=uuid.uuid4(), checkpoint_trigger="BEFORE_STEP: Draft email",
        status="PENDING", requested_at=datetime(2026, 9, 29, 12, 0), timeout_ms=300000,
        context_snapshot={"step_name": "Draft email", "step_prompt": "Email jane"},
    )

    async def fake_pending(self, company_id):
        return [approval]

    monkeypatch.setattr(ai_router_module.AIService, "get_pending_approvals", fake_pending)
    app = FastAPI()
    app.include_router(ai_router_module.router, prefix="/api/v1")

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role="tenant_user", company_id=uuid.uuid4())

    async def _db():
        yield None

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get("/api/v1/ai/approvals/pending")
    assert res.status_code == 200
    row = res.json()[0]
    assert row["context_snapshot"] == {"step_name": "Draft email", "step_prompt": "Email jane"}
    assert row["timeout_ms"] == 300000
