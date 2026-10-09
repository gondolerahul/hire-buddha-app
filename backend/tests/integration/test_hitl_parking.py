"""A HITL checkpoint parks the run; the decision resumes it (GH-07, PO-20, GH-25).

The checkpoint used to wait inside the step for up to its ``timeout_ms``,
holding a worker slot (and before GH-22, not waiting at all). Now it opens a
PENDING approval and raises ``HITLPending``; the run waits PAUSED, holding
nothing, and never goes ahead without an APPROVED decision. When the step is
dispatched again the checkpoint finds its approval and uses it once.

Real Postgres, rolled back. The loop's side, with fakes, is in
tests/unit/test_approval_pause.py.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.ai.core import approval_pause
from src.ai.core.exceptions import HITLPending, HITLRejected
from src.ai.schemas import PlanStep

pytestmark = pytest.mark.needs_db


class _Redis:
    async def publish(self, *_):
        pass

    async def xadd(self, *_, **__):
        pass

    async def expire(self, *_):
        pass


def _step():
    return PlanStep(step_id="s1", name="Send email", type="ACTION", target={"prompt_template": "Send it"})


async def _run(db, company_id, status="RUNNING"):
    from src.ai.orm.entity import HierarchicalEntity
    from src.ai.orm.execution import ExecutionRun

    entity = HierarchicalEntity(
        company_id=company_id, type="SKILL", name=f"gh07-{uuid.uuid4().hex[:6]}",
        planning={"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "order": 1, "name": "Send email", "type": "ACTION", "required": True}]}},
    )
    db.add(entity)
    await db.flush()
    run = ExecutionRun(company_id=company_id, entity_id=entity.id, input_data={"input": "x"}, status=status)
    db.add(run)
    await db.flush()
    return run, entity


async def _evaluate(db, run, *, timeout_ms=300000, auto=False):
    from src.ai.governance.governance_service import GovernanceService

    entity = SimpleNamespace(name="e", display_name="E", governance={})
    await GovernanceService(db, _Redis()).evaluate_hitl(
        run, entity, _step(), {"input": "x"}, "BEFORE", governance_dict={"hitl_checkpoints": [
            {"trigger_type": "BEFORE_STEP", "step_ref": "Send email",
             "timeout_ms": timeout_ms, "auto_approve_on_timeout": auto}]})


async def _approvals(db, run_id):
    return (await db.execute(text(
        "SELECT id, status, consumed_at FROM human_approvals WHERE run_id = :r ORDER BY requested_at"),
        {"r": str(run_id)})).all()


async def _decide(db, approval_id, status, notes=None):
    await db.execute(text("UPDATE human_approvals SET status = :s, reviewer_notes = :n WHERE id = :i"),
                     {"s": status, "n": notes, "i": str(approval_id)})


# ── the checkpoint ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_checkpoint_opens_an_approval_and_parks(db, test_company_id):
    run, _ = await _run(db, test_company_id)
    with pytest.raises(HITLPending) as parked:
        await _evaluate(db, run, timeout_ms=60000)
    [(approval_id, status, consumed)] = await _approvals(db, run.id)
    assert (status, consumed) == ("PENDING", None)
    marker = parked.value.marker()
    assert marker["approval_id"] == str(approval_id) and marker["step_id"] == "s1"
    assert marker["phase"] == "BEFORE" and marker["timeout_ms"] == 60000

    # Dispatched again before anyone decides: it parks on the same approval.
    with pytest.raises(HITLPending) as again:
        await _evaluate(db, run)
    assert again.value.approval_id == str(approval_id)
    assert len(await _approvals(db, run.id)) == 1


@pytest.mark.asyncio
async def test_a_redis_outage_does_not_skip_the_checkpoint(db, test_company_id):
    from src.ai.governance.governance_service import GovernanceService

    class _DeadRedis:
        async def xadd(self, *_, **__):
            raise ConnectionError("redis unreachable")

    run, _ = await _run(db, test_company_id)
    entity = SimpleNamespace(name="e", display_name="E", governance={})
    with pytest.raises(HITLPending):
        await GovernanceService(db, _DeadRedis()).evaluate_hitl(
            run, entity, _step(), {"input": "x"}, "BEFORE", governance_dict={"hitl_checkpoints": [
                {"trigger_type": "BEFORE_STEP", "step_ref": "Send email"}]})
    assert [r.status for r in await _approvals(db, run.id)] == ["PENDING"]


@pytest.mark.asyncio
async def test_an_approval_lets_the_step_run_once(db, test_company_id):
    run, _ = await _run(db, test_company_id)
    with pytest.raises(HITLPending) as parked:
        await _evaluate(db, run)
    await _decide(db, parked.value.approval_id, "APPROVED")

    await _evaluate(db, run)                                  # no raise: the step runs
    [(_, status, consumed)] = await _approvals(db, run.id)
    assert status == "APPROVED" and consumed is not None

    # The checkpoint fires again later (a retry): a person is asked again.
    with pytest.raises(HITLPending) as asked_again:
        await _evaluate(db, run)
    assert asked_again.value.approval_id != parked.value.approval_id
    assert [r.status for r in await _approvals(db, run.id)] == ["APPROVED", "PENDING"]


@pytest.mark.asyncio
async def test_a_rejection_raises_with_the_reviewers_notes(db, test_company_id):
    run, _ = await _run(db, test_company_id)
    with pytest.raises(HITLPending) as parked:
        await _evaluate(db, run)
    await _decide(db, parked.value.approval_id, "REJECTED", "  wrong customer ")
    with pytest.raises(HITLRejected, match="Execution blocked by human reviewer") as rejected:
        await _evaluate(db, run)
    assert rejected.value.reason.endswith("— wrong customer")
    assert (await _approvals(db, run.id))[0].consumed_at is not None


@pytest.mark.asyncio
async def test_ask_user_parks_then_returns_the_answer(db, test_company_id):
    from src.ai.governance.governance_service import GovernanceService

    run, _ = await _run(db, test_company_id)
    svc = GovernanceService(db, _Redis())
    with pytest.raises(HITLPending) as parked:
        await svc.ask_user(run, _step(), "which year?")
    await _decide(db, parked.value.approval_id, "APPROVED", "the 2025 figures")
    assert await svc.ask_user(run, _step(), "which year?") == "the 2025 figures"

    with pytest.raises(HITLPending) as asked:
        await svc.ask_user(run, _step(), "which month?")
    await _decide(db, asked.value.approval_id, "REJECTED")
    with pytest.raises(HITLRejected, match="declined"):
        await svc.ask_user(run, _step(), "which month?")


# ── the deadline ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("auto, expected", [(False, ("TIMEOUT", "")),
                                            (True, ("APPROVED", "Auto-approved on timeout"))])
async def test_past_the_deadline_a_pending_approval_is_settled(db, test_company_id, auto, expected):
    run, _ = await _run(db, test_company_id)
    with pytest.raises(HITLPending) as parked:
        await _evaluate(db, run, timeout_ms=1000, auto=auto)
    marker = parked.value.marker()
    assert await approval_pause.decision_for(db, marker, now=datetime.now(timezone.utc)) == ("PENDING", "")
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert await approval_pause.decision_for(db, marker, now=later) == expected


@pytest.mark.asyncio
async def test_a_decision_that_landed_first_wins_over_the_deadline(db, test_company_id):
    run, _ = await _run(db, test_company_id)
    with pytest.raises(HITLPending) as parked:
        await _evaluate(db, run, timeout_ms=1000)
    await _decide(db, parked.value.approval_id, "APPROVED", "ok")
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert await approval_pause.decision_for(db, parked.value.marker(), now=later) == ("APPROVED", "ok")


# ── resume ──────────────────────────────────────────────────────────────────


async def _parked_run(db, company_id, *, decision=None, notes=None, timeout_ms=300000, waited_s=0):
    """A run the loop parked on a BEFORE_STEP approval, as ``_persist_suspended`` leaves it."""
    from src.ai.core.agent_state import AgentState
    from src.ai.schemas.enums import EntityType

    run, entity = await _run(db, company_id)
    with pytest.raises(HITLPending) as parked:
        await _evaluate(db, run, timeout_ms=timeout_ms)
    if waited_s:
        await db.execute(text("UPDATE human_approvals SET requested_at = requested_at - make_interval(secs => :s) "
                              "WHERE id = :i"), {"s": waited_s, "i": parked.value.approval_id})
    if decision:
        await _decide(db, parked.value.approval_id, decision, notes)
    marker = parked.value.marker()
    if waited_s:
        marker["deadline"] = (datetime.fromisoformat(marker["deadline"]) - timedelta(seconds=waited_s)).isoformat()
    state = AgentState(run_id=run.id, entity_id=entity.id, company_id=company_id, entity_type=EntityType.SKILL)
    state.plan_steps = [{"step_id": "s1", "name": "Send email", "type": "ACTION", "required": True}]
    state.awaiting_approval = marker
    state.retry_queue = [{"plan_fragment": state.plan_steps, "executor": "SingleStep",
                          "strategy": "after_approval"}]
    since = datetime.now(timezone.utc) - timedelta(seconds=waited_s)
    await db.execute(text("UPDATE execution_runs SET status = 'PAUSED', context_state = CAST(:cs AS JSONB) "
                          "WHERE id = :i"),
                     {"cs": json.dumps({"__agent_state_snapshot__": state.snapshot(),
                                                      "__suspended_at__": since.isoformat()}),
                      "i": str(run.id)})
    return run, parked.value.approval_id


async def _row(db, run_id):
    return (await db.execute(text("SELECT status, error_message FROM execution_runs WHERE id = :i"),
                             {"i": str(run_id)})).one()


@pytest.fixture
def settled(monkeypatch):
    calls: list = []

    async def _settle(self, run):  # noqa: ANN001
        calls.append(run.id)

    from src.ai.core.credit_guard import CreditGuard
    monkeypatch.setattr(CreditGuard, "settle", _settle)
    return calls


@pytest.fixture
def enqueued(monkeypatch):
    calls: list = []

    async def _enqueue(function, *args, **kwargs):
        calls.append((function, args, kwargs))

    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    return calls


@pytest.mark.asyncio
async def test_a_rejected_run_resumes_to_cancelled_and_is_billed(db, test_company_id, settled, enqueued):
    from src.ai.core.agent_loop import AgentLoop

    run, approval_id = await _parked_run(db, test_company_id, decision="REJECTED", notes="wrong customer")
    outcome = await AgentLoop(db, None).resume_after_approval(run.id)
    assert outcome["status"] == "CANCELLED"
    status, error = await _row(db, run.id)
    assert status == "CANCELLED" and "wrong customer" in error
    assert settled == [run.id]
    assert (await _approvals(db, run.id))[0].consumed_at is not None
    # A late resume — the deadline job, the sweep — does nothing.
    assert (await AgentLoop(db, None).resume_after_approval(run.id))["resumed"] is False


@pytest.mark.asyncio
async def test_a_run_past_its_deadline_resumes_to_failed(db, test_company_id, settled, enqueued):
    from src.ai.core.agent_loop import AgentLoop

    run, approval_id = await _parked_run(db, test_company_id, timeout_ms=1000, waited_s=60)
    outcome = await AgentLoop(db, None).resume_after_approval(run.id)
    assert outcome["status"] == "FAILED"
    status, error = await _row(db, run.id)
    assert status == "FAILED" and "timed out" in error
    assert (await _approvals(db, run.id))[0].status == "TIMEOUT"


@pytest.mark.asyncio
async def test_a_pending_run_inside_its_deadline_stays_parked(db, test_company_id, settled, enqueued):
    from src.ai.core.agent_loop import AgentLoop

    run, _ = await _parked_run(db, test_company_id)
    assert (await AgentLoop(db, None).resume_after_approval(run.id))["resumed"] is False
    assert (await _row(db, run.id)).status == "PAUSED"
    assert settled == []


@pytest.mark.asyncio
async def test_only_one_resume_claims_the_run(db, test_company_id):
    run, _ = await _parked_run(db, test_company_id, decision="APPROVED")
    assert await approval_pause.claim(db, run.id) is True
    assert await approval_pause.claim(db, run.id) is False
    assert (await _row(db, run.id)).status == "RUNNING"


# ── the sweep and the endpoint ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_sweep_resumes_what_was_lost_and_nothing_else(db, test_company_id, enqueued):
    decided, _ = await _parked_run(db, test_company_id, decision="APPROVED", waited_s=600)
    expired, _ = await _parked_run(db, test_company_id, timeout_ms=1000, waited_s=600)
    waiting, _ = await _parked_run(db, test_company_id)
    by_supervisor, _ = await _run(db, test_company_id, status="PAUSED")   # no approval in its snapshot

    await approval_pause.sweep_paused_runs(db, grace_s=120)
    resumed = {args[0] for function, args, _ in enqueued if function == "resume_paused_run"}
    assert {str(decided.id), str(expired.id)} <= resumed
    assert not {str(waiting.id), str(by_supervisor.id)} & resumed


@pytest.mark.asyncio
async def test_answering_an_approval_resumes_its_run(db, test_company_id, enqueued):
    from tests.integration.test_hitl_respond import _app, _post, _user

    run, approval_id = await _parked_run(db, test_company_id)
    reviewer = await _user(db, test_company_id)
    res = await _post(_app(db, test_company_id, reviewer), approval_id, {"status": "APPROVED"})
    assert res.status_code == 200, res.text
    assert ("resume_paused_run", (str(run.id),), {"_job_id": f"hitl-decided:{approval_id}"}) in enqueued


# ── COST_THRESHOLD asks before the step that would cross it (GH-08) ─────────


async def _spent(db, company_id, run, usd: str):
    """A usage row on the run: what it has spent so far (its column stays 0)."""
    from decimal import Decimal
    from src.ai.usage_service import UsageService
    from src.config.models import IntegrationRegistry

    sku = f"gh08-{uuid.uuid4().hex[:6]}"
    db.add(IntegrationRegistry(company_id=company_id, provider_name="test", service_sku=sku,
                               component_type="tool", internal_cost=Decimal(usd),
                               cost_unit="per_request", status="active", service_category="API_TOOL"))
    await db.flush()
    await UsageService(db).log_usage(company_id, sku, 1, execution_id=run.id, attribution="tool")


def _browse():
    return PlanStep(step_id="s2", name="Browse", type="TOOL_CALL",
                    target={"tool_id": "headless_browser", "prompt_template": "open it"})


async def _cost_gate(db, run, step, threshold: float):
    from src.ai.governance.governance_service import GovernanceService

    entity = SimpleNamespace(name="e", display_name="E", governance={})
    await GovernanceService(db, _Redis()).evaluate_hitl(
        run, entity, step, {"input": "x"}, "BEFORE", governance_dict={"hitl_checkpoints": [
            {"trigger_type": "COST_THRESHOLD", "threshold": threshold}]})


@pytest.mark.asyncio
async def test_a_step_estimated_across_the_threshold_asks_first(db, test_company_id):
    from src.ai.planning.cost_estimator import estimate_step_cost

    run, _ = await _run(db, test_company_id)
    await _spent(db, test_company_id, run, "0.38")
    estimate = float(estimate_step_cost(_browse()))
    threshold = 0.38 + estimate / 2           # not reached yet; reached if the step runs

    with pytest.raises(HITLPending) as parked:
        await _cost_gate(db, run, _browse(), threshold)
    [(approval_id, status, _)] = await _approvals(db, run.id)
    trigger, snapshot = (await db.execute(text(
        "SELECT checkpoint_trigger, context_snapshot FROM human_approvals WHERE id = :i"),
        {"i": str(approval_id)})).one()
    assert trigger == f"COST_THRESHOLD: ${threshold:.2f} before Browse"
    assert snapshot["run_cost_usd"] == pytest.approx(0.38)
    assert snapshot["step_cost_estimate_usd"] == pytest.approx(estimate)

    # The run spends a little more while it is parked (a critic call): the
    # re-dispatched step still finds its approval — no second request.
    await _spent(db, test_company_id, run, "0.001")
    with pytest.raises(HITLPending) as again:
        await _cost_gate(db, run, _browse(), threshold)
    assert again.value.approval_id == parked.value.approval_id
    assert len(await _approvals(db, run.id)) == 1


@pytest.mark.asyncio
async def test_a_step_that_stays_under_the_threshold_runs(db, test_company_id):
    from src.ai.planning.cost_estimator import estimate_step_cost

    run, _ = await _run(db, test_company_id)
    await _spent(db, test_company_id, run, "0.38")
    await _cost_gate(db, run, _browse(), 0.38 + float(estimate_step_cost(_browse())) + 0.01)
    assert await _approvals(db, run.id) == []
