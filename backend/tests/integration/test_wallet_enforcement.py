"""What a wallet's state switches off and on (Phase 15 T4-6…T4-9; tech design §6.3).

Leaving ``ok`` pauses the business's automation (``negative_balance``) and tells
its admins; repaying resumes it (but not a pause the business made) and
restarts apps stopped for balance. Over the tolerance for
``billing.suspend_after_days`` the wallet is suspended: the company is
read-only except paying, and its Data API is off. Committed rows, one company
per test, purged afterwards.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from src.automation import limits as limits_mod
from src.billing import suspension
from src.billing.wallet import WalletService
from src.billing.wallet_jobs import enforce
from tests.harness.wallet import fund

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def biz(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.auth.models import Company, User
    from src.common import database
    from src.common.config import settings
    from src.common.email import email_service
    from tests.harness.purge import purge_companies

    engine = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                 json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))

    async def _mail(to, subject, body):
        return True

    monkeypatch.setattr(email_service, "async_send_email", _mail)
    async with database.AsyncSessionLocal() as db:
        company = Company(name=f"p15-enforce-{uuid.uuid4().hex[:6]}", type="TENANT", status="active",
                          billing_currency="USD")
        db.add(company)
        await db.flush()
        owner = User(email=f"p15-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Owner",
                     role="tenant_admin", company_id=company.id, is_active=True, is_verified=True)
        db.add(owner)
        await fund(db, company.id, "1")
        await db.commit()
        ids = SimpleNamespace(company=company.id, owner=owner)
    limits_mod.forget_state()
    suspension.forget()
    try:
        yield ids
    finally:
        limits_mod.forget_state()
        suspension.forget()
        async with engine.begin() as conn:
            await purge_companies(conn, [ids.company])
        await engine.dispose()


def _session():
    from src.common import database
    return database.AsyncSessionLocal()


async def _automation(company_id):
    from src.automation.models import AutomationLimitsRow
    async with _session() as db:
        row = (await db.execute(select(AutomationLimitsRow).where(AutomationLimitsRow.company_id == company_id))
               ).scalar_one_or_none()
        return (row.automation_state, row.paused_reason) if row else ("running", None)


async def _spend(company_id, amount):
    from src.billing.enforcement import wallet_changed
    async with _session() as db:
        change = await WalletService(db).deduct(company_id, Decimal(amount), source_type="test")
        await db.commit()
        await wallet_changed(db, company_id, change)
        return change


async def _top_up(company_id, amount):
    from src.billing.credit_service import CreditService
    async with _session() as db:
        return await CreditService(db).add_wallet_credits(company_id, Decimal(amount), source_id="test")


async def test_going_into_debt_pauses_automation_and_repaying_resumes_it(biz):
    from src.notifications.models import Notification

    change = await _spend(biz.company, "3")
    assert change.state_after == "over_tolerance"
    assert await _automation(biz.company) == ("paused", "negative_balance")
    assert await limits_mod.automation_state_for(biz.company) == "paused"
    await _top_up(biz.company, "10")
    assert await _automation(biz.company) == ("running", None)
    async with _session() as db:
        kinds = (await db.execute(select(Notification.kind).where(Notification.company_id == biz.company)
                                  .order_by(Notification.created_at))).scalars().all()
    assert kinds == ["wallet.over_tolerance", "wallet.ok"]


async def test_a_pause_the_business_made_is_not_resumed_by_repayment(biz):
    from src.automation.models import AutomationLimitsRow
    async with _session() as db:
        db.add(AutomationLimitsRow(company_id=biz.company, limits={}, automation_state="paused",
                                   paused_reason="owner paused it"))
        await db.commit()
    await _spend(biz.company, "3")
    await _top_up(biz.company, "10")
    assert await _automation(biz.company) == ("paused", "owner paused it")


async def test_over_the_tolerance_too_long_the_account_is_suspended_and_read_only(biz):
    from src.billing.billing_models import CreditWallet
    await _spend(biz.company, "3")
    async with _session() as db:
        wallet = (await db.execute(select(CreditWallet).where(CreditWallet.company_id == biz.company))).scalar_one()
        wallet.over_tolerance_since = datetime.utcnow() - timedelta(days=8)        # suspend_after_days = 7
        await db.commit()
    async with _session() as db:
        result = await enforce(db)
    assert result["suspended"] >= 1
    async with _session() as db:
        assert await suspension.is_suspended(db, biz.company)

        def request(method, path):
            return SimpleNamespace(method=method, url=SimpleNamespace(path=path))

        user = SimpleNamespace(company_id=biz.company)
        await suspension.refuse_writes(request("GET", "/api/v1/ai/entities"), db, user)          # reads go on
        await suspension.refuse_writes(request("POST", "/api/v1/credits/topup"), db, user)      # paying too
        with pytest.raises(HTTPException) as refused:
            await suspension.refuse_writes(request("POST", "/api/v1/ai/entities"), db, user)
        assert refused.value.status_code == 402 and "read-only" in refused.value.detail
    from src.billing.suspension import AccountSuspended
    from src.data_api.app import _not_suspended
    with pytest.raises(AccountSuspended):
        await _not_suspended(biz.company)
    await _top_up(biz.company, "10")                        # repaid: open again
    async with _session() as db:
        assert not await suspension.is_suspended(db, biz.company)
        assert (await WalletService(db).get(biz.company)).state == "ok"


async def test_apps_stop_after_the_grace_and_start_on_repayment(biz, monkeypatch):
    from src.billing import enforcement_hooks as hooks

    actions: list = []
    apps = {"published": [uuid.uuid4()], "stopped": []}

    async def published(company_id, *, stopped_for_balance):
        return list(apps["stopped"] if stopped_for_balance else apps["published"])

    async def operate(company_id, app_id, action):
        actions.append(action)
        source, target = ("published", "stopped") if action == "stop" else ("stopped", "published")
        apps[source].remove(app_id)
        apps[target].append(app_id)

    async def mark(company_id, app_id, stopped):
        return None

    monkeypatch.setattr(hooks, "_published_apps", published)
    monkeypatch.setattr(hooks, "_mark", mark)
    monkeypatch.setattr("src.apps.service.operate", operate)
    await _spend(biz.company, "3")                          # grace 0 h: the next tick stops them
    async with _session() as db:
        result = await enforce(db)
    assert result["apps_stopped"] == 1 and actions == ["stop"]
    async with _session() as db:
        assert (await enforce(db))["apps_stopped"] == 0      # already stopped
    await _top_up(biz.company, "10")
    assert actions == ["stop", "start"] and apps["stopped"] == []
