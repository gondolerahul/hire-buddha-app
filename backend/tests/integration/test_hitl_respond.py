"""Answering a HITL approval (GH-23, GH-24).

GH-23: the panel posts ``{status, notes}`` as JSON; the endpoint read them from
the query string, so every click was a 422. It now takes a validated body.

GH-24: the endpoint loaded the approval by id alone, so any user holding
another company's approval id could answer it. It is now scoped through the
run's company, and only a PENDING approval can be answered — once.

Runs against the real Postgres inside the suite's rolled-back transaction.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text

pytestmark = pytest.mark.needs_db


async def _company(db) -> uuid.UUID:
    cid = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO companies (id, name, type, status, created_at, updated_at) "
        "VALUES (:id, :n, 'TENANT', 'active', now(), now())"), {"id": str(cid), "n": f"hitl-{cid.hex[:6]}"})
    return cid


async def _user(db, company_id) -> uuid.UUID:
    """responded_by references users.id."""
    uid = uuid.uuid4()
    await db.execute(text(
        "INSERT INTO users (id, email, hashed_password, full_name, role, company_id, is_active) "
        "VALUES (:id, :email, 'x', 'Reviewer', 'tenant_user', :c, true)"),
        {"id": str(uid), "email": f"reviewer-{uid.hex[:8]}@test.local", "c": str(company_id)})
    return uid


async def _pending_approval(db, company_id) -> uuid.UUID:
    from src.ai.models import ExecutionRun, HumanApproval
    from src.ai.orm.entity import HierarchicalEntity
    ent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name="hitl-agent")
    db.add(ent)
    await db.flush()
    run = ExecutionRun(entity_id=ent.id, company_id=company_id, status="RUNNING", input_data={})
    db.add(run)
    await db.flush()
    approval = HumanApproval(run_id=run.id, checkpoint_trigger="BEFORE_STEP: Send", status="PENDING",
                             context_snapshot={"step_name": "Send"}, timeout_ms=300000)
    db.add(approval)
    await db.flush()
    return approval.id


async def _status(db, approval_id):
    return (await db.execute(text("SELECT status, reviewer_notes FROM human_approvals WHERE id = :i"),
                             {"i": str(approval_id)})).one()


def _app(db, company_id, user_id=None) -> FastAPI:
    from src.ai import router as ai_router_module
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(ai_router_module.router, prefix="/api/v1")

    async def _user():
        return SimpleNamespace(id=user_id or uuid.uuid4(), role="tenant_user", company_id=company_id)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return app


async def _post(app, approval_id, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(f"/api/v1/ai/approvals/{approval_id}/respond", json=body)


@pytest.mark.asyncio
async def test_the_panels_request_is_accepted(db):
    company = await _company(db)
    approval_id = await _pending_approval(db, company)
    reviewer = await _user(db, company)
    res = await _post(_app(db, company, reviewer), approval_id,
                      {"status": "APPROVED", "notes": "Responded via HITL Dashboard"})
    assert res.status_code == 200, res.text
    assert tuple(await _status(db, approval_id)) == ("APPROVED", "Responded via HITL Dashboard")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"status": "MAYBE"}, {"status": "APPROVED", "action": "x"}, {}])
async def test_bad_bodies_are_rejected(db, body):
    company = await _company(db)
    approval_id = await _pending_approval(db, company)
    res = await _post(_app(db, company), approval_id, body)
    assert res.status_code == 422
    assert (await _status(db, approval_id))[0] == "PENDING"


@pytest.mark.asyncio
async def test_another_company_cannot_answer(db):
    owner, stranger = await _company(db), await _company(db)
    approval_id = await _pending_approval(db, owner)
    res = await _post(_app(db, stranger), approval_id, {"status": "APPROVED"})
    assert res.status_code == 404
    assert (await _status(db, approval_id))[0] == "PENDING"


@pytest.mark.asyncio
async def test_an_approval_is_answered_once(db):
    from src.ai.service import AIService
    company = await _company(db)
    approval_id = await _pending_approval(db, company)
    reviewer = await _user(db, company)
    svc = AIService(db)
    await svc.respond_to_approval(approval_id, "REJECTED", reviewer, "no", company_id=company)
    with pytest.raises(HTTPException) as err:
        await svc.respond_to_approval(approval_id, "APPROVED", reviewer, "yes", company_id=company)
    assert err.value.status_code == 409
    assert tuple(await _status(db, approval_id)) == ("REJECTED", "no")


@pytest.mark.asyncio
async def test_a_timed_out_approval_cannot_be_answered(db):
    from src.ai.service import AIService
    company = await _company(db)
    approval_id = await _pending_approval(db, company)
    await db.execute(text("UPDATE human_approvals SET status = 'TIMEOUT' WHERE id = :i"), {"i": str(approval_id)})
    with pytest.raises(HTTPException) as err:
        await AIService(db).respond_to_approval(approval_id, "APPROVED", await _user(db, company),
                                                company_id=company)
    assert err.value.status_code == 409
