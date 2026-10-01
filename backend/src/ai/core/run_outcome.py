"""The run's terminal status, decided from what its steps did (AK-01)."""
from __future__ import annotations

from typing import Optional

from src.ai.core.agent_state import AgentState
from src.ai.schemas.enums import RunStatus


def final_status(state: AgentState) -> str:
    # A status set out of band (operator cancellation) wins so the abort
    # below doesn't relabel a CANCELLED run as a generic FAILED.
    if state.external_status:
        return state.external_status
    if state.next_decision == "ABORT":
        return RunStatus.FAILED.value
    if state.next_decision == "PAUSE_HITL":
        return RunStatus.PAUSED.value
    # With a plan, the steps' outcomes decide: COMPLETED only when every
    # required step succeeded, FAILED when none did. "No step is left ready"
    # is not success — a failed step is not ready either.
    outcome = state.plan_outcome()
    if outcome == "ALL":
        return RunStatus.COMPLETED.value
    if outcome == "NONE":
        return RunStatus.FAILED.value
    if outcome == "NO_PLAN" and state.all_subgoals_achieved():
        return RunStatus.COMPLETED.value
    return RunStatus.PARTIAL_COMPLETE.value


def failed_steps_summary(state: AgentState) -> Optional[str]:
    """The run's error_message when steps failed and nothing else explains it."""
    if not state.failed_steps:
        return None
    parts = [f"{sid}: {err}" for sid, err in state.failed_steps.items()]
    return ("failed steps: " + "; ".join(parts))[:1000]
