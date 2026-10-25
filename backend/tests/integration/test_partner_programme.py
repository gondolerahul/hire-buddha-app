"""The partner programme's structure (Phase 15 T8-1…T8-5, T8-9, T8-11). Real Postgres, rolled back.

* The tree: a tenant under a tenant, a partner four levels deep, a role in the
  wrong kind of company — refused (422); the violations report.
* Scope: a Gold partner sees its own company and the tenants it resells — not
  a referred customer's, not a sub-partner's; a Silver partner sees none.
* Acting: ``X-Company-Id`` from a partner needs an active grant; its scopes
  decide what the request may do; every request is recorded; an expired or
  revoked grant is refused.
* Applications: invite → apply → underwriting → approve (company, profile,
  agreement, admin) → sign → active; the depth limit.
* Leads: duplicates refused; a Silver lead converted by staff is a referred
  customer of BCL's; a Gold partner converts its own as resold.
* Reassignment splits attribution at its date; termination sends the tenants
  to BCL direct, revokes grants and forfeits unpaid earnings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from src.auth.models import Company
from src.partners import commission
from src.partners.models import (
    PartnerAccessEvent, PartnerAccessGrant, PartnerAgreement, PartnerAssignment, PartnerLead, PartnerProfile,
)
from src.partners.scope import data_scope
from tests.harness.partners import partner, tenant, user

pytestmark = pytest.mark.needs_db
D = Decimal


def _app(db, actor) -> FastAPI:
    from src.auth import company_router, dependencies, router as auth_router, user_router
    from src.common.database import get_db
    from src.common.tenancy.session import get_acting_tenant_db, get_control_db
    from src.partners import admin_router, portal_router, tenant_router

    app = FastAPI()
    for module in (portal_router, tenant_router, admin_router):
        app.include_router(module.router)
    app.include_router(company_router.router, prefix="/api/v1")
    app.include_router(user_router.router, prefix="/api/v1")

    @app.api_route("/acting", methods=["GET", "POST", "DELETE"])
    async def acting(db_=__import__("fastapi").Depends(get_acting_tenant_db)):
        return {"ok": True}

    async def _u():
        return actor

    async def _db():
        yield db

    for dep in (dependencies.get_current_user, auth_router.get_current_user):
        app.dependency_overrides[dep] = _u
    for dep in (get_db, get_control_db):
        app.dependency_overrides[dep] = _db
    return app


async def _call(db, actor, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, actor)), base_url="http://t") as c:
        return await c.request(method, path, **kw)


@pytest_asyncio.fixture
async def own_sessions(monkeypatch):
    """Sessions of their own (the access audit writes in one) on an engine with no pool: the app's pool
    may hold a connection an earlier test opened on its closed event loop."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.common import database
    from src.common.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """Applications are throttled per address (five an hour); not across these tests."""
    async def _zero(self, subject):
        return 0

    async def _none(self, subject):
        return None

    monkeypatch.setattr("src.auth.throttle.Throttle.retry_after", _zero)
    monkeypatch.setattr("src.auth.throttle.Throttle.hit", _none)


async def _platform(db):
    from src.auth.platform import platform_company_id
    return await platform_company_id(db)


# ── the tree (T8-1) ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tenant_cannot_be_under_a_tenant(db):
    t = await tenant(db)
    res = await _call(db, user("app_admin", await _platform(db)), "POST", "/api/v1/companies",
                      json={"name": "Child", "type": "TENANT", "parent_id": str(t)})
    assert res.status_code == 422 and "TENANT cannot be under a TENANT" in res.text


@pytest.mark.asyncio
async def test_partners_are_at_most_three_levels_deep(db):
    p1 = await partner(db)
    p2 = await partner(db, recruiter=p1)
    p3 = await partner(db, recruiter=p2)
    res = await _call(db, user("app_admin", await _platform(db)), "POST", "/api/v1/companies",
                      json={"name": "Fourth", "type": "PARTNER", "parent_id": str(p3)})
    assert res.status_code == 422 and "3 levels" in res.text
    assert (await db.get(PartnerProfile, p3)).depth == 3


@pytest.mark.asyncio
async def test_staff_add_a_partner_with_its_profile(db):
    res = await _call(db, user("app_admin", await _platform(db)), "POST", "/api/v1/companies",
                      json={"name": f"Direct partner {uuid.uuid4().hex[:4]}", "type": "PARTNER",
                            "partner_type": "SILVER"})
    assert res.status_code == 200, res.text
    profile = await db.get(PartnerProfile, uuid.UUID(res.json()["id"]))
    assert (profile.partner_type, profile.status, profile.depth) == ("SILVER", "active", 1)


@pytest.mark.asyncio
async def test_a_role_must_fit_its_company(db):
    t = await tenant(db)
    res = await _call(db, user("app_admin", await _platform(db)), "POST", "/api/v1/users", json={
        "email": f"x{uuid.uuid4().hex[:6]}@example.com", "full_name": "X", "password": "Str0ng!Passw0rd#1",
        "company_id": str(t), "role": "partner_admin"})
    assert res.status_code == 422 and "partner_admin cannot belong to a TENANT" in res.text


@pytest.mark.asyncio
async def test_the_tree_check_reports_violations(db):
    t = await tenant(db)
    child = Company(name="bad", type="TENANT", status="active", parent_id=t, billing_currency="INR",
                    country_code="IN")
    db.add(child)
    await db.flush()
    res = await _call(db, user("app_admin", await _platform(db)), "GET", "/api/v1/admin/partners/tree-check")
    assert any(v["kind"] == "parent" and v["company_id"] == str(child.id) for v in res.json()["violations"])


# ── scope (T8-3) ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_gold_partner_sees_its_resold_tenants_only(db):
    gold = await partner(db, "GOLD")
    sub = await partner(db, "GOLD", recruiter=gold)
    resold = await tenant(db, gold)
    referred = await tenant(db, gold, "referred")
    subs_tenant = await tenant(db, sub)
    scope = await data_scope(db, gold)
    assert resold in scope and gold in scope
    assert referred not in scope and subs_tenant not in scope and sub not in scope


@pytest.mark.asyncio
async def test_a_silver_partner_sees_no_tenant_data(db):
    silver = await partner(db, "SILVER")
    await tenant(db, silver, "referred")
    assert await data_scope(db, silver) == frozenset({silver})
    listed = await _call(db, user("partner_admin", silver), "GET", "/api/v1/companies")
    assert [c["id"] for c in listed.json()] == [str(silver)]


@pytest.mark.asyncio
async def test_a_gold_partner_creates_a_tenant_with_an_assignment_and_a_grant(db):
    gold = await partner(db, "GOLD")
    res = await _call(db, user("partner_admin", gold), "POST", "/api/v1/companies",
                      json={"name": f"Gold's customer {uuid.uuid4().hex[:4]}", "type": "TENANT"})
    assert res.status_code == 200, res.text
    t = uuid.UUID(res.json()["id"])
    assignment = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == t))).scalar_one()
    grant = (await db.execute(select(PartnerAccessGrant).where(PartnerAccessGrant.tenant_id == t))).scalar_one()
    assert (assignment.partner_id, assignment.relationship, assignment.source) == (gold, "resold", "created")
    assert (grant.scopes, grant.status, grant.expires_at) == (["admin"], "active", None)


@pytest.mark.asyncio
async def test_a_silver_partner_cannot_create_tenants(db):
    silver = await partner(db, "SILVER")
    res = await _call(db, user("partner_admin", silver), "POST", "/api/v1/companies",
                      json={"name": "No", "type": "TENANT"})
    assert res.status_code == 403


# ── acting under a grant (T8-4) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acting_needs_a_grant_and_follows_its_scopes(db, own_sessions):
    gold = await partner(db, "GOLD")
    t = await tenant(db, gold)
    admin, headers = user("partner_admin", gold), {"X-Company-Id": str(t)}
    refused = await _call(db, admin, "GET", "/acting", headers=headers)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "no_access_grant"
    grant = PartnerAccessGrant(partner_id=gold, tenant_id=t, scopes=["read"], status="active")
    db.add(grant)
    await db.flush()
    assert (await _call(db, admin, "GET", "/acting", headers=headers)).status_code == 200
    assert (await _call(db, admin, "POST", "/acting", headers=headers)).status_code == 403   # read only
    grant.scopes = ["support"]
    await db.flush()
    assert (await _call(db, admin, "POST", "/acting", headers=headers)).status_code == 200
    assert (await _call(db, admin, "DELETE", "/acting", headers=headers)).status_code == 403
    grant.expires_at = datetime.utcnow() - timedelta(minutes=1)
    await db.flush()
    assert (await _call(db, admin, "GET", "/acting", headers=headers)).status_code == 403
    from src.common.tenancy.session import control_session
    async with control_session() as other:                   # recorded in a session of its own
        events = (await other.execute(select(PartnerAccessEvent).where(PartnerAccessEvent.tenant_id == t))
                  ).scalars().all()
        assert len(events) == 2                 # the two requests the grant allowed
        for event in events:
            await other.delete(event)
        await other.commit()


@pytest.mark.asyncio
async def test_a_partner_user_never_acts_beyond_support(db, own_sessions):
    gold = await partner(db, "GOLD")
    t = await tenant(db, gold)
    db.add(PartnerAccessGrant(partner_id=gold, tenant_id=t, scopes=["admin"], status="active"))
    await db.flush()
    res = await _call(db, user("partner_user", gold), "DELETE", "/acting", headers={"X-Company-Id": str(t)})
    assert res.status_code == 403
    from src.common.tenancy.session import control_session
    from sqlalchemy import delete
    async with control_session() as other:
        await other.execute(delete(PartnerAccessEvent).where(PartnerAccessEvent.tenant_id == t))
        await other.commit()


@pytest.mark.asyncio
async def test_the_tenant_approves_and_revokes_a_request(db):
    gold = await partner(db, "GOLD")
    t = await tenant(db, gold)
    asked = await _call(db, user("partner_admin", gold), "POST", "/api/v1/partner/access",
                        json={"tenant_id": str(t), "scopes": ["billing"], "reason": "set up the plan", "days": 30})
    assert asked.status_code == 201 and asked.json()["status"] == "requested"
    tenant_admin = user("tenant_admin", t)
    view = (await _call(db, tenant_admin, "GET", "/api/v1/settings/partner-access")).json()
    assert view["partner"]["relationship"] == "resold" and len(view["grants"]) == 1
    grant_id = asked.json()["id"]
    assert (await _call(db, tenant_admin, "POST", f"/api/v1/settings/partner-access/{grant_id}/approve",
                        json={})).json()["status"] == "active"
    assert (await _call(db, tenant_admin, "POST", f"/api/v1/settings/partner-access/{grant_id}/revoke"
                        )).json()["status"] == "revoked"
    other = await tenant(db)
    stranger = await _call(db, user("partner_admin", gold), "POST", "/api/v1/partner/access",
                           json={"tenant_id": str(other), "scopes": ["read"], "reason": "please"})
    assert stranger.status_code == 403


# ── applications (T8-5) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invite_apply_underwrite_approve_sign(db, monkeypatch):
    sent = []

    async def _mail(email, hashed):
        sent.append(email)

    monkeypatch.setattr("src.auth.account_emails.send_password_reset_email", _mail)
    recruiter = await partner(db, "GOLD")
    invite = await _call(db, user("partner_admin", recruiter), "POST", "/api/v1/partner/network/invites", json={})
    token = invite.json()["token"]
    assert (await _call(db, None, "GET", f"/api/v1/partners/invites/{token}")).json()["recruiter"]
    email = f"apply-{uuid.uuid4().hex[:6]}@example.com"
    applied = await _call(db, None, "POST", "/api/v1/partners/apply", json={
        "token": token, "company_name": "New Reseller", "contact_name": "Asha", "email": email,
        "requested_type": "GOLD", "pan": "ABCDE1234F"})
    assert applied.status_code == 201, applied.text
    app_id = applied.json()["id"]
    staff = user("app_admin", await _platform(db))
    early = await _call(db, staff, "POST", f"/api/v1/admin/partners/applications/{app_id}/approve",
                        json={"partner_type": "SILVER"})
    assert early.status_code == 422 and "not complete" in early.text
    checklist = {k: True for k in ("identity_kyc", "business_kyc", "bank_verified", "sanctions_check",
                                   "no_duplicate", "territory_check", "agreement_reviewed")}
    await _call(db, staff, "POST", f"/api/v1/admin/partners/applications/{app_id}/review",
                json={"checklist": checklist})
    approved = await _call(db, staff, "POST", f"/api/v1/admin/partners/applications/{app_id}/approve",
                           json={"partner_type": "SILVER"})                 # BCL sets the type, not the applicant
    assert approved.status_code == 200, approved.text
    company_id = uuid.UUID(approved.json()["company_id"])
    profile = await db.get(PartnerProfile, company_id)
    assert (profile.partner_type, profile.status, profile.recruiter_partner_id, profile.depth, profile.pan) == (
        "SILVER", "approved", recruiter, 2, "ABCDE1234F")
    company = await db.get(Company, company_id)
    assert (company.type, company.parent_id) == ("PARTNER", recruiter)
    agreement = (await db.execute(select(PartnerAgreement).where(PartnerAgreement.partner_id == company_id))
                 ).scalar_one()
    assert agreement.terms["partner_type"] == "SILVER" and agreement.terms["commission_rules"]
    assert sent == [email]
    signed = await _call(db, user("partner_admin", company_id), "POST", "/api/v1/partner/me/agreement/sign")
    assert signed.json()["status"] == "active"                              # no fee due
    await db.refresh(profile)
    assert profile.probation_until > datetime.utcnow() + timedelta(days=80)


@pytest.mark.asyncio
async def test_a_partner_at_the_depth_limit_cannot_invite(db):
    p1 = await partner(db)
    p2 = await partner(db, recruiter=p1)
    p3 = await partner(db, recruiter=p2)
    res = await _call(db, user("partner_admin", p3), "POST", "/api/v1/partner/network/invites", json={})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_an_application_with_a_known_email_is_refused(db):
    data = {"company_name": "Dup", "contact_name": "Dee", "email": f"dup-{uuid.uuid4().hex[:6]}@example.com"}
    assert (await _call(db, None, "POST", "/api/v1/partners/apply", json=data)).status_code == 201
    assert (await _call(db, None, "POST", "/api/v1/partners/apply", json=data)).status_code == 409


# ── leads (T8-9) ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leads_are_exclusive_and_convert_to_customers(db, monkeypatch):
    async def _mail(*a):
        return None

    monkeypatch.setattr("src.auth.account_emails.send_password_reset_email", _mail)
    silver = await partner(db, "SILVER")
    other = await partner(db, "GOLD")
    domain = f"acme{uuid.uuid4().hex[:6]}.in"
    first = await _call(db, user("partner_user", silver), "POST", "/api/v1/partner/leads",
                        json={"company_name": f"Acme {domain}", "email": f"ceo@{domain}"})
    assert first.status_code == 201
    dup = await _call(db, user("partner_admin", other), "POST", "/api/v1/partner/leads",
                      json={"company_name": "Acme Again", "email": f"cto@{domain}"})
    assert dup.status_code == 409 and "already registered" in dup.text
    staff = user("app_admin", await _platform(db))
    lead_id = first.json()["id"]
    assert (await _call(db, user("partner_admin", silver), "POST", f"/api/v1/partner/leads/{lead_id}/convert",
                        json={})).status_code == 403                       # BCL converts a Silver lead
    done = await _call(db, staff, "POST", f"/api/v1/admin/partners/leads/{lead_id}/convert", json={})
    assert done.status_code == 200, done.text
    t = uuid.UUID(done.json()["tenant_id"])
    assignment = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == t))).scalar_one()
    assert (assignment.partner_id, assignment.relationship, assignment.source, assignment.commission_until) == (
        silver, "referred", "lead", None)
    assert (await db.get(Company, t)).parent_id == await _platform(db)
    assert (await db.get(PartnerLead, uuid.UUID(lead_id))).status == "converted"


@pytest.mark.asyncio
async def test_a_gold_partner_converts_its_own_lead_as_resold(db, monkeypatch):
    async def _mail(*a):
        return None

    monkeypatch.setattr("src.auth.account_emails.send_password_reset_email", _mail)
    gold = await partner(db, "GOLD")
    lead = await _call(db, user("partner_admin", gold), "POST", "/api/v1/partner/leads",
                       json={"company_name": f"Gold lead {uuid.uuid4().hex[:6]}"})
    done = await _call(db, user("partner_admin", gold), "POST", f"/api/v1/partner/leads/{lead.json()['id']}/convert",
                       json={})
    assert done.status_code == 200, done.text
    t = uuid.UUID(done.json()["tenant_id"])
    assert t in await data_scope(db, gold)
    assert (await db.execute(select(PartnerAccessGrant).where(PartnerAccessGrant.tenant_id == t))).scalar_one()


# ── reassignment and termination (T8-11) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_a_move_splits_attribution_at_its_date(db):
    a = await partner(db, "GOLD")
    b = await partner(db, "GOLD")
    t = await tenant(db, a, since_days_ago=60)
    move = datetime.utcnow() - timedelta(days=10)
    staff = user("app_admin", await _platform(db))
    res = await _call(db, staff, "POST", "/api/v1/admin/partners/assignments/reassign", json={
        "tenant_id": str(t), "partner_id": str(b), "relationship": "resold", "effective_from": move.isoformat(),
        "reason": "test: the customer moved"})
    assert res.status_code == 200, res.text
    before = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000), currency="INR",
                                         source_type="payment", source_id="old", at=move - timedelta(days=5))
    after = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000), currency="INR",
                                        source_type="payment", source_id="new", at=datetime.utcnow())
    assert [r.partner_id for r in before] == [a] and [r.partner_id for r in after] == [b]
    old_grant = (await db.execute(select(PartnerAccessGrant).where(PartnerAccessGrant.partner_id == a,
                                                                   PartnerAccessGrant.tenant_id == t))).first()
    assert old_grant is None or old_grant[0].status == "revoked"
    assert (await db.get(Company, t)).parent_id == b


@pytest.mark.asyncio
async def test_termination_moves_tenants_to_bcl_and_forfeits_unpaid_earnings(db):
    gold = await partner(db, "GOLD")
    t = await tenant(db, gold)
    db.add(PartnerAccessGrant(partner_id=gold, tenant_id=t, scopes=["admin"], status="active"))
    [earned] = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000),
                                           currency="INR", source_type="payment", source_id="term")
    staff = user("app_admin", await _platform(db))
    res = await _call(db, staff, "POST", f"/api/v1/admin/partners/{gold}/status",
                      json={"status": "terminated", "reason": "test: breach"})
    assert res.status_code == 200 and res.json()["tenants"] == 1
    await db.refresh(earned)
    assert earned.status == "reversed"
    assert (await db.get(Company, t)).parent_id == await _platform(db)
    assert (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == t,
                                                             PartnerAssignment.until.is_(None)))).first() is None
    assert all(g.status == "revoked" for g in (await db.execute(select(PartnerAccessGrant).where(
        PartnerAccessGrant.partner_id == gold))).scalars().all())


@pytest.mark.asyncio
async def test_staff_change_a_gold_partner_to_silver(db):
    """A type change (09 §5 "not exposed" in M15.4): Silver's rules from now and a new agreement; a Gold
    partner's resold tenants become its referred customers — attribution kept, grants revoked."""
    gold = await partner(db, "GOLD")
    t = await tenant(db, gold, since_days_ago=30)
    db.add(PartnerAccessGrant(partner_id=gold, tenant_id=t, scopes=["admin"], status="active"))
    await db.flush()
    staff = user("app_admin", await _platform(db))
    assert (await _call(db, user("partner_admin", gold), "POST", f"/api/v1/admin/partners/{gold}/type",
                        json={"partner_type": "SILVER", "reason": "test"})).status_code == 403
    res = await _call(db, staff, "POST", f"/api/v1/admin/partners/{gold}/type",
                      json={"partner_type": "silver", "reason": "test: delivers no more"})
    assert res.status_code == 200, res.text
    assert res.json()["converted_to_referred"] == [str(t)]
    profile = await db.get(PartnerProfile, gold)
    assert profile.partner_type == "SILVER"
    agreement = (await db.execute(select(PartnerAgreement).where(PartnerAgreement.partner_id == gold))).scalar_one()
    assert agreement.version == res.json()["agreement_version"] and agreement.signed_at is None
    [current] = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == t,
                                                                  PartnerAssignment.until.is_(None)))).scalars().all()
    assert (current.partner_id, current.relationship) == (gold, "referred")
    assert all(g.status == "revoked" for g in (await db.execute(select(PartnerAccessGrant).where(
        PartnerAccessGrant.partner_id == gold))).scalars().all())
    assert (await db.get(Company, t)).parent_id == await _platform(db)
    assert t not in await data_scope(db, gold)                      # a Silver partner sees no tenant data
    [earned] = await commission.distribute(db, tenant_id=t, revenue_kind="usage_topup", base=D(1000),
                                           currency="INR", source_type="payment", source_id="after-type")
    assert earned.partner_id == gold                                 # still its customer, at Silver's rate
    again = await _call(db, staff, "POST", f"/api/v1/admin/partners/{gold}/type",
                        json={"partner_type": "SILVER", "reason": "test"})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_silver_to_gold_leaves_referred_customers_with_bcl(db):
    silver = await partner(db, "SILVER")
    t = await tenant(db, silver, "referred")
    res = await _call(db, user("app_admin", await _platform(db)), "POST", f"/api/v1/admin/partners/{silver}/type",
                      json={"partner_type": "GOLD", "reason": "test: now delivers"})
    assert res.status_code == 200 and res.json()["converted_to_referred"] == []
    assert (await db.get(PartnerProfile, silver)).partner_type == "GOLD"
    [current] = (await db.execute(select(PartnerAssignment).where(PartnerAssignment.tenant_id == t,
                                                                  PartnerAssignment.until.is_(None)))).scalars().all()
    assert current.relationship == "referred" and t not in await data_scope(db, silver)


@pytest.mark.asyncio
async def test_a_tenant_named_in_the_body_needs_a_grant_too(db, own_sessions):
    """Managing a resold tenant's people names the tenant in the body, not ``X-Company-Id``: the same
    grant check applies (09 §5: only the header was grant-checked)."""
    gold = await partner(db, "GOLD")
    t = await tenant(db, gold)
    admin = user("partner_admin", gold)

    def body():
        return {"email": f"p15-{uuid.uuid4().hex[:8]}@example.com", "password": "Correct-Horse-Battery-9",
                "full_name": "Someone", "role": "tenant_user", "company_id": str(t)}

    refused = await _call(db, admin, "POST", "/api/v1/users", json=body())
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "no_access_grant"
    grant = PartnerAccessGrant(partner_id=gold, tenant_id=t, scopes=["read"], status="active")
    db.add(grant)
    await db.flush()
    read_only = await _call(db, admin, "POST", "/api/v1/users", json=body())
    assert read_only.status_code == 403 and read_only.json()["detail"]["code"] == "grant_scope"
    grant.scopes = ["support"]
    await db.flush()
    made = await _call(db, admin, "POST", "/api/v1/users", json=body())
    assert made.status_code == 200, made.text
    from sqlalchemy import delete

    from src.common.tenancy.session import control_session
    async with control_session() as other:                   # the audit rows, written in a session of their own
        await other.execute(delete(PartnerAccessEvent).where(PartnerAccessEvent.tenant_id == t))
        await other.commit()


@pytest.mark.asyncio
async def test_the_migration_backfill(db):
    """control_0020's backfill, run again on rows made here: a partner and its tenant become a Gold
    profile at depth 1, a resold assignment and an admin grant."""
    from pathlib import Path
    import re

    from sqlalchemy import text

    p = Company(name="legacy partner", type="PARTNER", status="active", billing_currency="INR", country_code="IN")
    db.add(p)
    await db.flush()
    t = Company(name="legacy tenant", type="TENANT", status="active", parent_id=p.id, billing_currency="INR",
                country_code="IN")
    db.add(t)
    await db.flush()
    source = Path("migrations/control/versions/control_0020_partners.py").read_text(encoding="utf-8")
    statements = re.findall(r'op\.execute\("""(.*?)"""\)', source, flags=re.S)
    backfill = [s for s in statements if "partner_profiles" in s.split("INSERT INTO", 1)[-1][:40]
                or "INTO partner_assignments" in s or "INTO partner_access_grants" in s]
    assert len(backfill) == 3
    for sql in backfill:
        await db.execute(text(sql.replace("FROM companies c WHERE c.type = 'PARTNER'",
                                          f"FROM companies c WHERE c.type = 'PARTNER' AND c.id = '{p.id}'")
                              .replace("WHERE t.type = 'TENANT' AND p.type = 'PARTNER'",
                                       f"WHERE t.type = 'TENANT' AND p.type = 'PARTNER' AND t.id = '{t.id}'")
                              .replace("WHERE relationship = 'resold' AND until IS NULL",
                                       f"WHERE relationship = 'resold' AND until IS NULL AND tenant_id = '{t.id}'")))
    profile = await db.get(PartnerProfile, p.id)
    assert (profile.partner_type, profile.status, profile.depth, profile.kyc_status) == ("GOLD", "active", 1,
                                                                                         "pending")
    assert (await db.execute(select(PartnerAssignment.relationship).where(PartnerAssignment.tenant_id == t.id))
            ).scalar_one() == "resold"
    assert (await db.execute(select(PartnerAccessGrant.scopes).where(PartnerAccessGrant.tenant_id == t.id))
            ).scalar_one() == ["admin"]
