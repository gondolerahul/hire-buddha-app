"""GW-13: an internal event has no ``priority`` — it was stored and never read.

arq has no per-job priority, so the field promised an ordering nothing gave.
It is gone from the schema and the emitter; a caller that still sends it is
not refused (the schema ignores unknown fields), and nothing carries it on.
"""
from __future__ import annotations

import inspect

from src.gateway import internal_event
from src.gateway.internal_event import InternalEvent, emit_internal_event


def test_the_schema_and_the_emitter_have_no_priority():
    assert "priority" not in InternalEvent.model_fields
    assert "priority" not in inspect.signature(emit_internal_event).parameters


def test_an_old_caller_sending_priority_is_not_refused():
    event = InternalEvent(event_type="doc_indexed", client_id="c", source="cron", priority=1)
    assert not hasattr(event, "priority")


async def test_the_queued_envelope_carries_no_priority(monkeypatch):
    queued = []

    async def _queue(envelope):
        queued.append(envelope)

    monkeypatch.setattr(internal_event, "queue_event", _queue)
    await emit_internal_event("agent.signal", "c", "agent:x", {})
    assert "priority" not in queued[0].metadata
