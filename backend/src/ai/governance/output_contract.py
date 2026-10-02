"""governance/output_contract.py — the run's final output against its output schema (EP-05).

``io_contract.output_schema`` was pasted into the prompt as an instruction and
checked by nothing. Now, when the plan's last step has run and succeeded, its
output is checked: it must be a JSON object (bare, or the first one in the
text, e.g. inside a fenced block) carrying the schema's required keys, with
declared types — the subset ``input_contract`` checks (D21). A mismatch turns
the post critic's verdict into ``REVISE`` with a ``WRONG_FORMAT`` tag and a
suggestion naming what is wrong, so the corrective retry rewrites the step's
prompt (PC-06). A schema with no properties and no required keys checks nothing.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

__all__ = ["output_problems", "apply_output_contract"]

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _first_object(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    candidates = [text] + _FENCED.findall(text)
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:text.rfind("}") + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def output_problems(entity: Any, output: str) -> list[str]:
    """What is wrong with ``output`` for ``entity``'s output schema; [] when fine."""
    from src.ai.governance.input_contract import _type_ok

    contract = getattr(entity, "io_contract", None) or {}
    schema = contract.get("output_schema") if isinstance(contract, Mapping) else None
    if not isinstance(schema, Mapping):
        return []
    raw_props = schema.get("properties")
    props: Mapping[str, Any] = raw_props if isinstance(raw_props, Mapping) else {}
    required = [str(r) for r in (schema.get("required") or [])]
    if not props and not required:
        return []
    data = _first_object(output)
    if data is None:
        return ["the output is not a JSON object"]
    problems = [f"'{name}' is missing" for name in required if name not in data]
    for name, spec in props.items():
        if name in data and isinstance(spec, Mapping) and "type" in spec and not _type_ok(data[name], spec["type"]):
            problems.append(f"'{name}' must be {spec['type']}")
    return problems


def _plan_finished(state: Any) -> bool:
    ids = {str(s.get("step_id") or s.get("id") or "") for s in state.plan_steps}
    ids.discard("")
    return bool(ids) and ids <= state.completed_step_ids and not state.plan_ready_steps()


async def apply_output_contract(pipeline: Any, entity: Any, state: Any, observation: Any, post: Any) -> Any:
    """The post verdict, made ``REVISE``/``WRONG_FORMAT`` when the run's final
    output does not fit the output schema; unchanged otherwise."""
    from src.ai.core.agent_state import PostCriticVerdict
    from src.ai.planning.failure_tags import FailureTag

    if observation.outcome != "success" or not _plan_finished(state):
        return post
    problems = output_problems(entity, observation.output or "")
    if not problems:
        return post
    keys = list(((getattr(entity, "io_contract", None) or {}).get("output_schema") or {}).get("properties") or {})
    verdict = PostCriticVerdict(
        kind="REVISE", tags=list(dict.fromkeys([*post.tags, FailureTag.WRONG_FORMAT])), cost_usd=post.cost_usd,
        suggestion=(f"Return only a JSON object with the keys {keys}: " + "; ".join(problems))[:500])
    override = getattr(pipeline, "override_post", None)
    if override is not None:
        override(verdict)
    return verdict
