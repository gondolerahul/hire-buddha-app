"""What the foreign keys between control and tenant tables did, now done by the
services (Phase 14 WS2 2.3, tech spec §5.3 rule 2).

The keys are gone (migration ``p14_drop_cross_plane_fks``), so a control row
may name a tenant row that this database does not hold — in split mode it is
in the tenant's own database. Where an id comes from a caller it is checked,
and the code that deletes rows does the keys' ON DELETE actions. The test
purge's share is in ``test_purge_companies.py``. Rolled back like every
integration test.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.needs_db


async def _company(db):
    from src.auth.models import Company

    company = Company(name=f"p14-refs-{uuid.uuid4().hex[:8]}", type="TENANT", status="active")
    db.add(company)
    await db.flush()
    return company.id


async def _agent(db, company_id):
    from src.ai.orm.entity import HierarchicalEntity

    agent = HierarchicalEntity(company_id=company_id, type="AGENT", status="ACTIVE", name="p14-refs")
    db.add(agent)
    await db.flush()
    return agent.id


def _number() -> str:
    return f"+1555{uuid.uuid4().int % 10_000_000:07d}"


async def test_a_number_may_name_an_agent_this_database_does_not_hold(db):
    """What split-mode voice needs: the number (control) names an agent in a tenant database."""
    from src.voice.phone_pool_models import PhoneNumber

    company = await _company(db)
    db.add(PhoneNumber(phone_number=_number(), provider="twilio", country_code="+1", status="assigned",
                       is_active=True, company_id=company, agent_id=uuid.uuid4()))
    await db.flush()


async def test_a_number_is_assigned_only_to_an_agent_of_its_company(db):
    from src.voice.number_router import NumberRouter

    mine, theirs = await _company(db), await _company(db)
    agent = await _agent(db, theirs)
    router, number = NumberRouter(db), _number()

    for company, agent_id in ((mine, agent), (theirs, uuid.uuid4())):
        with pytest.raises(ValueError, match="is not an agent of company"):
            await router.assign_number_to_customer(company, uuid.uuid4(), "c", agent_id, number,
                                                   provider="twilio")
    entry = await router.assign_number_to_customer(theirs, uuid.uuid4(), "c", agent, number,
                                                   provider="twilio")
    assert (entry.company_id, entry.agent_id, entry.status) == (theirs, agent, "assigned")


async def test_deleting_entities_does_what_the_keys_did_on_delete(db):
    """The meta-agent reseed's hard delete: a run's credit hold goes with it
    (was ON DELETE CASCADE), a webhook endpoint lets go of the agent (was
    ON DELETE SET NULL)."""
    from src.ai.meta.seed_meta_agent import _purge_entities
    from src.ai.orm.execution import ExecutionRun
    from src.billing.billing_models import CreditHold
    from src.gateway.models import WebhookEndpoint

    company = await _company(db)
    agent = await _agent(db, company)
    # Raw SQL: an ORM insert pins an entity version, which _purge_entities
    # does not delete (it predates versions) — not what this test is about.
    run_id = uuid.uuid4()
    await db.execute(text("INSERT INTO execution_runs (id, entity_id, company_id, status, input_data) "
                          "VALUES (:id, :e, :c, 'COMPLETED', '{}')"), {"id": run_id, "e": agent, "c": company})
    endpoint = WebhookEndpoint(company_id=company, source="generic", name="p14-refs",
                               secret_encrypted="x", entity_id=agent)
    db.add_all([CreditHold(company_id=company, run_id=run_id, amount=1), endpoint])
    await db.flush()

    await _purge_entities(db, [str(agent)])

    assert await db.scalar(select(func.count()).select_from(ExecutionRun).where(ExecutionRun.id == run_id)) == 0
    assert await db.scalar(select(func.count()).select_from(CreditHold).where(CreditHold.run_id == run_id)) == 0
    await db.refresh(endpoint)
    assert endpoint.entity_id is None


async def test_deleting_an_agent_a_number_is_assigned_to_is_refused(db):
    """phone_numbers.agent_id refused the delete; the delete still refuses."""
    from src.ai.meta.seed_meta_agent import _purge_entities
    from src.ai.orm.entity import HierarchicalEntity
    from src.voice.phone_pool_models import PhoneNumber

    company = await _company(db)
    agent = await _agent(db, company)
    db.add(PhoneNumber(phone_number=_number(), provider="twilio", country_code="+1", status="assigned",
                       is_active=True, company_id=company, agent_id=agent))
    await db.flush()

    with pytest.raises(RuntimeError, match="unassign them first"):
        await _purge_entities(db, [str(agent)])
    assert await db.get(HierarchicalEntity, agent) is not None
