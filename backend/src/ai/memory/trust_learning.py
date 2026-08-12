"""memory.trust_learning — in-tenant provenance trust-score learning (`07` §3).

``Provenance.trust_score`` is a static per-source-type prior. This host-side
loop *learns* it: when a knowledge node from source S survives critic review or
contributes to a successful run, S earns trust; when it is rejected, it loses
some. The learned value is a Beta-posterior mean — ``(prior·k + successes) /
(k + observations)`` — so it starts at the static prior and converges to the
observed success rate as evidence accumulates (no cliff at a fixed threshold).

Privacy: this is purely in-tenant aggregate statistics over sources (no tenant
data, prompts, or outputs), so it is safe to ship in P12 (`06` §8). Gated by
``memory.trust_score_learning`` (default OFF).
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

logger = logging.getLogger(__name__)

__all__ = ["source_key", "prior_for", "TrustLearner"]

# Pseudo-count strength of the static prior. Higher = slower to move off the
# prior. 8 means ~8 observations before learned trust is ~half data-driven.
_PRIOR_STRENGTH = 8.0


def source_key(source_type: str, *, tool_id: Optional[str] = None,
               url: Optional[str] = None) -> str:
    """Canonical, stable identity for a knowledge source.

    ``tool:web_search`` / ``external_link:example.com`` / ``user_upload``. The
    URL is reduced to its host so per-page noise does not fragment the score.
    """
    st = (source_type or "unknown").lower()
    if tool_id:
        return f"{st}:{tool_id}"
    if url:
        host = url.split("://", 1)[-1].split("/", 1)[0].lower() or url.lower()
        return f"{st}:{host}"
    return st


def prior_for(source_type: str) -> float:
    """The static per-source-type trust prior from the CORTEX model."""
    try:
        from cortex_memory.dtos import DEFAULT_TRUST_BY_SOURCE
        return float(DEFAULT_TRUST_BY_SOURCE.get((source_type or "").lower(), 0.5))
    except Exception:  # noqa: BLE001
        return 0.5


def _posterior(prior: float, successes: float, observations: int) -> float:
    learned = (prior * _PRIOR_STRENGTH + successes) / (_PRIOR_STRENGTH + observations)
    return max(0.0, min(1.0, learned))


class TrustLearner:
    """Records source outcomes and serves the learned trust score."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def _get(self, company_id: UUID, key: str) -> Optional[Any]:
        from src.ai.orm.trust import SourceTrustScore
        res = await self.db.execute(
            select(SourceTrustScore).where(
                SourceTrustScore.company_id == company_id,
                SourceTrustScore.source_key == key,
            )
        )
        return res.scalar_one_or_none()

    async def record_outcome(
        self,
        company_id: UUID,
        source_type: str,
        *,
        positive: bool,
        tool_id: Optional[str] = None,
        url: Optional[str] = None,
        weight: float = 1.0,
        commit: bool = True,
    ) -> float:
        """Fold one outcome into a source's learned trust; return the new value."""
        from src.ai.orm.trust import SourceTrustScore

        key = source_key(source_type, tool_id=tool_id, url=url)
        prior = prior_for(source_type)
        weight = max(0.0, float(weight))

        row = await self._get(company_id, key)
        if row is None:
            row = SourceTrustScore(
                company_id=company_id, source_key=key, observations=0,
                successes=0.0, prior=prior, learned_trust=prior,
            )
            self.db.add(row)

        row.observations = int(row.observations) + 1
        if positive:
            row.successes = float(row.successes) + weight
        row.learned_trust = _posterior(float(row.prior), float(row.successes),
                                       int(row.observations))
        if commit:
            await self.db.commit()
        return float(row.learned_trust)

    async def effective_trust(
        self,
        company_id: UUID,
        source_type: str,
        *,
        tool_id: Optional[str] = None,
        url: Optional[str] = None,
    ) -> float:
        """Learned trust for a source, or the static prior if never observed."""
        key = source_key(source_type, tool_id=tool_id, url=url)
        row = await self._get(company_id, key)
        if row is None:
            return prior_for(source_type)
        return float(row.learned_trust)
