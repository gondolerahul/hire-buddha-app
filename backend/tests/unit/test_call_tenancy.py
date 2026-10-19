"""A telephony request names its tenant first (Phase 14 WS2 2.12, ``voice/call_tenancy.py``).

Single mode changes nothing; split mode finds the tenant from a ``company=``
we handed the provider or from our own number on the call, and refuses a
call no tenant owns before any tenant database is read. The webhook and
stream paths against two real databases are in
``tests/integration/test_tenant_routing.py``.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.voice import call_tenancy


@pytest.fixture
def split(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "TENANCY_MODE", "split")


@pytest.fixture
def single(monkeypatch):
    from src.common.config import settings

    monkeypatch.setattr(settings, "TENANCY_MODE", "single")


class _Numbers:
    """Assigned numbers → company."""

    def __init__(self, owners):
        self.owners, self.asked = owners, []

    async def find_customer_by_number(self, number):
        self.asked.append(number)
        company = self.owners.get(number)
        return SimpleNamespace(company_id=company) if company else None


def test_media_stream_paths_name_the_company_only_in_split_mode(monkeypatch):
    from src.common.config import settings

    session = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4())
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    assert call_tenancy.media_stream_path("twilio", session) == f"/stream/twilio/{session.id}"
    assert call_tenancy.tenant_query(session.company_id) == ""
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    assert call_tenancy.media_stream_path("tata", session) == f"/stream/tata/{session.company_id}/{session.id}"
    assert call_tenancy.tenant_query(session.company_id) == f"company={session.company_id}"


def test_callback_urls_and_tata_references_name_the_company_only_in_split_mode(monkeypatch):
    from src.common.config import settings

    company, session = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(settings, "TENANCY_MODE", "single")
    assert call_tenancy.with_tenant("/webhooks/voice/twilio/status", company) == "/webhooks/voice/twilio/status"
    assert call_tenancy.call_reference(company, session) == str(session)
    monkeypatch.setattr(settings, "TENANCY_MODE", "split")
    assert call_tenancy.with_tenant("/status", company) == f"/status?company={company}"
    assert call_tenancy.with_tenant("/twiml?session_id=1", company) == f"/twiml?session_id=1&company={company}"
    assert call_tenancy.with_tenant("/status", None) == "/status"
    assert call_tenancy.call_reference(company, session) == f"{company}.{session}"


def test_a_tata_reference_reads_back_in_either_form():
    company, session = uuid.uuid4(), uuid.uuid4()
    assert call_tenancy.parse_call_reference(f"{company}.{session}") == (company, session)
    assert call_tenancy.parse_call_reference(str(session)) == (None, session)  # single mode, or older calls
    assert call_tenancy.parse_call_reference("null") == (None, None)
    assert call_tenancy.parse_call_reference(None) == (None, None)
    assert call_tenancy.parse_call_reference("not.an-id") == (None, None)


async def test_single_mode_never_looks_a_tenant_up(single):
    numbers = _Numbers({"+15550001": uuid.uuid4()})
    assert await call_tenancy.call_company(numbers, str(uuid.uuid4()), "+15550001") is None
    assert numbers.asked == []


async def test_a_company_we_handed_out_wins(split):
    named = uuid.uuid4()
    numbers = _Numbers({"+15550001": uuid.uuid4()})
    assert await call_tenancy.call_company(numbers, str(named), "+15550001") == named
    assert numbers.asked == []


async def test_otherwise_the_first_of_our_numbers_names_it(split):
    beta = uuid.uuid4()
    numbers = _Numbers({"+15550002": beta})
    assert await call_tenancy.call_company(numbers, "not-a-uuid", None, "+15550009", "whatsapp:+15550002") == beta
    assert numbers.asked == ["+15550009", "+15550002"]
    assert await call_tenancy.call_company(_Numbers({}), None, "+15550009") is None


async def test_the_session_manager_moves_to_the_tenant_only_in_split_mode(monkeypatch, split):
    from contextlib import asynccontextmanager

    opened = []

    @asynccontextmanager
    async def tenant_session(company_id):
        opened.append(company_id)
        yield "tenant-db"

    monkeypatch.setattr(call_tenancy, "tenant_session", tenant_session)
    original = SimpleNamespace(db="control-db", _redis="cache")
    company = uuid.uuid4()
    async with call_tenancy.tenant_session_manager(original, company) as manager:
        assert manager.db == "tenant-db" and manager._redis == "cache"
    assert opened == [company]


async def test_single_mode_keeps_the_session_manager(single):
    original = SimpleNamespace(db="db")
    async with call_tenancy.tenant_session_manager(original, uuid.uuid4()) as manager:
        assert manager is original


# ── the webhooks, split mode ───────────────────────────────────────────────

class _FormRequest:
    query_params: dict = {}

    def __init__(self, form):
        self._form = form

    async def form(self):
        return self._form


class _UnusedSessions:
    """A session manager no route may touch before the tenant is known."""

    db = None

    def __getattr__(self, name):
        raise AssertionError(f"the session manager was used ({name}) before the tenant was known")


async def test_split_mode_refuses_a_number_no_tenant_owns(split):
    from src.voice.webhook_router import twilio_incoming_call

    res = await twilio_incoming_call(
        _FormRequest({"CallSid": "CA1", "From": "+15550002", "To": "+15550001"}),
        session_manager=_UnusedSessions(), number_router=_Numbers({}))
    assert b"not configured" in res.body and b"<Stream" not in res.body


async def test_split_mode_drops_a_status_callback_no_tenant_owns(monkeypatch, split):
    from src.voice import webhook_router

    monkeypatch.setattr(webhook_router, "NumberRouter", lambda db: _Numbers({}))
    res = await webhook_router.twilio_status_callback(
        _FormRequest({"CallSid": "CA1", "CallStatus": "completed", "From": "+1", "To": "+2"}),
        session_manager=_UnusedSessions())
    assert res == {"status": "ok", "message": "No matching session found"}


# ── the Tata direct stream learns its tenant from the call ─────────────────

async def test_the_tata_stream_moves_to_the_tenant_of_its_did(monkeypatch, split):
    from src.voice import websocket_handler

    beta = uuid.uuid4()
    moved = []

    handler = websocket_handler.TataStreamHandler.__new__(websocket_handler.TataStreamHandler)
    handler.number_router = _Numbers({"+15550001": beta})

    async def _use_tenant(company_id):
        moved.append(company_id)
        raise _Stop  # the rest of the start event is the existing logic

    handler._use_tenant = _use_tenant
    with pytest.raises(_Stop):
        await handler._handle_tata_start_event(
            {"start": {"streamSid": "S1", "callSid": "C1", "from": "+15550009", "to": "+15550001"}})
    assert moved == [beta]


async def test_the_tata_stream_moves_to_the_tenant_its_reference_names(monkeypatch, split):
    """A campaign's click-to-call carries ``<company>.<session>``: that company
    wins over the numbers, which are not even looked up."""
    from src.voice import websocket_handler

    acme, beta = uuid.uuid4(), uuid.uuid4()
    moved = []
    handler = websocket_handler.TataStreamHandler.__new__(websocket_handler.TataStreamHandler)
    handler.number_router = _Numbers({"+15550001": beta})

    async def _use_tenant(company_id):
        moved.append(company_id)
        raise _Stop

    handler._use_tenant = _use_tenant
    with pytest.raises(_Stop):
        await handler._handle_tata_start_event({"start": {
            "from": "+15550009", "to": "+15550001",
            "customParameters": {"custom_identifier": f"{acme}.{uuid.uuid4()}"}}})
    assert moved == [acme] and handler.number_router.asked == []


async def test_the_tata_stream_gives_up_on_a_call_no_tenant_owns(split):
    from src.voice import websocket_handler

    handler = websocket_handler.TataStreamHandler.__new__(websocket_handler.TataStreamHandler)
    handler.number_router = _Numbers({})
    handler.session_manager = _UnusedSessions()
    await handler._handle_tata_start_event({"start": {"from": "+15550009", "to": "+15550001"}})
    assert getattr(handler, "session_id", None) is None


class _Stop(Exception):
    pass
