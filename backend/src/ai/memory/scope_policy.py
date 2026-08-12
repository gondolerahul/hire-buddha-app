"""
ai.memory.scope_policy — host re-export shim.

``ScopePolicy`` / ``ScopeViolation`` moved into the host-independent
``cortex_memory`` package (Phase 12 `04` Stage B). This shim keeps the existing
``src.ai.memory.scope_policy`` import path working; new code should import from
``cortex_memory.scope_policy`` (or the package root) directly.
"""
from __future__ import annotations

from cortex_memory.scope_policy import ScopePolicy, ScopeViolation

__all__ = ["ScopePolicy", "ScopeViolation"]
