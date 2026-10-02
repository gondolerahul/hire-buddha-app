"""ai.core.step_signals — what the loop tells a step, typed (AK-21, D22).

The loop used to tell the step engine things by writing them into the context
dict it copied out for each executor — ``__agent_state__`` (iteration, budget
pressure, open subgoals), ``__subjects__``, ``__failure_patterns__`` — and
copying the dict back afterwards: every value in two places, reconciled once
per iteration, and plumbing one forgotten filter away from a prompt.

Now the context dict carries data — the run's input and the steps' outputs
(memory's keys stay, owned by register 08) — and the loop's signals travel in
a :class:`StepSignals` it sets in a ``ContextVar`` around each executor call.
A ContextVar is per task, so each parallel DAG branch sees the signals of the
iteration that started it, and nothing is copied back.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional

__all__ = ["StepSignals", "current_signals", "step_signals", "signals_from_state"]


@dataclass(frozen=True)
class StepSignals:
    iteration: int = 0
    budget_pressure: Optional[float] = None
    open_subgoals: tuple[str, ...] = ()
    subjects: Optional[str] = None           # the run's subjects, as refs (TL-09)
    failure_patterns: Optional[str] = None   # lessons from recent failed runs (PC-12)
    step_names: Mapping[str, str] = field(default_factory=dict)   # step name → id (EP-18)

    def agent_state(self) -> dict[str, Any]:
        """The ``__agent_state__`` view a meta tool reads from its tool context."""
        return {"iteration": self.iteration, "budget_pressure": self.budget_pressure,
                "open_subgoals": list(self.open_subgoals)}


_SIGNALS: ContextVar[Optional[StepSignals]] = ContextVar("step_signals", default=None)


def current_signals() -> Optional[StepSignals]:
    """The signals of the loop iteration this code runs in, if any."""
    return _SIGNALS.get()


@contextmanager
def step_signals(signals: StepSignals) -> Iterator[StepSignals]:
    token = _SIGNALS.set(signals)
    try:
        yield signals
    finally:
        _SIGNALS.reset(token)


def signals_from_state(state: Any) -> StepSignals:
    """The loop's signals for the iteration ``state`` is in."""
    names: dict[str, str] = {}
    for step in getattr(state, "plan_steps", None) or []:
        if isinstance(step, dict):
            sid, name = str(step.get("step_id") or step.get("id") or ""), str(step.get("name") or "")
            if sid and name and name != sid:
                names.setdefault(name, sid)
    return StepSignals(
        iteration=int(getattr(state, "iteration", 0) or 0),
        budget_pressure=float(state.budget.pressure) if getattr(state, "budget", None) is not None else None,
        open_subgoals=tuple(sg.description for sg in getattr(state, "open_subgoals", []) or []),
        subjects=getattr(state, "subjects_block", "") or None,
        failure_patterns=getattr(state, "failure_patterns_block", "") or None,
        step_names=names,
    )
