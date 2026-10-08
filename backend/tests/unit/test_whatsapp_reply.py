"""A WhatsApp reply comes from the model, not the apology (VT-03).

The handler called ``GeminiTextServiceFactory.get_service`` without its
required ``service_metadata``; the ``TypeError`` was caught and every customer
got "I'm currently unable to process your request". It now builds the service
on the company's Google integration (``from_company``). The factory also kept
one instance per project and model, with the first caller's system
instruction, so two agents would have shared one prompt.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.voice import gemini_text
from src.voice.gemini_text import GeminiTextServiceFactory


@pytest.mark.asyncio
async def test_a_reply_is_the_models_answer(monkeypatch):
    from src.voice.whatsapp_handler import WhatsAppHandler

    asked = []

    class _Service:
        async def generate_response(self, message, conversation_history=None, context=None):
            return {"response": f"Re: {message}"}

    async def _from_company(db, company_id, model=None, system_instruction=None, **kw):
        asked.append((company_id, model, system_instruction))
        return _Service()

    async def _context(**_kw):
        return SimpleNamespace(system_instruction="You are the clinic's receptionist.",
                               conversation_history=[], api_key=None)

    monkeypatch.setattr(GeminiTextServiceFactory, "from_company", staticmethod(_from_company))
    handler = WhatsAppHandler.__new__(WhatsAppHandler)
    handler.db = object()
    handler.agent_loader = SimpleNamespace(load_agent_for_session=_context)
    session = SimpleNamespace(agent_id=uuid.uuid4(), customer_id=uuid.uuid4(), company_id=uuid.uuid4())

    reply = await handler._generate_response(session, "Can I book Tuesday?")
    assert reply == "Re: Can I book Tuesday?"
    assert asked == [(session.company_id, "gemini-2.0-flash", "You are the clinic's receptionist.")]


def test_two_agents_on_one_project_do_not_share_a_prompt(monkeypatch):
    made = []

    class _Service:
        def __init__(self, service_metadata, model=None, system_instruction=None, **kw):
            made.append(system_instruction)
            self.system_instruction = system_instruction

    monkeypatch.setattr(gemini_text, "GeminiTextService", _Service)
    GeminiTextServiceFactory.clear_cache()
    meta = {"project_id": "p1"}
    a = GeminiTextServiceFactory.get_service(meta, model="m", system_instruction="agent A")
    b = GeminiTextServiceFactory.get_service(meta, model="m", system_instruction="agent B")
    again = GeminiTextServiceFactory.get_service(meta, model="m", system_instruction="agent A")
    GeminiTextServiceFactory.clear_cache()
    assert (a.system_instruction, b.system_instruction) == ("agent A", "agent B")
    assert again is a and made == ["agent A", "agent B"]
