"""
cortex_memory.scope_policy — declarative ScopePolicy for the CORTEX tree.

When a CORTEX service is constructed with a ``scoped_subtree_root_id``, every
operation must stay inside the descendant set of that root. This centralises
that rule in a typed :class:`ScopePolicy` the service consults uniformly.

Defaults are **strict** — the service raises :class:`ScopeViolation` on the
first attempt to read or write outside the scoped subtree. The child-recursion
path that needs to read shared parent context passes
``ScopePolicy(can_read_outside=True)``.

A core tree primitive with no host dependency — the first piece moved into the
package (Phase 12 `04` Stage B). The host re-exports it from
``src/ai/memory/scope_policy.py`` so existing imports keep working.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScopePolicy:
    can_read_outside: bool = False
    can_write_outside: bool = False
    can_navigate_to_siblings: bool = False
    error_on_violation: bool = True

    @classmethod
    def child_recursion_default(cls) -> "ScopePolicy":
        """Default for child recursive runs: read parent, never write up."""
        return cls(
            can_read_outside=True,
            can_write_outside=False,
            can_navigate_to_siblings=False,
            error_on_violation=True,
        )


class ScopeViolation(RuntimeError):
    """Raised when a CORTEX operation breaks its ScopePolicy."""

    def __init__(self, operation: str, target_id: str, scope_root_id: str):
        super().__init__(
            f"ScopeViolation: {operation} on {target_id} is outside scoped "
            f"subtree rooted at {scope_root_id}"
        )
        self.operation = operation
        self.target_id = target_id
        self.scope_root_id = scope_root_id


__all__ = ["ScopePolicy", "ScopeViolation"]
