"""gates.py — every control that can refuse, and what it does when it cannot decide (GH-21, GH-I2).

A gate that could not evaluate — Redis down, a wallet it could not read, a
check that raised — used to look exactly like a gate that passed: most of them
swallowed the error and let the request through, and none said so. Now each
one's failure path calls :func:`gate_failed`, which logs a warning and emits
``gate.failed`` with the gate, what it did (``closed``: refused; ``open``: let
it through) and the error. The event goes to the structured log and the OTel
exporter; it is the metric to alert on.

:data:`GATES` lists them all. A gate that fails open says why — it is a
decision, not a default — and ``tests/unit/test_gate_inventory.py`` checks that
every ``gate_failed`` call names a gate listed here, that every gate listed has
a call, and that an open one gives its reason.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

__all__ = ["Gate", "GATES", "gate_failed"]


@dataclass(frozen=True)
class Gate:
    fails: Literal["closed", "open"]
    what: str
    why_open: str = ""


GATES: dict[str, Gate] = {
    "rate_limiter": Gate("closed", "RedisRateLimiter — the agent-creation burst limit and per-company quotas: Redis unreachable refuses (GH-03)"),
    "semantic_duplicate": Gate("closed", "the agent-creation duplicate check: a search that cannot run refuses (MI-01)"),
    "hitl_checkpoint": Gate("closed", "a HITL checkpoint that cannot be evaluated asks a person before the step (GH-09)"),
    "credit_admission": Gate("closed", "a run's admission: a wallet or spend cap it cannot read and the run does not start (BC-05)"),
    "credit_breaker": Gate(
        "open", "a running run's credit and spend-cap breaker",
        why_open="a run is not stopped on a wallet it cannot read; settlement still bills what it spent"),
    "webhook_signature": Gate("closed", "an inbound webhook whose endpoint secret does not decrypt is refused (GW-01)"),
    "webhook_duplicate": Gate("closed", "an inbound webhook whose delivery cannot be checked for a repeat is a 503 (GW-03)"),
    "voice_call_credit": Gate("closed", "a call's credit admission: a balance it cannot read refuses the call (VT-01, HD9)"),
}


def gate_failed(gate: str, error: Any, *, decision: str = "", **context: Any) -> None:
    """Record that ``gate`` could not evaluate. ``decision`` defaults to what
    :data:`GATES` says the gate does; pass it when a caller chose otherwise."""
    from src.ai.core.events import event

    spec = GATES.get(gate)
    did = decision or (spec.fails if spec else "unknown")
    detail = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    logger.warning("Gate %s could not evaluate (%s): %s", gate, did, detail[:300])
    event("gate.failed", gate=gate, decision=did, error=detail[:500], severity="warn", **context)
