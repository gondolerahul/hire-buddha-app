"""
ai.core.prompt_utils — Prompt construction and variable resolution.

Extracted from worker.py during Phase 10A to break the circular import
between worker.py and step_executor.py. These are pure utility functions
with no database or service dependencies.
"""
import json
import re
from typing import Any, Dict, List, Optional

from src.ai.schemas import PlanStep


def parse_variables(text: str, variables: dict[str, Any]) -> str:
    """Replaces {{variable}} and {variable} in text with values from variables dict.

    Supports both double-brace ``{{topic}}`` and single-brace ``{topic}`` syntax.
    Double-brace patterns are replaced first (higher priority / more explicit),
    then single-brace patterns for any remaining placeholders.
    """
    if not text:
        return ""

    def _resolve(key: str, fallback: str) -> str:
        val: Any = variables
        parts = key.split('.')
        for i, k in enumerate(parts):
            if isinstance(val, dict):
                val = val.get(k, None)
            else:
                # If we landed on a non-dict value and the remaining part is
                # just "output", the value itself IS the output — return it.
                # This handles {{step_1.output}} when context stores step_1="result text".
                remaining = parts[i:]
                if remaining == ["output"] and val is not None:
                    return str(val)
                return fallback
        if val is None or val is variables:
            return fallback
        return str(val)

    # Pass 1: double-brace {{var}}
    def replace_double(match: "re.Match[str]") -> str:
        key = match.group(1).strip()
        return _resolve(key, match.group(0))
    text = re.sub(r'\{\{(.*?)\}\}', replace_double, text)

    # Pass 2: single-brace {var}  (skip if looks like JSON / Python format string)
    def replace_single(match: "re.Match[str]") -> str:
        key = match.group(1).strip()
        # Skip patterns that look like JSON or contain spaces/special chars
        if not key or ' ' in key or ':' in key or ',' in key or '"' in key:
            return match.group(0)
        return _resolve(key, match.group(0))
    text = re.sub(r'(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_.]*)\}(?!\})', replace_single, text)

    return text


# CORTEX ops-help moved into the cortex_memory package (Phase 12 `04`); re-used
# here so build_sandwich_prompt still injects it.
from cortex_memory.prompts import CORTEX_OPS_HELP  # noqa: E402,F401


def build_sandwich_prompt(
    identity: str,
    goal: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    few_shot_examples: Optional[List[Dict[str, str]]] = None,
    context: Optional[str] = None,
    current_task: str = "",
    output_schema: Optional[Dict[str, Any]] = None,
    success_criteria: Optional[List[Dict[str, Any]]] = None,
    allowed_deviations: Optional[Dict[str, Any]] = None,
    execution_constraints: Optional[Dict[str, Any]] = None,
    platform_awareness: Optional[str] = None,
    cortex_enabled: bool = False,                       # Track 6: inject ops-help once
) -> str:
    """
    Build structured prompt using the 'Sandwich Method'.

    Layers:
    1. Identity & Role (Who I am)
    2. Goal & Objective (What I'm trying to achieve)
    3. Tools & Capabilities (What I can do)
    3.5. Platform Awareness (Meta-cognition: what the platform can do)
    4. Few-Shot Examples (How I should behave)
    5. Success Criteria (How output will be judged)
    6. Planning Permissions (Dynamic planning deviations)
    7. Output Format (Required output schema)
    8. Execution Constraints (Cost/tool limits)
    9. Context/History (What happened so far)
    10. Current Task (What I need to do now)
    """
    sections = []

    # Layer 1: Identity & Role
    sections.append(f"## Identity & Role\n{identity}")

    # Layer 2: Goal & Objective
    if goal:
        sections.append(f"## Goal & Objective\n{goal}")

    # Layer 3: Tools & Capabilities
    if tools:
        tool_descriptions = "\n".join([
            f"- **{t['name']}**: {t['description']}" for t in tools
        ])
        sections.append(f"## Available Tools\nYou can use the following tools:\n{tool_descriptions}")

    # Layer 3.5: Platform Awareness (Tier 1 Meta-Cognition)
    if platform_awareness:
        sections.append(f"## Platform Awareness\n{platform_awareness}")

    # Layer 3.7: CORTEX Operations Help (Track 6 — injected once into the
    # system prompt instead of being re-shipped on every viewport).
    if cortex_enabled:
        sections.append(CORTEX_OPS_HELP)

    # Layer 4: Few-Shot Examples
    if few_shot_examples:
        example_text = "\n\n".join([
            f"**Scenario**: {ex.get('scenario', ex.get('input', ''))}\n**Response**: {ex.get('ideal_response', ex.get('output', ''))}"
            for ex in few_shot_examples
        ])
        sections.append(f"## Examples of Expected Behavior\n{example_text}")

    # Layer 5: Success Criteria
    if success_criteria:
        criteria_lines = "\n".join(
            f"- {sc.get('criterion', sc)} (validated by: {sc.get('validation_type', 'llm_judge')})"
            if isinstance(sc, dict) else f"- {sc}"
            for sc in success_criteria
        )
        sections.append(f"## Success Criteria\nYour output will be evaluated against:\n{criteria_lines}")

    # Layer 6: Planning Permissions
    if allowed_deviations:
        perm_lines = []
        if allowed_deviations.get("can_add_steps"):
            perm_lines.append("- You MAY add additional steps if needed")
        if allowed_deviations.get("can_skip_optional_steps"):
            perm_lines.append("- You MAY skip optional steps")
        if allowed_deviations.get("can_reorder_steps"):
            perm_lines.append("- You MAY reorder steps for efficiency")
        if allowed_deviations.get("can_change_tools"):
            perm_lines.append("- You MAY choose different tools than specified")
        if perm_lines:
            sections.append(f"## Planning Permissions\n" + "\n".join(perm_lines))

    # Layer 7: Output Format
    if output_schema and output_schema.get("properties"):
        schema_str = json.dumps(output_schema, indent=2)
        sections.append(
            f"## Required Output Format\n"
            f"Your response MUST conform to this JSON schema:\n```json\n{schema_str}\n```"
        )

    # Layer 8: Execution Constraints
    if execution_constraints:
        constraint_lines = []
        for key, val in execution_constraints.items():
            constraint_lines.append(f"- {key}: {val}")
        sections.append(f"## Execution Constraints\n" + "\n".join(constraint_lines))

    # Layer 9: Context/History
    if context:
        sections.append(f"## Previous Context\n{context}")

    # Layer 10: Current Task
    sections.append(f"## Current Task\n{current_task}")

    return "\n\n".join(sections)


def filter_context_for_step(
    step: PlanStep,
    full_context: dict[str, Any],
    context_policy: Optional[Dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Filter context based on step's explicit inputs and policy.

    Args:
        step: The plan step being executed
        full_context: Full execution context dictionary
        context_policy: Policy configuration from logic_gate

    Returns:
        Filtered context dictionary
    """
    if not context_policy:
        return full_context

    # Check for explicit input dependencies in step target
    if step.target and hasattr(step.target, 'input_dependencies'):
        deps = step.target.input_dependencies or []
        if deps:
            filtered = {"input": full_context.get("input")}
            for dep in deps:
                if dep in full_context:
                    filtered[dep] = full_context[dep]
            return filtered

    # Apply context policy
    policy_type = context_policy.get("type", "FULL")

    if policy_type == "LAST_N":
        n = context_policy.get("n", 3)
        keys = list(full_context.keys())
        # Always include 'input' and last N keys
        filtered = {"input": full_context.get("input")} if "input" in full_context else {}
        for k in keys[-n:]:
            filtered[k] = full_context[k]
        return filtered

    elif policy_type == "SLIDING_WINDOW":
        max_chars = context_policy.get("max_chars", 4000)
        filtered = {}
        total_chars = 0
        # Include from most recent first
        for k in reversed(list(full_context.keys())):
            v_str = str(full_context[k])
            if total_chars + len(v_str) <= max_chars:
                filtered[k] = full_context[k]
                total_chars += len(v_str)
            else:
                break
        return dict(reversed(list(filtered.items())))

    elif policy_type == "EXPLICIT":
        explicit_keys = context_policy.get("explicit_keys", [])
        return {k: full_context[k] for k in explicit_keys if k in full_context}

    # FULL - return everything
    return full_context
