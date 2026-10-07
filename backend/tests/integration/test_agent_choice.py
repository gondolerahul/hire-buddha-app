"""GW-17 on Postgres: an event or a socket runs one agent, chosen the same way every time.

``LIMIT 1`` with no order over the company's non-archived entities could pick a
child step, a draft or a soft-deleted agent, and a different one per delivery.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from src.gateway.agent_choice import choose_agent

pytestmark = pytest.mark.needs_db


@pytest_asyncio.fixture
async def company(db):
    from src.auth.models import Company

    c = Company(name=f"gw17-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c


async def _entity(db, company, name, **fields):
    from src.ai.orm import HierarchicalEntity

    e = HierarchicalEntity(company_id=company.id, type=fields.pop("type", "AGENT"),
                           status=fields.pop("status", "ACTIVE"), name=name, **fields)
    db.add(e)
    await db.flush()
    return e


@pytest.mark.asyncio
async def test_the_only_active_agent_is_chosen(db, company):
    agent = await _entity(db, company, "inbox")
    await _entity(db, company, "step", parent_id=agent.id, type="ACTION")      # a child
    await _entity(db, company, "draft", status="DRAFT")
    await _entity(db, company, "old", status="ARCHIVED")
    await _entity(db, company, "gone", deleted_at=datetime.utcnow())
    await _entity(db, company, "blueprint", is_template=True)
    choice = await choose_agent(db, company.id)
    assert choice.entity is not None and choice.entity.id == agent.id


@pytest.mark.asyncio
async def test_several_agents_are_refused_not_guessed(db, company):
    await _entity(db, company, "sales")
    await _entity(db, company, "support")
    choice = await choose_agent(db, company.id)
    assert choice.entity is None
    assert choice.error == "ambiguous_agent"
    assert "entity_id" in choice.detail


@pytest.mark.asyncio
async def test_a_named_agent_wins(db, company):
    await _entity(db, company, "sales")
    support = await _entity(db, company, "support")
    choice = await choose_agent(db, company.id, [None, str(support.id)])
    assert choice.entity.id == support.id


@pytest.mark.asyncio
async def test_a_name_that_does_not_resolve_is_refused(db, company):
    from src.auth.models import Company

    other = Company(name=f"gw17o-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(other)
    await db.flush()
    await _entity(db, company, "only")
    theirs = await _entity(db, other, "theirs")
    draft = await _entity(db, company, "draft", status="DRAFT")
    for name in (str(theirs.id), str(draft.id), "not-a-uuid"):
        choice = await choose_agent(db, company.id, [name])
        assert (choice.entity, choice.error) == (None, "unknown_agent"), name


@pytest.mark.asyncio
async def test_no_agent(db, company):
    assert (await choose_agent(db, company.id)).error == "no_agent"
