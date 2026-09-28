"""
cortex_memory.prompts — CORTEX prompt fragments.

CORTEX domain knowledge (the operations help block injected into agent system
prompts / viewports). Moved out of the host (Phase 12 `04`); the host's
``prompt_utils`` re-uses it.
"""
from __future__ import annotations

CORTEX_OPS_HELP = (
    "## Available CORTEX Operations\n"
    "You can perform the following operations on the cognitive tree:\n"
    "  NAVIGATE(node_id) — Move your viewport to a node; see its title, summary, and children\n"
    "  READ(node_id, page=0) — Read the full content of a node (paged if large)\n"
    "  WRITE(parent_id, node_type, title, content, summary) — Create a new child node\n"
    "  RECURSE(node_id, task, result_slot) — Spawn a child execution scoped to a subtree\n"
    "  AWAIT_CHILDREN() — Wait for all child executions to complete and collect results\n"
    "  CHECKPOINT(progress_summary, key_facts, next_steps) — Save progress and compress context"
)

__all__ = ["CORTEX_OPS_HELP"]
