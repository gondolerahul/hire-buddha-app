"""
ai.memory.experience_tree_service — host re-export shim.

``ExperienceTreeService`` moved into the ``cortex_memory`` package (Phase 12
`04` Stage B); it has no host dependency, so this is a plain re-export.
"""
from __future__ import annotations

from cortex_memory.experience_tree import ExperienceTreeService

__all__ = ["ExperienceTreeService"]
