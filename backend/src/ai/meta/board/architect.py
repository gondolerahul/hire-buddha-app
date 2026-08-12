"""
ai.meta.board.architect — Role 3: produce the draft HierarchicalEntity.

In Track 5 the Architect is **not** a new LLM agent — the existing
Meta-Agent runtime entity already produces draft specs. This module
just defines the typed envelope and a tiny *revise* helper the
Critic loop drives.

A subclass may plug in a real LLM revision; the base implementation
applies the Critic's ``fix_suggestion`` text as a structured note in
the draft's ``metadata_extensions.architect_revisions`` so a human (or
the next Architect LLM call) can act on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArchitectDraft:
    payload: dict[str, Any] = field(default_factory=dict)
    revisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload": dict(self.payload),
            "revisions": list(self.revisions),
        }


class Architect:
    """Tracks the draft spec and applies Critic-driven revisions."""

    async def revise(
        self,
        draft: ArchitectDraft,
        concerns: list[dict[str, Any]],
    ) -> ArchitectDraft:
        """Apply each concern as a structured note inside the draft.

        Override to call a real LLM (e.g. the Meta-Agent) for an
        intelligent rewrite. The base implementation records the
        feedback so subsequent layers can see it.
        """
        if not concerns:
            return draft
        new_payload = dict(draft.payload)
        meta = dict(new_payload.get("metadata_extensions") or {})
        revs = list(meta.get("architect_revisions") or [])
        revs.extend(concerns)
        meta["architect_revisions"] = revs
        new_payload["metadata_extensions"] = meta
        return ArchitectDraft(
            payload=new_payload,
            revisions=list(draft.revisions) + list(concerns),
        )


__all__ = ["Architect", "ArchitectDraft"]
