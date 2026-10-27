"""Closing and deleting businesses (docs/phase15/13). Real Postgres, committed — the runner works in
sessions of its own — and every company made here is purged afterwards.

* Flow B (§10): a test business and everything it owns deleted at once — its rows, users, files,
  Git repositories, its numbers back in the pool, its own database dropped; the offboarding record
  and the delete's audit row stay. Refused while the switch is off, for a business that is not a
  test one, with the wrong name, and for the platform company; a business with real money cannot
  be marked test.
* Flow A (§5–§9): the admin asks; the business is read-only, may cancel; erasure keeps the books
  (invoices, payments, the wallet's ledger) with the company anonymised, forfeits what credit is
  left (no refund, D-2), keeps the billing summary and the certificate, and leaves nothing else.
* A step that fails is logged and the run resumes there.
* One person erased from a business (§6.6).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path):
    """Own sessions (NullPool), in-memory storage, a scratch Git root, and no queue: tests run the runner."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.code_lanes import git
    from src.common import database
    from src.common.config import settings
    from src.common.platform import storage as storage_mod
    from src.offboarding import runner
    from tests.harness.storage import MemoryStorage

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", engine)
    memory = MemoryStorage()
    storage_mod.set_storage(memory)
    git.set_builtin_provider(git.LocalGitProvider(tmp_path / "git"))
    queued = []

    async def no_queue(offboarding_id):
        queued.append(offboarding_id)

    monkeypatch.setattr(runner, "enqueue", no_queue)
    made: list = []
    yield SimpleNamespace(storage=memory, queued=queued, made=made, git_root=tmp_path / "git")
    storage_mod.set_storage(None)
    git.set_builtin_provider(None)
    from src.common.tenancy.session import control_session
    from src.offboarding.models import CompanyOffboarding
    from src.offboarding.purge import purge_companies

    async with control_session() as db:
        await db.execute(text("DELETE FROM platform_settings WHERE key LIKE 'offboarding.%'"))
        await db.execute(CompanyOffboarding.__table__.delete().where(CompanyOffboarding.company_id.in_(made)))
        await db.execute(text("DELETE FROM admin_audit_log WHERE target_company_id = ANY(:ids)"), {"ids": made})
        await purge_companies(await db.connection(), [c for c in made])
        await db.commit()
    await engine.dispose()


def _staff():
    return SimpleNamespace(id=uuid.uuid4(), role="app_admin", company_id=None, email="staff@example.com")


async def _setting(key: str, value) -> None:
    from src.common.settings_store import set_platform_setting
    from src.common.tenancy.session import control_session

    async with control_session() as db:
        await set_platform_setting(db, key, value, actor=_staff(), reason="test")
        await db.commit()


async def _business(env, *, is_test: bool, name: str = "obd") -> SimpleNamespace:
    """A business with people, credit, usage, a billing line, a number, files, a repository and an audit row."""
    from src.auth.models import Company, User
    from src.billing.billing_models import BillingLine
    from src.common.admin_audit import record_admin_change
    from src.common.tenancy.session import control_session
    from src.voice.phone_pool_models import PhoneNumber
    from tests.harness.wallet import fund

    company_id = uuid.uuid4()
    env.made.append(company_id)
    admin_email = f"obd-{company_id.hex[:8]}@example.com"
    async with control_session() as db:
        db.add(Company(id=company_id, name=f"{name}-{company_id.hex[:8]}", type="TENANT", status="active",
                       is_test=is_test, onboarding_status="completed", gstin=None))
        await db.flush()
        admin = User(email=admin_email, full_name="Obd Admin", hashed_password="!x", role="tenant_admin",
                     company_id=company_id, is_active=True, is_verified=True)
        db.add(admin)
        db.add(User(email=f"obd-u-{company_id.hex[:8]}@example.com", full_name="Obd User", hashed_password="!x",
                    role="tenant_user", company_id=company_id, is_active=True, is_verified=True))
        await fund(db, company_id, "10", expires_in=timedelta(days=30))
        db.add(BillingLine(company_id=company_id, period_day=datetime.utcnow().date(), category="ai_models",
                           currency="INR", cost_usd=Decimal(1), billed_usd=Decimal(2), billed_ccy=Decimal(200)))
        number = PhoneNumber(phone_number=f"+9180{uuid.uuid4().int % 10**8:08d}", status="claimed",
                             company_id=company_id, provider="tata", country_code="IN", is_active=True)
        db.add(number)
        record_admin_change(db, actor=_staff(), action="set", object_type="spend_cap", object_key=str(company_id),
                            target_company_id=company_id, new_value={"cap": 5}, reason="test")
        await db.commit()
        admin_id, number_id = admin.id, number.id
    hexed = company_id.hex
    await env.storage.put(f"c-{hexed}/files/report.txt", b"hello")
    await env.storage.put(f"c-{hexed}/invoices/HB-1.pdf", b"%PDF-1.4 invoice")
    from src.code_lanes.git import builtin_provider
    await builtin_provider().create_repo(f"c-{hexed[:12]}", "crm")
    return SimpleNamespace(id=company_id, admin_id=admin_id, admin_email=admin_email, number_id=number_id,
                           name=f"{name}-{company_id.hex[:8]}")


async def _rows(company_id) -> int:
    from src.common.tenancy.session import control_session
    from src.offboarding.purge import row_counts

    async with control_session() as db:
        return sum((await row_counts(await db.connection(), company_id)).values())


# ── Flow B ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_test_business_is_deleted_with_everything_it_owns(env):
    from src.auth.models import Company
    from src.common.tenancy.session import control_session
    from src.offboarding import runner, service
    from src.offboarding.models import CompanyOffboarding
    from src.voice.phone_pool_models import PhoneNumber

    await _setting("offboarding.immediate_delete_enabled", True)
    biz = await _business(env, is_test=True)
    assert await _rows(biz.id) > 0
    async with control_session() as db:
        [off] = await service.delete_immediately(db, biz.id, actor=_staff(), reason="feature test done",
                                                 confirm_name=biz.name)
    assert env.queued == [off.id]
    result = await runner.run(off.id)
    assert result["state"] == "erased", result
    async with control_session() as db:
        assert await db.get(Company, biz.id) is None
        assert await _rows(biz.id) == 0
        assert (await db.execute(text("SELECT count(*) FROM users WHERE email = :e"), {"e": biz.admin_email})).scalar() == 0
        number = await db.get(PhoneNumber, biz.number_id)
        assert number.company_id is None and number.status == "available"
        kept = await db.get(CompanyOffboarding, off.id)
        assert kept.state == "erased" and kept.certificate["kind"].startswith("test business")
        audit = (await db.execute(text("SELECT action FROM admin_audit_log WHERE target_company_id = :c"),
                                  {"c": biz.id})).scalars().all()
        assert audit == ["delete_immediately"]          # the delete's own record stays; the rest went
    assert not [k for k in env.storage.objects if k.startswith(f"c-{biz.id.hex}/")]
    assert not (env.git_root / f"c-{biz.id.hex[:12]}").exists()


@pytest.mark.asyncio
async def test_a_test_business_with_its_own_database_loses_it(env):
    from src.common.tenancy.session import control_session
    from src.offboarding import runner, service
    from src.offboarding.workspace import Workspace, database_exists
    from tests.harness.tenant_db import scratch_tenant

    await _setting("offboarding.immediate_delete_enabled", True)
    async with scratch_tenant("obdtenant") as tenant:
        env.made.append(tenant.company_id)
        async with control_session() as db:
            await db.execute(text("UPDATE companies SET is_test = true WHERE id = :c"), {"c": tenant.company_id})
            await db.commit()
            name = (await db.execute(text("SELECT name FROM companies WHERE id = :c"), {"c": tenant.company_id})).scalar()
            [off] = await service.delete_immediately(db, tenant.company_id, actor=_staff(), reason="test",
                                                     confirm_name=name)
        ws = Workspace(company_id=tenant.company_id, tenant_key=tenant.key, db_name=tenant.db_name,
                       server_host="localhost")
        assert await database_exists(ws)
        result = await runner.run(off.id)
        assert result["state"] == "erased", result
        assert not await database_exists(ws)


@pytest.mark.asyncio
async def test_immediate_delete_is_refused_unless_every_guard_holds(env):
    from fastapi import HTTPException

    from src.auth.platform import platform_company_id
    from src.billing.billing_models import PaymentTransaction
    from src.common.tenancy.session import control_session
    from src.offboarding import service

    biz = await _business(env, is_test=True)
    real = await _business(env, is_test=False)
    async with control_session() as db:
        with pytest.raises(HTTPException) as off_switch:          # the switch is off by default
            await service.delete_immediately(db, biz.id, actor=_staff(), reason="x", confirm_name=biz.name)
        assert off_switch.value.status_code == 409
    await _setting("offboarding.immediate_delete_enabled", True)
    async with control_session() as db:
        with pytest.raises(HTTPException) as not_test:
            await service.delete_immediately(db, real.id, actor=_staff(), reason="x", confirm_name=real.name)
        assert not_test.value.status_code == 409 and "not marked as a test business" in str(not_test.value.detail)
        with pytest.raises(HTTPException) as wrong_name:
            await service.delete_immediately(db, biz.id, actor=_staff(), reason="x", confirm_name="something else")
        assert wrong_name.value.status_code == 422
        with pytest.raises(HTTPException) as platform:
            await service.delete_immediately(db, await platform_company_id(db), actor=_staff(), reason="x",
                                             confirm_name="HireBuddha")
        assert platform.value.status_code == 409
        tenant_admin = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=biz.id, email="a@example.com")
        with pytest.raises(HTTPException) as not_staff:
            await service.delete_immediately(db, biz.id, actor=tenant_admin, reason="x", confirm_name=biz.name)
        assert not_staff.value.status_code == 403
        db.add(PaymentTransaction(company_id=real.id, amount=Decimal(100), currency="INR",
                                  transaction_type="topup", status="success"))
        await db.commit()
        with pytest.raises(HTTPException) as real_money:
            await service.set_test(db, real.id, True, actor=_staff(), reason="x")
        assert real_money.value.status_code == 409 and "paid payments" in str(real_money.value.detail)


# ── Flow A ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_business_closes_keeps_its_books_and_nothing_else(env):
    from fastapi import HTTPException

    from src.auth.models import Company, User
    from src.billing.billing_models import WalletEntry, WalletLot
    from src.billing.suspension import refuse_writes
    from src.common.tenancy.session import control_session
    from src.offboarding import runner, service
    from src.offboarding.models import CompanyOffboarding

    biz = await _business(env, is_test=False)
    admin = SimpleNamespace(id=biz.admin_id, role="tenant_admin", company_id=biz.id, email=biz.admin_email)
    async with control_session() as db:
        off = await service.request_closure(db, biz.id, actor=admin, reason="we are closing down", export=True)
        assert off.confirmed_at is not None and off.grace_until > datetime.utcnow() + timedelta(days=29)
        company = await db.get(Company, biz.id)
        assert company.status == "offboarding_requested"
        request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/v1/ai/entities"))
        with pytest.raises(HTTPException) as read_only:
            await refuse_writes(request, db, SimpleNamespace(company=company, company_id=biz.id, role="tenant_admin"))
        assert read_only.value.status_code == 409
        await service.cancel_closure(db, biz.id, actor=admin)
        assert (await db.get(Company, biz.id)).status == "active"
        off = await service.request_closure(db, biz.id, actor=admin, reason="closing after all", export=True)
        await service.bring_forward(db, off.id, actor=_staff())
    result = await runner.run(off.id)
    assert result["state"] == "erased", result
    async with control_session() as db:
        company = await db.get(Company, biz.id)
        assert company.status == "erased" and company.name.startswith("Erased business B-")
        assert (await db.execute(select(func.count()).select_from(User).where(User.company_id == biz.id))).scalar() == 0
        lots = (await db.execute(select(WalletLot).where(WalletLot.company_id == biz.id))).scalars().all()
        assert lots and all(lot.remaining == 0 for lot in lots)                      # forfeited, no refund
        expired = (await db.execute(select(WalletEntry).where(WalletEntry.company_id == biz.id,
                                                              WalletEntry.kind == "expire"))).scalars().all()
        assert any(e.reason == "offboarding" for e in expired)
        line_rows = (await db.execute(text("SELECT count(*) FROM billing_lines WHERE company_id = :c"),
                                      {"c": biz.id})).scalar()
        assert line_rows == 0
        done = await db.get(CompanyOffboarding, off.id)
        assert done.state == "erased" and done.company_name is None and done.certificate["kept"]
        assert done.export_key and done.export_key in env.storage.objects
    ref = done.company_ref
    assert f"retained/{ref}/billing-summary.json" in env.storage.objects
    assert f"retained/{ref}/invoices/HB-1.pdf" in env.storage.objects
    assert f"retained/{ref}/certificate.pdf" in env.storage.objects
    assert not [k for k in env.storage.objects if k.startswith(f"c-{biz.id.hex}/")]


@pytest.mark.asyncio
async def test_a_failed_step_is_logged_and_the_run_resumes_there(env, monkeypatch):
    from src.common.tenancy.session import control_session
    from src.offboarding import runner, service, workspace
    from src.offboarding.models import OffboardingStepLog

    await _setting("offboarding.immediate_delete_enabled", True)
    biz = await _business(env, is_test=True)
    async with control_session() as db:
        [off] = await service.delete_immediately(db, biz.id, actor=_staff(), reason="x", confirm_name=biz.name)
    real = workspace.storage_deleted
    calls = {"n": 0}

    async def flaky(ws):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("storage unreachable")
        return await real(ws)

    monkeypatch.setattr(runner, "IMMEDIATE_STEPS",
                        [(n, runner._ws(flaky) if n == "storage_deleted" else f) for n, f in runner.IMMEDIATE_STEPS])
    first = await runner.run(off.id)
    assert first["state"] == "failed" and first["failed"] == "storage_deleted"
    second = await runner.run(off.id)
    assert second["state"] == "erased"
    async with control_session() as db:
        log = (await db.execute(select(OffboardingStepLog.step, OffboardingStepLog.outcome).where(
            OffboardingStepLog.offboarding_id == off.id))).all()
    assert ("storage_deleted", "failed") in log and ("storage_deleted", "succeeded") in log
    assert sum(1 for s, o in log if s == "quiesced" and o == "succeeded") == 1        # not run twice


# ── one person ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_person_is_found_and_erased(env):
    from src.common.tenancy.session import control_session
    from src.offboarding import person

    biz = await _business(env, is_test=True)
    person_email = f"customer-{uuid.uuid4().hex[:6]}@example.com"
    from src.ai.orm import HierarchicalEntity

    async with control_session() as db:
        agent = HierarchicalEntity(company_id=biz.id, type="AGENT", status="ACTIVE", name="caller")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        await db.execute(text(
            "INSERT INTO lead_queue (id, company_id, agent_id, lead_id, phone, lead_data, status, priority, "
            "attempt_count, max_attempts, created_at, updated_at) VALUES (:i, :c, :a, 'L-1', '+919876543210', "
            "CAST(:d AS jsonb), 'pending', 1, 0, 3, now(), now())"),
            {"i": uuid.uuid4(), "c": biz.id, "a": agent_id, "d": '{"name": "Asha", "email": "%s"}' % person_email})
        await db.commit()
    found = await person.search(biz.id, person_email)
    assert found["count"] >= 1 and {m["table"] for m in found["matches"]} >= {"lead_queue"}
    done = await person.erase(biz.id, person_email, actor=_staff())
    assert done["deleted"].get("lead_queue") == 1
    assert (await person.search(biz.id, person_email))["count"] == 0
