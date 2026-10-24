"""The inbound webhooks refuse a call the admission rule refuses (VT-01, HD9).

Both used to compare ``total_available`` with $0.10 and connect the call on
any error. The rule itself is tested on Postgres in
tests/integration/test_call_admission.py.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


class _Request:
    def __init__(self, form):
        self._form = form

    async def form(self):
        return self._form


class _Sessions:
    def __init__(self):
        self.db = object()
        self.created = []

    async def create_voice_session(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())


class _Numbers:
    def __init__(self, company_id):
        self.assignment = SimpleNamespace(company_id=company_id, customer_id=uuid.uuid4(),
                                          agent_id=uuid.uuid4(), phone_number="+15550001")

    async def find_customer_by_number(self, _number):
        return self.assignment


@pytest.fixture
def refused(monkeypatch):
    seen = []

    async def _refuse(db, company_id, *, direction, checkpoint, number=None):
        seen.append((company_id, direction, checkpoint))
        return "Cannot start execution: no free credit"

    async def _not_mobile(*_a, **_k):
        return None

    monkeypatch.setattr("src.voice.call_admission.call_refusal", _refuse)
    monkeypatch.setattr("src.mobile.identification.resolve_mobile_inbound", _not_mobile)
    return seen


@pytest.mark.asyncio
async def test_twilio_hangs_up_without_a_session(refused):
    from src.voice.webhook_router import twilio_incoming_call

    company, sessions = uuid.uuid4(), _Sessions()
    res = await twilio_incoming_call(
        _Request({"CallSid": "CA1", "From": "+15550002", "To": "+15550001", "CallStatus": "ringing"}),
        session_manager=sessions, number_router=_Numbers(company))
    assert b"<Hangup/>" in res.body and b"<Stream" not in res.body
    assert sessions.created == []
    assert refused == [(company, "inbound", "twilio_webhook")]


class _JsonRequest:
    headers = {"content-type": "application/json"}
    query_params: dict = {}

    def __init__(self, payload):
        self.payload = payload

    async def body(self):
        import json
        return json.dumps(self.payload).encode()

    async def json(self):
        return self.payload


@pytest.mark.asyncio
async def test_tata_refuses_without_a_session(refused):
    from src.voice.webhook_router import tata_incoming_call

    company, sessions = uuid.uuid4(), _Sessions()
    res = await tata_incoming_call(
        _JsonRequest({"callId": "T1", "fromNumber": "+15550002", "toNumber": "+15550001"}),
        session_manager=sessions, number_router=_Numbers(company))
    assert res["error"] == "This service is temporarily unavailable"
    assert sessions.created == []
    assert refused == [(company, "inbound", "tata_webhook")]
