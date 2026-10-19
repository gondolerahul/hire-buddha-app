"""A campaign is read and controlled only by the companies that may see it.

Before: ``GET /campaigns/{id}``, ``/{id}/status``, ``/{id}/active-calls``,
``/{id}/download`` and ``PATCH /{id}/status`` looked a campaign up by id alone,
so with one shared database (``TENANCY_MODE=single``) any signed-in user who
knew an id could read its calls and contacts, download its report, or start and
stop it; ``POST /campaigns`` took any company's agent, dialling on that
company's number and credit. Now each follows ``auth.visibility``: the caller's
own company, a partner's tenants, every company for an app admin — anything
else is 404, so an id is not confirmed. Real Postgres, rolled back.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

import src.main  # noqa: F401  (every model mapped: campaign calls refer to voice sessions)

pytestmark = pytest.mark.needs_db

ROUTES = [
    ("GET", "/api/v1/campaigns/{id}"),
    ("GET", "/api/v1/campaigns/{id}/status"),
    ("GET", "/api/v1/campaigns/{id}/active-calls"),
    ("GET", "/api/v1/campaigns/{id}/download"),
    ("PATCH", "/api/v1/campaigns/{id}/status?status=paused"),
    ("PATCH", "/api/v1/campaigns/{id}/status?status=running"),
]


async def _company(db, kind="TENANT", parent=None):
    from src.auth.models import Company

    company = Company(name=f"own-{uuid.uuid4().hex[:6]}", type=kind, status="active", parent_id=parent)
    db.add(company)
    await db.flush()
    return company.id


async def _campaign(db, company_id):
    from src.ai.campaign_models import Campaign, CampaignCall
    from src.ai.orm.entity import HierarchicalEntity

    agent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE",
                               name=f"own-{uuid.uuid4().hex[:6]}")
    db.add(agent)
    await db.flush()
    campaign = Campaign(company_id=company_id, created_by=uuid.uuid4(), agent_id=agent.id, name="ownership",
                        total_contacts=1, contact_list=[{"phone": "+15550000001"}], provider="twilio",
                        status="draft")
    db.add(campaign)
    await db.flush()
    db.add(CampaignCall(campaign_id=campaign.id, contact_data={"phone": "+15550000001", "name": "Lead"},
                        status="pending"))
    await db.flush()
    return campaign.id, agent.id


@pytest.fixture
def world(db, monkeypatch):
    """The campaign router on the test session; jobs recorded, not queued."""
    from src.ai import campaign_router
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    caller = {"user": None}
    queued = []

    async def _user():
        return caller["user"]

    async def _db():
        yield db

    async def _enqueue(function, *args, **kwargs):
        queued.append((function, args, kwargs))
        return SimpleNamespace(job_id="test")

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)

    async def call(user, method, path, **kwargs):
        caller["user"] = user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.request(method, path, **kwargs)

    return SimpleNamespace(call=call, queued=queued)


def _person(company_id, role="tenant_admin"):
    return SimpleNamespace(id=uuid.uuid4(), company_id=company_id, role=role, email="own@test.local")


async def _status(db, campaign_id):
    from src.ai.campaign_models import Campaign

    return (await db.execute(select(Campaign.status).where(Campaign.id == campaign_id)
                             .execution_options(populate_existing=True))).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize("method, path", ROUTES)
async def test_another_companys_campaign_is_not_found(db, world, method, path):
    owner, stranger = await _company(db), await _company(db)
    campaign_id, _ = await _campaign(db, owner)

    refused = await world.call(_person(stranger), method, path.format(id=campaign_id))
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "Campaign not found"
    assert world.queued == [] and await _status(db, campaign_id) == "draft"   # nothing started, nothing changed

    allowed = await world.call(_person(owner), method, path.format(id=campaign_id))
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_a_partner_reaches_its_tenants_campaigns_and_no_one_elses(db, world):
    partner = await _company(db, "PARTNER")
    tenant, outsider = await _company(db, parent=partner), await _company(db)
    tenants_campaign, _ = await _campaign(db, tenant)
    outsiders_campaign, _ = await _campaign(db, outsider)
    partner_admin = _person(partner, role="partner_admin")

    assert (await world.call(partner_admin, "GET", f"/api/v1/campaigns/{tenants_campaign}")).status_code == 200
    started = await world.call(partner_admin, "PATCH", f"/api/v1/campaigns/{tenants_campaign}/status",
                               params={"status": "running"})
    assert started.status_code == 200, started.text
    # The job carries the campaign's company (the tenant), not the partner's.
    assert world.queued == [("execute_campaign_task", (str(tenants_campaign),), {"company_id": str(tenant)})]
    assert (await world.call(partner_admin, "GET", f"/api/v1/campaigns/{outsiders_campaign}")).status_code == 404

    # An app admin sees every company's.
    app_admin = _person(uuid.uuid4(), role="app_admin")
    assert (await world.call(app_admin, "GET", f"/api/v1/campaigns/{outsiders_campaign}")).status_code == 200


@pytest.mark.asyncio
async def test_a_campaign_cannot_be_made_on_another_companys_agent(db, world):
    from src.ai.campaign_models import Campaign

    mine, theirs = await _company(db), await _company(db)
    _, my_agent = await _campaign(db, mine)
    _, their_agent = await _campaign(db, theirs)
    body = {"name": "borrowed", "contact_list": [{"phone": "+15550000002", "name": "Lead"}]}

    refused = await world.call(_person(mine), "POST", "/api/v1/campaigns", json={**body, "agent_id": str(their_agent)})
    assert refused.status_code == 404 and refused.json()["detail"] == "Agent not found"
    made = (await db.execute(select(Campaign.id).where(Campaign.name == "borrowed"))).first()
    assert made is None

    created = await world.call(_person(mine), "POST", "/api/v1/campaigns", json={**body, "agent_id": str(my_agent)})
    assert created.status_code == 200, created.text
    campaign = await db.get(Campaign, uuid.UUID(created.json()["id"]))
    assert campaign.company_id == mine and campaign.agent_id == my_agent
