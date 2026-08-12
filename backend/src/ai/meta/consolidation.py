"""ai.meta.consolidation — Curator consolidation: merge plans (`06` §4.1).

Anti-sprawl was *block-only*: it refused near-duplicate creation. This turns it
into *consolidate* — when a cluster of ≥N near-duplicate entities (pairwise
similarity > threshold) already exists, the Curator proposes a **merge plan**:
pick a winner, list the losers, re-point references, archive the losers, and fork
their intelligence rules into the winner.

A merge is **never executed automatically** (`06` §4.1): ``propose_plans`` only
emits proposals + an audit row; a human approves before anything is re-pointed or
archived. The plan-selection logic is pure so it is unit-testable; the DB
clustering is a thin layer over the registry search.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

__all__ = ["EntityRef", "MergePlan", "select_winner", "build_merge_plan", "ConsolidationPlanner"]

DEFAULT_MIN_CLUSTER = 5
DEFAULT_MIN_SIMILARITY = 0.9


@dataclass
class EntityRef:
    entity_id: str
    name: str = ""
    version: int = 1
    usage_count: int = 0
    updated_at: str = ""        # ISO; recency tiebreak


@dataclass
class MergePlan:
    winner_id: str
    loser_ids: List[str]
    similarity: float
    rationale: str = ""
    reference_repoints: List[str] = field(default_factory=list)
    rule_forks: List[str] = field(default_factory=list)
    requires_hitl: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_winner(entities: List[EntityRef]) -> EntityRef:
    """The survivor of a merge: most-used, then highest version, then most recent."""
    return max(entities, key=lambda e: (e.usage_count, e.version, e.updated_at))


def build_merge_plan(
    cluster: List[EntityRef],
    similarity: float,
    *,
    min_cluster: int = DEFAULT_MIN_CLUSTER,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> Optional[MergePlan]:
    """Build a merge plan for a near-duplicate cluster, or None if it doesn't qualify."""
    if len(cluster) < min_cluster or similarity < min_similarity:
        return None
    winner = select_winner(cluster)
    losers = [e for e in cluster if e.entity_id != winner.entity_id]
    if not losers:
        return None
    return MergePlan(
        winner_id=winner.entity_id,
        loser_ids=[e.entity_id for e in losers],
        similarity=round(similarity, 3),
        rationale=(
            f"{len(cluster)} near-duplicate entities (similarity {similarity:.0%}); "
            f"keep '{winner.name or winner.entity_id}' (usage={winner.usage_count}, "
            f"v{winner.version}), archive {len(losers)} and fork their rules."
        ),
        reference_repoints=[e.entity_id for e in losers],
        rule_forks=[e.entity_id for e in losers],
    )


class ConsolidationPlanner:
    """Discovers near-duplicate clusters and proposes (never executes) merges."""

    def __init__(self, db: Any, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def propose_plans(
        self,
        *,
        min_cluster: int = DEFAULT_MIN_CLUSTER,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        audit: bool = True,
    ) -> List[MergePlan]:
        """Cluster the company's entities and return qualifying merge proposals.

        Gated by the caller (``meta_agent.curator_consolidation_enabled``). Writes
        each proposal to the MetaIntelligenceTree as a curator decision for audit.
        """
        clusters = await self._find_clusters(min_similarity)
        plans: List[MergePlan] = []
        for cluster, sim in clusters:
            plan = build_merge_plan(cluster, sim, min_cluster=min_cluster,
                                    min_similarity=min_similarity)
            if plan is not None:
                plans.append(plan)

        if audit and plans:
            try:
                from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
                tree = MetaIntelligenceTree(self.db, self.company_id)
                for plan in plans:
                    await tree.record_curator_decision(
                        decision="CONSOLIDATE",
                        candidates=[{"entity_id": eid} for eid in plan.loser_ids],
                        rationale=plan.rationale,
                        outcome="proposed",
                    )
            except Exception:  # noqa: BLE001
                logger.debug("consolidation audit write failed; continuing")
        return plans

    async def _find_clusters(self, min_similarity: float) -> List[tuple[List[EntityRef], float]]:
        """Greedy single-link clustering over registry-search similarity.

        Each ACTIVE entity seeds a search; hits above ``min_similarity`` (minus a
        small band so the cluster can form) join its cluster. Entities already
        claimed by a cluster are skipped. Best-effort: returns [] on any error.
        """
        try:
            from src.ai.meta.registry_search_service import RegistrySearchService, SearchRequest
            from src.ai.models import HierarchicalEntity
            from sqlalchemy import select

            rows = (await self.db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.company_id == self.company_id,
                    HierarchicalEntity.status == "ACTIVE",
                )
            )).scalars().all()
            search = RegistrySearchService(self.db, self.company_id)
            claimed: set[str] = set()
            clusters: List[tuple[List[EntityRef], float]] = []
            for seed in rows:
                if str(seed.id) in claimed:
                    continue
                req = SearchRequest(intent=getattr(seed, "description", "") or seed.name)
                hits = await search.search(req, top_k=20)
                members: List[EntityRef] = [_to_ref(seed)]
                worst = 1.0
                for h in hits:
                    hid = str(h.entity_id)
                    if hid == str(seed.id) or hid in claimed:
                        continue
                    if h.combined_score >= min_similarity:
                        members.append(EntityRef(entity_id=hid, name=h.entity_name,
                                                 usage_count=0))
                        worst = min(worst, h.combined_score)
                if len(members) > 1:
                    for m in members:
                        claimed.add(m.entity_id)
                    clusters.append((members, worst))
            return clusters
        except Exception as exc:  # noqa: BLE001
            logger.warning("consolidation clustering failed: %s", exc)
            return []


def _to_ref(entity: Any) -> EntityRef:
    updated = getattr(entity, "updated_at", None)
    return EntityRef(
        entity_id=str(entity.id),
        name=getattr(entity, "name", "") or "",
        version=int(getattr(entity, "version", 1) or 1),
        usage_count=int(getattr(entity, "usage_count", 0) or 0),
        updated_at=updated.isoformat() if updated is not None else "",
    )
