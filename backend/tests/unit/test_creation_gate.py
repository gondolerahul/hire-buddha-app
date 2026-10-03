"""An entity an agent creates passes one gate, in the creation service
(P10.3 — MI-02, MI-03, D28).

The anti-sprawl gates were advice that ``meta_entity_creator`` honoured in
CREATE mode only; its VERSION mode, and any other path, skipped them. Ten
entities could be created in ten seconds.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.ai.governance import creation_gate
from src.ai.governance.creation_gate import CreationRefused, require_agent_creation


class _Guard:
    """Stands in for AntiSprawlGuard; each answer is set per test."""
    daily = {"allowed": True, "message": ""}
    chain = {"needs_consolidation": False, "adaptation_count": 0, "threshold": 3, "versions": []}
    dup = {"is_duplicate": False, "message": ""}
    seen: list = []

    def __init__(self, db, company_id):
        pass

    async def check_creation_allowed(self, user_id=None):
        _Guard.seen.append("daily")
        return _Guard.daily

    async def check_consolidation_needed(self, source_entity_id):
        _Guard.seen.append("chain")
        return _Guard.chain

    async def check_semantic_duplicate(self, **kw):
        _Guard.seen.append("dup")
        return _Guard.dup


class _Limiter:
    def __init__(self, allow=True):
        self.allow, self.calls = allow, []

    async def check_and_consume(self, **kw):
        self.calls.append(kw)
        return self.allow


@pytest.fixture
def gates(monkeypatch):
    import src.ai.meta.anti_sprawl as anti_sprawl

    _Guard.daily = {"allowed": True, "message": ""}
    _Guard.chain = {"needs_consolidation": False, "adaptation_count": 0, "threshold": 3, "versions": []}
    _Guard.dup = {"is_duplicate": False, "message": ""}
    _Guard.seen = []
    limiter = _Limiter()
    monkeypatch.setattr(anti_sprawl, "AntiSprawlGuard", _Guard)
    monkeypatch.setattr(creation_gate, "_limiter", lambda: limiter)
    return limiter


PAYLOAD = {"type": "AGENT", "name": "n", "description": "triage support email",
           "capabilities": {"tools": [{"tool_id": "email_ingest"}]}}


@pytest.mark.asyncio
async def test_a_burst_is_refused_and_an_outage_refuses_too(gates):
    gates.allow = False
    with pytest.raises(CreationRefused) as err:
        await require_agent_creation(None, uuid.uuid4(), PAYLOAD)
    assert err.value.gate == "burst_limit"
    (call,) = gates.calls
    assert (call["limit"], call["window_seconds"], call["fail_open"]) == (3, 60, False)


@pytest.mark.asyncio
async def test_the_daily_limit_and_a_duplicate_refuse(gates):
    _Guard.daily = {"allowed": False, "message": "Daily creation limit reached (10/10)."}
    with pytest.raises(CreationRefused) as err:
        await require_agent_creation(None, uuid.uuid4(), PAYLOAD)
    assert err.value.gate == "daily_limit"

    _Guard.daily = {"allowed": True, "message": ""}
    _Guard.dup = {"is_duplicate": True, "message": "Near-duplicate", "existing_entity_id": "e1"}
    with pytest.raises(CreationRefused) as err:
        await require_agent_creation(None, uuid.uuid4(), PAYLOAD)
    assert (err.value.gate, err.value.details["existing_entity_id"]) == ("semantic_duplicate", "e1")


@pytest.mark.asyncio
async def test_a_new_version_checks_the_adaptation_chain_it_never_ran(gates):
    _Guard.chain = {"needs_consolidation": True, "adaptation_count": 3, "threshold": 3, "versions": [{"id": "v"}]}
    with pytest.raises(CreationRefused) as err:
        await require_agent_creation(None, uuid.uuid4(), PAYLOAD, source_entity_id=uuid.uuid4())
    assert err.value.gate == "adaptation_chain"
    assert "dup" not in _Guard.seen  # a version of an entity is not its duplicate


@pytest.mark.asyncio
async def test_the_creation_service_gates_agents_not_people(monkeypatch):
    from src.ai import service as service_mod
    from src.ai.schemas import HierarchicalEntityCreate

    calls = []

    async def gate(db, company_id, payload, **kw):
        calls.append(kw)
        raise CreationRefused("daily_limit", "no")

    monkeypatch.setattr(creation_gate, "require_agent_creation", gate)
    svc = service_mod.AIService(SimpleNamespace())
    entity = HierarchicalEntityCreate.model_validate({"type": "AGENT", "name": "n"})
    with pytest.raises(CreationRefused):
        await svc.create_entity(entity, uuid.uuid4(), origin="agent")
    assert calls == [{"user_id": None, "source_entity_id": None}]

    async def no_composition_check(*_a, **_kw):
        raise RuntimeError("reached the person's path")

    monkeypatch.setattr(svc, "_require_composition", no_composition_check)
    with pytest.raises(RuntimeError, match="person's path"):
        await svc.create_entity(entity, uuid.uuid4())   # a person: no gate
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_tool_reports_the_refusal(monkeypatch):
    import json

    from src.ai import service as service_mod
    from src.ai.tools.meta.entity_creator import MetaEntityCreatorTool

    async def refuse(self, *a, **kw):
        assert kw["origin"] == "agent"
        raise CreationRefused("burst_limit", "slow down")

    monkeypatch.setattr(service_mod.AIService, "create_entity", refuse)
    out = json.loads(await MetaEntityCreatorTool()._create_entity(
        {"entity_payload": {"type": "AGENT", "name": "n"}}, SimpleNamespace(), uuid.uuid4(), None))
    assert out == {"success": False, "error": "slow down", "gate": "burst_limit"}


@pytest.mark.asyncio
async def test_the_limiter_refuses_on_an_outage_when_asked_to():
    from src.ai.governance.rate_limiter import RedisRateLimiter

    class _Down:
        def pipeline(self):
            raise ConnectionError("redis down")

    limiter = RedisRateLimiter(_Down())
    assert await limiter.check_and_consume(key="k", limit=3, window_seconds=60, fail_open=False) is False
    assert await limiter.check_and_consume(key="k", limit=3, window_seconds=60) is True  # its old default
    assert await RedisRateLimiter(None).check_and_consume(key="k", limit=3, window_seconds=60, fail_open=False) is False
