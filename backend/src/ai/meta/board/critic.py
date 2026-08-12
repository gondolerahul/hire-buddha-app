"""
ai.meta.board.critic — Role 4: spec-quality critic loop.

Drives :class:`MetaSpecCriticTool` with up to ``MAX_REVISE_ROUNDS``
rounds. On REVISE, calls ``architect.revise(draft, concerns)`` and
re-critiques. On PASS, returns the draft. On BLOCK (or max rounds
hit), returns the report so the Promoter can reject.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

logger = logging.getLogger(__name__)

MAX_REVISE_ROUNDS: int = 2


@dataclass
class CriticReport:
    verdict: str = "REVISE"                     # PASS / REVISE / BLOCK
    concerns: list[dict[str, Any]] = field(default_factory=list)
    rules_referenced: list[str] = field(default_factory=list)
    rounds: int = 0
    blocked_reason: str = ""

    @property
    def has_blocking_concern(self) -> bool:
        return any(c.get("blocks_promotion") for c in self.concerns)

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


class BoardCritic:
    """Coordinates the spec_critic tool + architect revise loop."""

    def __init__(self, *, company_id: UUID, max_rounds: int = MAX_REVISE_ROUNDS):
        self.company_id = company_id
        self.max_rounds = max_rounds

    async def review_with_revision(
        self,
        draft: Any,
        architect: Any,
        *,
        search_top_k: list[Any] | None = None,
    ) -> tuple[Any, CriticReport]:
        report = CriticReport()
        for round_ in range(self.max_rounds + 1):
            report = await self._call_tool(draft, search_top_k or [])
            report.rounds = round_
            if report.verdict == "PASS":
                return draft, report
            if report.verdict == "BLOCK":
                return draft, report
            # REVISE — ask architect for another draft.
            if round_ < self.max_rounds:
                draft = await architect.revise(draft, report.concerns)
            else:
                report.verdict = "BLOCK"
                report.blocked_reason = "max revise rounds reached"
        return draft, report

    async def _call_tool(self, draft: Any, search_top_k: list[Any]) -> CriticReport:
        from src.ai.tools.meta.spec_critic import MetaSpecCriticTool
        spec_payload = self._spec_payload(draft)
        tool = MetaSpecCriticTool()
        raw = await tool.run_with_context(
            json.dumps({
                "mode": "review_spec",
                "spec": spec_payload,
                "search_top_k": search_top_k,
            }),
            context={"company_id": self.company_id},
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("BoardCritic could not parse tool output; defaulting to REVISE")
            return CriticReport(verdict="REVISE")
        if "error" in parsed and "verdict" not in parsed:
            return CriticReport(
                verdict="REVISE",
                concerns=[{
                    "severity": "med",
                    "category": "prompt",
                    "issue": parsed["error"],
                    "fix_suggestion": "",
                    "blocks_promotion": False,
                }],
            )
        return CriticReport(
            verdict=str(parsed.get("verdict", "REVISE")).upper(),
            concerns=list(parsed.get("concerns") or []),
            rules_referenced=list(parsed.get("rules_referenced") or []),
        )

    @staticmethod
    def _spec_payload(draft: Any) -> dict[str, Any]:
        if isinstance(draft, dict):
            return draft
        payload = getattr(draft, "payload", None)
        if isinstance(payload, dict):
            return payload
        if hasattr(draft, "to_dict"):
            d = draft.to_dict()
            if isinstance(d, dict) and isinstance(d.get("payload"), dict):
                return cast("dict[str, Any]", d["payload"])
            return cast("dict[str, Any]", d)
        return {"raw": str(draft)}


__all__ = ["BoardCritic", "CriticReport", "MAX_REVISE_ROUNDS"]
