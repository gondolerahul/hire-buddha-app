"""
ai.meta.board.requirement_chat — Role 1: clarify user requirement → Spec.

The RequirementChat takes a free-form user message and produces a
:class:`Spec` dict that downstream Board roles consume. In Track 5 it
is a *deterministic, structuring* role — it does not call an LLM by
itself. The Meta-Agent's runtime entity already does the clarification
via REACT loops; this class just normalises whatever the agent built
into the canonical Spec shape so the Curator / Architect have a stable
contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Spec:
    """Canonical request envelope passed between Board roles."""
    description: str
    preferred_type: Optional[str] = None      # ACTION / SKILL / AGENT / PROCESS
    required_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "preferred_type": self.preferred_type,
            "required_tools": list(self.required_tools),
            "tags": list(self.tags),
            "extra": dict(self.extra),
        }


class RequirementChat:
    """Normalise the raw user request into a :class:`Spec`."""

    async def clarify(self, raw_request: dict[str, Any] | str) -> Spec:
        if isinstance(raw_request, str):
            return Spec(description=raw_request.strip())

        if not isinstance(raw_request, dict):
            return Spec(description=str(raw_request))

        return Spec(
            description=str(raw_request.get("description") or raw_request.get("intent") or "")
                .strip(),
            preferred_type=raw_request.get("preferred_type")
                            or raw_request.get("type"),
            required_tools=list(raw_request.get("required_tools") or []),
            tags=list(raw_request.get("tags") or []),
            extra={
                k: v for k, v in raw_request.items()
                if k not in {"description", "intent", "preferred_type",
                             "type", "required_tools", "tags"}
            },
        )


__all__ = ["RequirementChat", "Spec"]
