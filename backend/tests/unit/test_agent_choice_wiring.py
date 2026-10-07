"""GW-17: the worker and the sockets ask ``choose_agent``, with names in the right order.

The choice itself is tested on Postgres (``tests/integration/test_agent_choice.py``).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.gateway import agent_choice
from src.gateway.agent_choice import AgentChoice


class _Session:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def asked(monkeypatch):
    calls: list[list] = []

    async def choose(db, company_id, named=()):
        calls.append(list(named))
        return AgentChoice(error="ambiguous_agent", detail="several")

    monkeypatch.setattr(agent_choice, "choose_agent", choose)
    return calls


@pytest.mark.asyncio
async def test_the_endpoints_binding_comes_before_the_events_entity_id(monkeypatch, asked):
    from src.ai.core import arq_jobs

    monkeypatch.setattr(arq_jobs, "AsyncSessionLocal", lambda: _Session())
    bound, sent = str(uuid.uuid4()), str(uuid.uuid4())
    await arq_jobs.process_gateway_event({}, {
        "client_id": str(uuid.uuid4()), "event_type": "lead.created", "source": "crm",
        "raw_data": {"entity_id": sent, "raw": {}}, "metadata": {"entity_id": bound},
    })
    assert asked == [[bound, sent]]


@pytest.mark.asyncio
async def test_a_refused_choice_reaches_the_socket(monkeypatch, asked):
    from src.common import database
    from src.gateway.dispatcher import CentralDispatcher

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session())
    info = await CentralDispatcher().resolve_agent_for_client(str(uuid.uuid4()), "audio", "a1")
    assert info == {"error": "ambiguous_agent", "message": "several"}
    assert asked == [["a1"]]
