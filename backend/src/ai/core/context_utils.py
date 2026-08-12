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
    """Store step output in context (Phase 4 — DATA-1).

    Full output is preserved to ensure inter-step data integrity (e.g. research
    findings flowing into synthesis → report → PDF). Context growth for LLM
    prompt construction is managed separately by _maybe_summarize_context(),
    which intelligently trims older entries when the total context exceeds
    configurable thresholds.
    """
    value = output
    # PERF-3: Incremental context size tracking
    old_value = context_state.get(step_name, "")
    context_state[step_name] = value
    if cortex_bridge:
        cortex_bridge.update_context_size(step_name, old_value, value)
    if step_id and step_id != step_name:
        old_id_value = context_state.get(step_id, "")
        context_state[step_id] = value
        if cortex_bridge:
            cortex_bridge.update_context_size(step_id, old_id_value, value)


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
