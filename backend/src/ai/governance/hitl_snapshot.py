"""What a HITL reviewer sees: the ``context_snapshot`` stored on an approval.

A reviewer must be able to tell what they are authorising without opening the
run. BEFORE checkpoints show what the step is about to do (its resolved prompt,
its tool); AFTER checkpoints also show what it produced. Text fields are capped
so a large step output cannot bloat the approvals list. Step ids stay out: they
expose internal plan topology and mean nothing to a reviewer.
"""
from __future__ import annotations

from typing import Any, Optional

from src.ai.core.prompt_utils import parse_variables

MAX_FIELD_CHARS = 4000


def _clip(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_FIELD_CHARS:
        return f"{text[:MAX_FIELD_CHARS]}… [{len(text) - MAX_FIELD_CHARS} more characters]"
    return text


def build_hitl_snapshot(
    *,
    checkpoint: Any,
    trigger_desc: str,
    phase: str,
    entity: Any,
    step: Any,
    context_state: dict[str, Any],
    run_cost_usd: Any = None,
    step_result: Any = None,
) -> dict[str, Any]:
    """Return the JSON-safe snapshot for one fired checkpoint. Empty fields are omitted."""
    target = getattr(step, "target", None)
    template = getattr(target, "prompt_template", None) if target else None
    step_type = getattr(step, "type", None)

    output = None
    if phase == "AFTER" and step_result is not None:
        output = step_result.get("output") if isinstance(step_result, dict) else step_result

    snapshot: dict[str, Any] = {
        "message": checkpoint.message or f"Approval required: {trigger_desc}",
        "trigger_type": getattr(checkpoint.trigger_type, "value", str(checkpoint.trigger_type)),
        "phase": phase,
        "entity_name": getattr(entity, "display_name", None) or getattr(entity, "name", None),
        "step_name": getattr(step, "name", None),
        "step_type": getattr(step_type, "value", step_type),
        "step_description": _clip(getattr(step, "description", None)),
        "tool_id": getattr(target, "tool_id", None) if target else None,
        "step_prompt": _clip(parse_variables(template, context_state)) if template else None,
        "run_input": _clip(context_state.get("input")),
        "step_output": _clip(output),
        "run_cost_usd": float(run_cost_usd) if run_cost_usd is not None else None,
    }
    return {k: v for k, v in snapshot.items() if v is not None}
