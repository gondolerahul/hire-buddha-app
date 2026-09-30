"""An artifact's campaign_id is a campaign, and only the uploader's own (DM-18).

The foreign key pointed at hierarchical_entities, so a real campaign id was
refused and an entity id accepted. And the upload attached a file to any
campaign or agent id it was given, another company's included.

Real Postgres, rolled back; the file itself is written to a temp directory.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from src.common.orm_models import import_all_models

import_all_models()  # campaign models reference voice models by name
pytestmark = pytest.mark.needs_db


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"dm18-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c


async def _campaign(db, company_id):
    from src.ai.campaign_models import Campaign
    from src.ai.orm.entity import HierarchicalEntity
    agent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name=f"dm18-{uuid.uuid4().hex[:6]}")
    db.add(agent)
    await db.flush()
    from src.auth.models import User
    creator = User(email=f"dm18-{uuid.uuid4().hex[:8]}@example.com", full_name="c", hashed_password="x",
                   company_id=company_id, role="tenant_admin")
    db.add(creator)
    await db.flush()
    campaign = Campaign(company_id=company_id, agent_id=agent.id, created_by=creator.id, name="dm18 campaign",
                        status="draft", contact_list=[])
    db.add(campaign)
    await db.flush()
    return campaign, agent


@pytest.mark.asyncio
async def test_the_key_references_campaigns(db):
    from src.ai.artifact_models import Artifact

    company = await _company(db)
    campaign, agent = await _campaign(db, company.id)
    ok = Artifact(company_id=company.id, campaign_id=campaign.id, origin="user-uploads",
                  file_category="documents", file_name="a.txt", file_path="/tmp/a.txt")
    db.add(ok)
    await db.flush()
    wrong = Artifact(company_id=company.id, campaign_id=agent.id, origin="user-uploads",
                     file_category="documents", file_name="b.txt", file_path="/tmp/b.txt")
    db.add(wrong)
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_upload_refuses_another_companys_campaign_or_agent(db, monkeypatch, tmp_path):
    from src.ai import artifact_router
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    mine, theirs = await _company(db), await _company(db)
    their_campaign, their_agent = await _campaign(db, theirs.id)
    my_campaign, my_agent = await _campaign(db, mine.id)

    app = FastAPI()
    app.include_router(artifact_router.router)
    user = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=mine.id)

    async def _user():
        return user

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    saved = []

    async def fake_save(self, **kwargs):
        saved.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), company_id=mine.id, campaign_id=kwargs.get("campaign_id"),
                               agent_id=kwargs.get("agent_id"), run_id=None, origin="user-uploads",
                               file_category="documents", file_name="f.txt", file_path=str(tmp_path / "f.txt"),
                               file_size=1, duration_seconds=None, mime_type="text/plain", purpose=None,
                               generated_by="user-upload", artifact_metadata=None, created_at=datetime.utcnow())

    monkeypatch.setattr(artifact_router.ArtifactService, "save_upload", fake_save)

    async def upload(**form):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/api/v1/artifacts/upload", files={"file": ("f.txt", b"x", "text/plain")},
                                data={"file_category": "documents", **{k: str(v) for k, v in form.items()}})

    assert (await upload(campaign_id=their_campaign.id)).status_code == 404
    assert (await upload(agent_id=their_agent.id)).status_code == 404
    assert saved == []
    res = await upload(campaign_id=my_campaign.id, agent_id=my_agent.id)
    assert res.status_code == 200 and saved[0]["campaign_id"] == my_campaign.id
