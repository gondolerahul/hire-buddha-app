"""The cutover and the rollout switches (Phase 15 T10-1…T10-3). Real Postgres, rolled back.

* Ledger = balance: any sequence of grants, usage and staff adjustments keeps
  every lot and the debt equal to the ledger, and available − debt equal to
  what went in minus what went out.
* The readiness report finds a business without a wallet and a tenant under a
  partner with no assignment; ``billing.v2_mode = on`` is refused until it is
  clean, and ``on`` records no shadow rows.
* The switches: enforcement off admits work from a wallet in debt and
  suspends no one; entitlements off opens every feature; the programme off
  accrues no commission and takes no applications.
"""
from __future__ import annotations

import random
import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from src.billing import rollout
from tests.harness.partners import partner, tenant, user

pytestmark = pytest.mark.needs_db
D = Decimal


@pytest_asyncio.fixture(autouse=True)
async def own_sessions(monkeypatch):
    """Code that opens its own control sessions (the access audit, notices) gets an engine with no pool."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common import database
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", engine)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_switches():
    rollout.forget()
    yield
    rollout.forget()


async def _switch(db, key: str, value) -> None:
    from src.common.settings_store import set_setting

    await set_setting(db, key, value, actor=user("app_admin", None), reason="test")
    await db.flush()
    rollout.forget()


async def _platform(db):
    from src.auth.platform import platform_company_id
    return await platform_company_id(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", range(6))
async def test_the_ledger_equals_the_balance_after_any_sequence(db, seed):
    from src.billing.wallet import WalletService

    rng = random.Random(seed)
    company = await tenant(db)
    wallets = WalletService(db)
    await wallets.ensure(company)
    net = D(0)
    for _ in range(25):
        amount = D(rng.randrange(1, 500000)) / 100
        op = rng.choice(("grant", "paid", "deduct", "deduct", "adjust"))
        if op in ("grant", "paid"):
            await wallets.grant(company, "topup" if op == "paid" else "grant", amount, expires_at=None,
                                paid=op == "paid", source_type="test", source_id=uuid.uuid4().hex)
            net += amount
        elif op == "deduct":
            await wallets.deduct(company, amount, source_type="test", source_id=uuid.uuid4().hex)
            net -= amount
        else:
            sign = rng.choice((1, -1))
            await wallets.adjust(company, amount * sign, actor_id=uuid.uuid4(), reason="property test")
            net += amount * sign
        await db.flush()
        assert await wallets.check(company) == []
        b = await wallets.balance(company)
        assert b["available"] >= 0 and b["debt"] >= 0
        assert b["available"] - b["debt"] == net


@pytest.mark.asyncio
async def test_readiness_finds_a_missing_wallet_and_an_unassigned_tenant(db):
    from src.auth.models import Company
    from src.billing.cutover import markdown, readiness

    p = await partner(db, "GOLD")
    orphan = Company(name=f"orphan-{uuid.uuid4().hex[:6]}", type="TENANT", status="active", parent_id=p,
                     billing_currency="INR", country_code="IN")
    db.add(orphan)
    await db.flush()
    report = await readiness(db, shadow_days=1)
    by_name = {c["name"]: c for c in report["checks"]}
    assert not report["ready"]
    assert any(pr.get("company") == orphan.name and pr["what"] == "no wallet"
               for pr in by_name["Wallets equal their ledgers"]["problems"])
    assert any(pr.get("company") == orphan.name and "no assignment" in pr["what"]
               for pr in by_name["Partner assignments and tree"]["problems"])
    assert "NOT READY" in markdown(report) and orphan.name in markdown(report)


def _settings_app(db, actor) -> FastAPI:
    from src.auth import dependencies
    from src.billing import settings_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_control_db

    app = FastAPI()
    app.include_router(settings_router.router)

    async def _u():
        return actor

    async def _db():
        yield db

    app.dependency_overrides[dependencies.get_current_user] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    return app


async def _put(db, actor, key, value):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_settings_app(db, actor)), base_url="http://t") as c:
        return await c.put(f"/api/v1/admin/billing-settings/{key}", json={"value": value, "reason": "cutover"})


@pytest.mark.asyncio
async def test_v2_on_is_refused_until_the_report_is_clean(db, monkeypatch):
    from src.billing import cutover

    admin = user("app_admin", await _platform(db))
    ready = {"ready": False, "checks": [{"step": 4, "name": "Platform billing formula", "detail": "none",
                                         "ok": False, "severity": "blocker"}]}

    async def _readiness(_db, **_kw):
        return ready

    monkeypatch.setattr(cutover, "readiness", _readiness)
    refused = await _put(db, admin, "billing.v2_mode", "on")
    assert refused.status_code == 409 and "Platform billing formula" in refused.text
    ready.update(ready=True, checks=[])
    assert (await _put(db, admin, "billing.v2_mode", "on")).status_code == 200


@pytest.mark.asyncio
async def test_v2_on_records_no_shadow(db):
    from src.billing.shadow import record_shadow

    t = await tenant(db)
    await _switch(db, "billing.v2_mode", "on")
    assert await record_shadow(db, company_id=t, subject_type="run", subject_id=None, rows=[],
                               v1_cost_usd=D(1), v1_billed_usd=D(1)) is None
    await _switch(db, "billing.v2_mode", "shadow")
    assert await record_shadow(db, company_id=t, subject_type="run", subject_id=None, rows=[],
                               v1_cost_usd=D(1), v1_billed_usd=D(1)) is not None


@pytest.mark.asyncio
async def test_enforcement_off_admits_a_wallet_in_debt(db):
    from src.billing import suspension
    from src.billing.credit_service import state_refusal
    from src.billing.wallet import WalletService

    t = await tenant(db)
    wallets = WalletService(db)
    await wallets.ensure(t)
    await wallets.deduct(t, D(100), source_type="test", source_id="debt")
    await db.flush()
    assert state_refusal(await wallets.balance(t)) is not None
    await _switch(db, "billing.enforcement_enabled", False)
    balance = await wallets.balance(t)
    assert balance["state"] != "ok" and balance["enforced"] is False and state_refusal(balance) is None
    (await wallets.get(t)).state = "suspended"
    await db.flush()
    suspension.forget()
    assert await suspension.is_suspended(db, t) is False
    await _switch(db, "billing.enforcement_enabled", True)
    suspension.forget()
    assert await suspension.is_suspended(db, t) is True
    suspension.forget()


@pytest.mark.asyncio
async def test_entitlements_off_open_every_feature(db):
    from src.billing import features
    from src.billing.billing_models import CompanyEntitlementOverride

    t = await tenant(db)
    db.add(CompanyEntitlementOverride(company_id=t, feature_key="feature.agents.templates", enabled=False, reason="test"))
    await db.flush()
    features.forget(t)
    assert (await features.entitlement(db, t, "feature.agents.templates")).enabled is False
    await _switch(db, "entitlements.enforced", False)
    features.forget(t)
    got = await features.entitlement(db, t, "feature.agents.templates")
    assert got.enabled is True and got.source == "rollout"
    features.forget(t)


@pytest.mark.asyncio
async def test_the_programme_off_accrues_nothing_and_takes_no_applications(db):
    from src.partners import commission
    from src.partners.applications import apply

    p = await partner(db, "GOLD")
    t = await tenant(db, p, since_days_ago=30)
    await _switch(db, "partners.programme_enabled", False)
    assert await commission.distribute(db, tenant_id=t, revenue_kind="subscription", base=D(10000), currency="INR",
                                       source_type="payment", source_id="off") == []
    with pytest.raises(HTTPException) as refused:
        await apply(db, {"email": "someone@example.com", "company_name": "X"})
    assert refused.value.status_code == 403


@pytest.mark.asyncio
async def test_customer_notices_are_filled_per_company_and_sent_once_each(db, monkeypatch):
    from src.billing import cutover_notices
    from src.notifications import service

    usd, inr = await tenant(db, currency="USD"), await tenant(db)
    sent = []

    async def _notify(company_id, **kw):
        sent.append((company_id, kw))
        return 1

    monkeypatch.setattr(service, "notify", _notify)
    dry = await cutover_notices.send(db, "billing_currency", date="1 Dec", company_ids=[usd, inr])
    assert dry["companies"] == 2 and dry["told"] == 0 and sent == []
    done = await cutover_notices.send(db, "billing_currency", date="1 Dec", company_ids=[usd, inr], dry_run=False)
    assert done["told"] == 2
    titles = {c: kw["title"] for c, kw in sent}
    assert titles[usd].endswith("billed in USD") and titles[inr].endswith("billed in INR")
    assert {kw["dedupe_key"] for _c, kw in sent} == {"phase15:billing_currency:v1"}
    assert all("{" not in kw["body"] for _c, kw in sent)


@pytest.mark.asyncio
async def test_a_suspended_partner_cannot_act_in_its_tenants(db):
    from src.partners.access import check_acting, grant_for_created_tenant
    from src.partners.models import PartnerProfile

    p = await partner(db, "GOLD")
    t = await tenant(db, p)
    await grant_for_created_tenant(db, partner_id=p, tenant_id=t)
    await db.flush()
    actor = user("partner_admin", p)
    await check_acting(db, user=actor, tenant_id=t, method="GET", path="/api/v1/ai/entities")
    (await db.get(PartnerProfile, p)).status = "suspended"
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await check_acting(db, user=actor, tenant_id=t, method="GET", path="/api/v1/ai/entities")
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "partner_suspended"
