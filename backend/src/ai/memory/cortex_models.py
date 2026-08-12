"""
ai.memory.cortex_models — host re-export shim.

The CORTEX ORM (CortexTree/Node/Edge) + its enums moved into the
host-independent ``cortex_memory`` package (Phase 12 `04` Stage B), onto the
package's own ``Base`` with opaque (FK-free) external references. This shim
keeps the ``src.ai.memory.cortex_models`` import path working; new code should
import from ``cortex_memory`` directly.

The host's Alembic ``target_metadata`` includes ``cortex_memory.metadata`` so
the package-owned tables are still managed by the host DB during the in-host
phase.
"""
from __future__ import annotations

from cortex_memory.enums import (
    CortexNodeStatus,
    CortexNodeType,
    CortexTreeStatus,
    MemoryDomain,
    ScopeLevel,
)
from cortex_memory.models import CortexEdge, CortexNode, CortexTree

__all__ = [
    "CortexTree",
    "CortexNode",
    "CortexEdge",
    "CortexTreeStatus",
    "CortexNodeType",
    "CortexNodeStatus",
    "MemoryDomain",
    "ScopeLevel",
]
