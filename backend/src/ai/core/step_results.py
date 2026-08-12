"""
ai.core.step_results — per-step result summaries for the AgentLoop.

Mirrors the legacy engine's ``result_data["steps"]`` shape
(``{"step", "step_id", "type", "output"[, "child_run_id"]}``) so the loop
persists the same run metadata. Downstream consumers — notably the refine
flow in ``service.py``, which reuses unchanged steps' outputs by id — read
this back, so the loop must produce it once it is the sole engine.

Kept out of ``agent_loop.py`` to keep that module lean; the loop calls
``record_step_result`` (inline completion) and ``record_child_step_result``
(an async child folded on resume).
"""
from __future__ import annotations

from typing import Any, Optional


def find_plan_step(steps: Any, step_id: Any) -> Optional[dict[str, Any]]:
    """Find a plan step by id in a plan_fragment / plan_steps list.

    Returns a normalized ``{"name", "type"}`` dict (entries may be raw dicts
    or PlanStep objects), or ``None`` if no match.
    """
    target = str(step_id or "")
    for s in (steps or []):
        if isinstance(s, dict):
            sid = str(s.get("step_id") or s.get("id") or "")
            if sid == target:
                return {"name": s.get("name"), "type": s.get("type")}
        else:
            sid = str(getattr(s, "step_id", "") or "")
            if sid == target:
                return {"name": getattr(s, "name", None),
                        "type": getattr(s, "type", None)}
    return None


def record_step_result(state: Any, move: Any, step_id: str,
                       action_result: Any) -> None:
    """Append a per-step summary for a step completed inline this iteration."""
    step = find_plan_step(getattr(move, "plan_fragment", None), step_id)
    entry: dict[str, Any] = {
        "step": (step.get("name") if step else None) or step_id,
        "step_id": step_id,
        "type": str((step.get("type") if step else "") or ""),
        "output": (action_result.output or "")[:8000],
    }
    child_ids = getattr(action_result, "children_run_ids", None) or []
    if child_ids:
        entry["child_run_id"] = str(child_ids[0])
    state.step_results.append(entry)


def record_child_step_result(state: Any, step_id: str, output: str,
                             child_run_id: Any) -> None:
    """Append a per-step summary for an async child folded on resume."""
    step = find_plan_step(state.plan_steps, step_id)
    entry: dict[str, Any] = {
        "step": (step.get("name") if step else None) or step_id,
        "step_id": step_id,
        "type": str((step.get("type") if step else "")
                    or "CHILD_ENTITY_INVOCATION"),
        "output": (str(output) if output else "")[:8000],
    }
    if child_run_id:
        entry["child_run_id"] = str(child_run_id)
    state.step_results.append(entry)
