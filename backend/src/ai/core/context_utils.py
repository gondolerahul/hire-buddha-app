"""
ai.core.context_utils — Context state management utilities.

Handles step output storage and context sanitization for persistence.
Extracted from worker.py during Phase 10A restructuring.
"""
from typing import Any, Optional


# SEC-1: Keys to strip before persisting context to DB.
# Prevents accidental exposure of API keys, secrets, and internal
# bookkeeping data in DB dumps or API responses.
_SENSITIVE_CONTEXT_KEYS = frozenset({
    "api_key", "api_secret", "secret", "token", "password",
    "auth", "authorization", "credential", "credentials",
    "__model_override",
    # Live runtime handle injected by AgentLoop — not JSON-serializable.
    "__redis__",
})


def store_step_output(
    context_state: dict[str, Any],
    step_name: str,
    step_id: str,
    output: str,
    cortex_bridge: Any = None,
) -> None:
    """Store a step's output in the context, once, under the step's id (EP-18).

    Full output is preserved to ensure inter-step data integrity (e.g. research
    findings flowing into synthesis → report → PDF). Context growth for LLM
    prompt construction is managed separately by _maybe_summarize_context().

    Before, the output was stored under the name *and* the id: every output
    twice (a 40 KB finding was 80 KB of context, trimmed sooner), and two steps
    with one name overwrote each other. ``{{name}}`` still resolves: through
    the run's name→id map (``StepSignals.step_names``) in ``parse_variables``.
    A step with no id is stored under its name.
    """
    key = step_id or step_name
    # PERF-3: Incremental context size tracking
    old_value = context_state.get(key, "")
    context_state[key] = output
    if cortex_bridge:
        cortex_bridge.update_context_size(key, old_value, output)


def sanitize_context_for_persistence(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ctx with sensitive keys redacted.

    Called before persisting context_state to the database to prevent
    accidental exposure of API keys, secrets, and internal bookkeeping data.
    """
    if not ctx:
        return ctx
    sanitized = {}
    for k, v in ctx.items():
        key_lower = k.lower()
        if any(sk in key_lower for sk in _SENSITIVE_CONTEXT_KEYS):
            continue  # drop entirely
        sanitized[k] = v
    return sanitized
