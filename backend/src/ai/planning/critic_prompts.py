"""
ai.planning.critic_prompts — Prompt templates for the Critic Pipeline.

Extracted from critic_pipeline.py so the orchestrating module stays
under the kernel layout-lint cap. Prompts here are intentionally
data-only; behaviour lives in :mod:`ai.planning.critic_pipeline`.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "PRE_PROMPT_SYSTEM",
    "PRE_PROMPT_USER",
    "POST_PROMPT_SYSTEM",
    "POST_PROMPT_USER",
    "render_steps",
]


def render_steps(move: Any) -> str:
    """The steps a move would run, as the pre-critic sees them (PC-01):
    without them it judged a move by its executor name and a count."""
    lines = []
    for step in (getattr(move, "plan_fragment", None) or [])[:8]:
        if not isinstance(step, dict):
            continue
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        tool = f", tool {target.get('tool_id')}" if target and target.get("tool_id") else ""
        line = (f"  - {step.get('name') or step.get('step_id')} [{step.get('type', 'ACTION')}{tool}]"
                f": {str(step.get('description') or '')[:300]}")
        template = str((target or {}).get("prompt_template") or "")[:400]
        if template:
            line += f"\n    template: {template}"
        lines.append(line)
    return "\n".join(lines) or "  (none: an open-ended move)"


PRE_PROMPT_SYSTEM = (
    "You are a strict pre-action critic for an autonomous AI agent. "
    "Your job is to detect obviously bad moves BEFORE they execute. "
    "Reply in JSON only."
)

PRE_PROMPT_USER = (
    "Goal: {goal}\n"
    "Open subgoals: {subgoals}\n"
    "Proposed move:\n  executor={executor}\n  rationale={rationale}\n"
    "  plan_fragment_size={plan_size}\n"
    "Steps it would run:\n{steps}\n"
    "Budget pressure: {pressure:.2f}\n"
    "Respond with JSON:\n"
    '{{"verdict": "PASS|BLOCK|REVISE", "concerns": ["..."]}}\n'
    "PASS = looks reasonable. BLOCK = clearly off-topic, unsafe, or wasteful: the steps "
    "will not run. REVISE = sensible but needs adjustment: your concerns are given to the "
    "steps as a correction before they run."
)

POST_PROMPT_SYSTEM = (
    "You are a senior reviewer of AI agent outputs. You will be shown a "
    "step's output, the goal it was meant to advance, and prior history. "
    "Your task: assign a verdict and structured failure tags. Be precise. "
    "Reply in JSON only."
)

POST_PROMPT_USER = (
    "Goal: {goal}\n"
    "Task description: {task}\n"
    "Step description: {step_desc}\n"
    "Observation outcome: {outcome}\n"
    "Step output (complete unless a line says the system cut it):\n---\n{output}\n---\n"
    "Recent prior health records (last 3):\n{prior_history}\n"
    "Top intelligence rules (top 3):\n{intel_rules}\n\n"
    "Closed set of failure tags:\n"
    "OFF_TOPIC, HALLUCINATION, INCOMPLETE, WRONG_FORMAT, TOOL_FAILURE, "
    "CONTRADICTION, UNVERIFIABLE, POLICY_VIOLATION, UNDER_BUDGET, "
    "OVER_BUDGET, BLOCKED_DEPENDENCY, NEEDS_CLARIFICATION.\n\n"
    "Respond with JSON only:\n"
    '{{"verdict": "PASS|REVISE|REJECT", '
    '"tags": ["TAG1", "TAG2"], '
    '"suggestion": "concise fix recommendation (or empty for PASS)"}}'
)
