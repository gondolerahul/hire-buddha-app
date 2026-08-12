"""Phase 11 Track 2 — events emitter tests."""
from __future__ import annotations

import pytest

from src.ai.core.events import aevent, capture_test_events, event


def test_event_emits_record() -> None:
    with capture_test_events() as evts:
        event("agent.loop.run_start", run_id="r1", iter=4)
    assert len(evts) == 1
    assert evts[0].name == "agent.loop.run_start"
    assert evts[0].payload["run_id"] == "r1"


def test_capture_is_isolated() -> None:
    with capture_test_events() as outer:
        event("outer.a")
        with capture_test_events() as inner:
            event("inner.a")
        # Inner saw only its own emit; outer saw only its own.
        assert [e.name for e in inner] == ["inner.a"]
        # The outer capture should not have observed the inner emit.
        assert all(e.name != "inner.a" for e in outer)
        # After inner exits, emits land in outer again.
        event("outer.b")
    assert {e.name for e in outer} >= {"outer.a", "outer.b"}


def test_payload_sanitised_for_logger() -> None:
    class _ObjWithToDict:
        def to_dict(self):
            return {"k": "v"}

    with capture_test_events() as evts:
        event("agent.test.payload", complex_obj=_ObjWithToDict(),
              list_field=[1, 2, 3], nested={"a": 1})
    p = evts[0].payload
    assert p["complex_obj"] == {"k": "v"}
    assert p["list_field"] == ["1", "2", "3"]
    assert p["nested"] == {"a": 1}


@pytest.mark.asyncio
async def test_aevent_also_captured() -> None:
    with capture_test_events() as evts:
        await aevent("agent.async.thing", x=1)
    assert evts[0].name == "agent.async.thing"


# ---------------------------------------------------------------------------
# Track 13 — TelemetryEvent envelope
# ---------------------------------------------------------------------------


def test_emit_returns_telemetry_envelope() -> None:
    from src.ai.core.events import emit
    ev = emit(
        "agent.loop.iteration_start",
        severity="info",
        run_id="11111111-1111-1111-1111-111111111111",
        iteration=4,
        payload={"executor": "DAG"},
    )
    assert ev.event == "agent.loop.iteration_start"
    assert ev.severity == "info"
    assert ev.iteration == 4
    assert ev.payload == {"executor": "DAG"}
    assert str(ev.run_id) == "11111111-1111-1111-1111-111111111111"


def test_event_splits_structured_keys_into_envelope() -> None:
    from src.ai.core.events import event
    with capture_test_events() as evts:
        event(
            "agent.critic.post_verdict",
            run_id="22222222-2222-2222-2222-222222222222",
            iteration=2,
            severity="warn",
            tag="HALLUCINATION",
        )
    rec = evts[0]
    assert rec.severity == "warn"
    # Back-compat: structured keys still appear in payload for legacy
    # consumers (run_id used to live there).
    assert rec.payload["run_id"] == "22222222-2222-2222-2222-222222222222"
    assert rec.payload["iteration"] == 2
    assert rec.payload["tag"] == "HALLUCINATION"


def test_emit_invalid_severity_falls_back_to_info() -> None:
    from src.ai.core.events import event
    with capture_test_events() as evts:
        event("agent.test.bad_severity", severity="critical")
    assert evts[0].severity == "info"


def test_otel_exporter_receives_envelope() -> None:
    from src.ai.core.events import emit, set_otel_exporter, TelemetryEvent
    received: list[TelemetryEvent] = []
    set_otel_exporter(lambda ev: received.append(ev))
    try:
        emit("agent.test.otel", severity="error", payload={"x": 1})
    finally:
        set_otel_exporter(None)
    assert len(received) == 1
    assert received[0].severity == "error"
    assert received[0].event == "agent.test.otel"


def test_envelope_to_dict_serialisable() -> None:
    import json as _json
    from src.ai.core.events import emit
    ev = emit(
        "agent.cost.charged",
        severity="info",
        company_id="33333333-3333-3333-3333-333333333333",
        run_id="44444444-4444-4444-4444-444444444444",
        payload={"attribution": "tool", "amount_usd": 0.01},
    )
    out = ev.to_dict()
    # Round-trips through JSON cleanly.
    _json.dumps(out)
    assert out["event"] == "agent.cost.charged"
    assert out["company_id"] == "33333333-3333-3333-3333-333333333333"
    assert out["severity"] == "info"
    assert out["payload"]["attribution"] == "tool"
