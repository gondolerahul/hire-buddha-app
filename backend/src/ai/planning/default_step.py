"""
ai.planning.default_step — the step an entity runs when nothing else plans it.

Every level resolves its plan the same way (R1, EP-26 — ``PlannerService.reconcile``):
its static plan; else a dynamic plan; else, when it has children and no tools
of its own, delegation to them; else this one step. It is an ACTION step, so the
entity's own tools are offered to the model, the entity's description is the
task and its goal is in the system prompt.

Its template reads what the execute form asks for: the fields of
``io_contract.input_schema`` when the entity declares them, otherwise
``{{input}}``. The entity read path shows the same step for an entity without
static steps (``display_planning``), so the form asks for those inputs.
"""
from __future__ import annotations

import copy
from typing import Any

__all__ = ["DEFAULT_STEP_ID", "default_step", "display_planning"]

DEFAULT_STEP_ID = "auto_generated"


def _input_fields(entity: Any) -> list[str]:
    io_contract = getattr(entity, "io_contract", None) or {}
    schema = io_contract.get("input_schema") if isinstance(io_contract, dict) else None
    properties = (schema or {}).get("properties") if isinstance(schema, dict) else None
    return [name for name in (properties or {}) if isinstance(name, str) and name]


def default_step(entity: Any) -> dict[str, Any]:
    """The one step of an entity with no plan and nothing to delegate to."""
    fields = _input_fields(entity)
    if fields and fields != ["input"]:
        template = "\n".join(f"{name}: {{{{{name}}}}}" for name in fields)
    else:
        template = "{{input}}"
    description = (
        getattr(entity, "description", None)
        or getattr(entity, "goal", None)
        or f"Do the work of {getattr(entity, 'name', None) or 'this entity'}."
    )
    return {
        "step_id": DEFAULT_STEP_ID,
        "order": 1,
        "name": "Execute",
        "description": description,
        "type": "ACTION",
        "target": {"prompt_template": template},
        "required": True,
    }


def display_planning(entity: Any) -> Any:
    """``entity.planning`` as the API shows it: with the default step when the
    static plan has no steps. A copy — the stored row is never changed (EP-27)."""
    planning = getattr(entity, "planning", None)
    static_plan = (planning or {}).get("static_plan") if isinstance(planning, dict) else None
    if isinstance(static_plan, dict) and static_plan.get("steps"):
        return planning
    shown = copy.deepcopy(planning) if isinstance(planning, dict) else {}
    shown["static_plan"] = {
        **(static_plan if isinstance(static_plan, dict) else {}),
        "enabled": True,
        "steps": [default_step(entity)],
    }
    return shown
