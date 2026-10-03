"""The gate every publication passes (MI-20, D27).

Publishing a draft version, and promoting a ``DRAFT`` entity to ``ACTIVE``,
run the Board's deterministic Validator over the definition first. A failed
check refuses the publication with the checks that failed; a person with an
admin role (D13) still makes the decision. Before, the Validator, the
TestDriver and the Promoter's gates were on no creation path at all.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional
from uuid import UUID

__all__ = ["PublicationRefused", "require_publishable"]


class PublicationRefused(ValueError):
    """The definition fails a publication check. Maps to 422."""

    def __init__(self, failed: list[dict[str, str]]):
        self.failed = failed
        super().__init__("Not publishable: " + "; ".join(
            f"{c['name']}: {c['reason']}" if c["reason"] else c["name"] for c in failed))


async def require_publishable(definition: Mapping[str, Any], company_id: Optional[UUID]) -> None:
    """Raise :class:`PublicationRefused` unless every Validator check passes."""
    from src.ai.meta.board.validator import ValidatorRole

    report = await ValidatorRole().check(dict(definition), company_id=company_id)
    if not report.passed:
        raise PublicationRefused([{"name": c.name, "reason": c.reason} for c in report.failed])
