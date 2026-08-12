"""
ai.meta.skill_library — Phase 11 Track 5 skill candidate detector.

Scans recent ExecutionRuns for an entity, extracts consecutive
successful tool-call chains, and proposes a SKILL entity candidate
when the same chain is seen ≥ ``MIN_REPEATS`` times across the
``LOOKBACK_RUNS`` window.

Candidates are written into the company's
:class:`MetaIntelligenceTree` under the ``🎯 Spec Patterns`` section
as ``skill_candidate`` nodes. They never auto-promote — a human must
explicitly approve them via the admin API.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


MIN_REPEATS: int = 5
LOOKBACK_RUNS: int = 50
MIN_CHAIN_LEN: int = 2
MAX_CHAIN_LEN: int = 6


@dataclass
class ChainCandidate:
    chain: tuple[str, ...]
    frequency: int = 0
    sample_run_ids: list[str] = field(default_factory=list)


__all__ = ["SkillLibrary", "ChainCandidate", "MIN_REPEATS", "LOOKBACK_RUNS"]


class SkillLibrary:
    """Detect & propose skill candidates."""

    def __init__(
        self,
        db: Any,
        *,
        min_repeats: int = MIN_REPEATS,
        lookback_runs: int = LOOKBACK_RUNS,
        min_chain_len: int = MIN_CHAIN_LEN,
        max_chain_len: int = MAX_CHAIN_LEN,
    ):
        self.db = db
        self.min_repeats = min_repeats
        self.lookback_runs = lookback_runs
        self.min_chain_len = min_chain_len
        self.max_chain_len = max_chain_len

    # ------------------------------------------------------------------
    # Public — scan one entity, propose any chains that cross threshold
    # ------------------------------------------------------------------

    async def scan_entity(
        self,
        entity_id: UUID,
        company_id: UUID,
    ) -> list[ChainCandidate]:
        runs = await self._recent_run_ids(entity_id)
        if not runs:
            return []
        chains = await self._extract_chains(runs)
        candidates = self._tally_chains(chains)
        if not candidates:
            return []

        from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
        meta = MetaIntelligenceTree(self.db, company_id)
        for c in candidates:
            try:
                await meta.add_skill_candidate(
                    source_entity_id=entity_id,
                    chain=list(c.chain),
                    frequency=c.frequency,
                    suggestion=self._suggestion_for(c),
                )
            except Exception as exc:                                        # noqa: BLE001
                logger.debug("skill_candidate write failed: %s", exc)
        return candidates

    # ------------------------------------------------------------------
    # Static, pure helper — exposed so unit tests can poke it without DB
    # ------------------------------------------------------------------

    def detect_chains(self, runs_tool_sequences: list[list[str]]) -> list[ChainCandidate]:
        """Pure detector — given one list of tool-name sequences per run,
        return the chains that cross the ``min_repeats`` threshold.

        Useful for tests that don't want a live DB.
        """
        chains = []
        for seq in runs_tool_sequences:
            chains.extend(self._window_chains(seq))
        return self._tally_chains(chains)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _recent_run_ids(self, entity_id: UUID) -> list[UUID]:
        from sqlalchemy import select
        from src.ai.orm.execution import ExecutionRun
        rows = (await self.db.execute(
            select(ExecutionRun.id)
            .where(ExecutionRun.entity_id == entity_id)
            .order_by(ExecutionRun.created_at.desc())
            .limit(self.lookback_runs)
        )).scalars().all()
        return list(rows)

    async def _extract_chains(self, run_ids: list[UUID]) -> list[tuple[str, ...]]:
        from sqlalchemy import select
        from src.ai.orm.execution import ToolInteractionLog
        # Pull all successful tool calls for these runs ordered by run + time.
        rows = (await self.db.execute(
            select(
                ToolInteractionLog.run_id,
                ToolInteractionLog.tool_id,
                ToolInteractionLog.success,
                ToolInteractionLog.created_at,
            )
            .where(ToolInteractionLog.run_id.in_(run_ids))
            .order_by(ToolInteractionLog.run_id, ToolInteractionLog.created_at)
        )).all()

        sequences: dict[Any, list[str]] = {}
        for run_id, tool_id, success, _ in rows:
            if not success:
                # Reset chain — a failure breaks the consecutive sequence.
                sequences.setdefault(run_id, [])
                sequences[run_id].append("__BREAK__")
                continue
            sequences.setdefault(run_id, [])
            sequences[run_id].append(str(tool_id))

        out: list[tuple[str, ...]] = []
        for seq in sequences.values():
            # Split on breaks; window each clean segment.
            segments: list[list[str]] = [[]]
            for tool in seq:
                if tool == "__BREAK__":
                    segments.append([])
                else:
                    segments[-1].append(tool)
            for seg in segments:
                out.extend(self._window_chains(seg))
        return out

    def _window_chains(self, seq: list[str]) -> list[tuple[str, ...]]:
        chains: list[tuple[str, ...]] = []
        for length in range(self.min_chain_len, self.max_chain_len + 1):
            if len(seq) < length:
                break
            for i in range(len(seq) - length + 1):
                chain = tuple(seq[i: i + length])
                # Skip degenerate chains made of one repeated tool — those
                # are usually loops and don't deserve to be a skill.
                if len(set(chain)) == 1:
                    continue
                chains.append(chain)
        return chains

    def _tally_chains(self, chains: list[tuple[str, ...]]) -> list[ChainCandidate]:
        if not chains:
            return []
        counter: Counter[tuple[str, ...]] = Counter(chains)
        out: list[ChainCandidate] = []
        for chain, freq in counter.most_common():
            if freq < self.min_repeats:
                break
            out.append(ChainCandidate(chain=chain, frequency=freq))
        return out

    @staticmethod
    def _suggestion_for(c: ChainCandidate) -> str:
        return (
            f"Tool chain [{' → '.join(c.chain)}] observed {c.frequency}× "
            f"across recent runs. Consider promoting to a SKILL entity for reuse."
        )
