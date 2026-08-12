"""
ai.meta.meta_intelligence_tree — Platform-scoped IntelligenceTree owned
by the Meta-Agent (Phase 11 Track 5).

One tree per company. Reuses the existing CORTEX schema; the only
distinguishing feature is ``scope_level=TENANT`` and the absence of an
owning ``entity_id`` — the tree belongs to the Meta-Agent role across
the whole tenant.

Layout::

    MetaIntelligenceTree (scope=tenant, owner=meta-agent role)
    ├── 📏 Architecture Anti-Patterns      ← written by Critic
    ├── 🎯 Spec Patterns                    ← written by Curator + Promoter
    ├── 🚨 Test Failure Tags                ← written by TestDriver
    ├── 🧠 Curator Decisions                ← written by Curator
    ├── 🔧 Tool Reliability                 ← written by post-Promoter monitor
    └── 📝 Prompt-Update Candidates         ← written by prompt-evo cron

Nodes inside each section are typed by ``metadata_extra["kind"]``
(e.g. ``"anti_pattern"``, ``"skill_candidate"``,
``"prompt_update_candidate"``). This avoids requiring a new
``CortexNodeType`` enum value per row variety while still letting
queries filter cleanly.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, cast
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


SECTIONS: dict[str, str] = {
    "anti_patterns":   "📏 Architecture Anti-Patterns",
    "spec_patterns":   "🎯 Spec Patterns",
    "test_failures":   "🚨 Test Failure Tags",
    "curator_dec":     "🧠 Curator Decisions",
    "tool_reliab":     "🔧 Tool Reliability",
    "prompt_cand":     "📝 Prompt-Update Candidates",
    "composition":     "🔗 Composition Graph",
}

# Cap on how many anti-pattern nodes we keep per section. The Critic
# prompt only reads top_k anyway; older rows are pruned via LRU on
# ``last_seen``.
MAX_ROWS_PER_SECTION: int = 200


@dataclass
class AntiPatternRow:
    title: str
    suggestion: str
    evidence_count: int = 1
    related_tags: Optional[list[str]] = None
    last_seen: Optional[str] = None
    node_id: Optional[UUID] = None

    @property
    def text(self) -> str:
        if self.suggestion:
            return f"{self.title} — fix: {self.suggestion}"
        return self.title


__all__ = [
    "MetaIntelligenceTree",
    "SECTIONS",
    "AntiPatternRow",
    "MAX_ROWS_PER_SECTION",
]


class MetaIntelligenceTree:
    """Per-company tree wrapper. Cheap to instantiate."""

    def __init__(self, db: Any, company_id: UUID):
        self.db = db
        self.company_id = company_id

    # ------------------------------------------------------------------
    # Tree / section bootstrap
    # ------------------------------------------------------------------

    async def ensure_tree(self) -> Any:
        from src.ai.memory.cortex_models import (
            CortexNode,
            CortexNodeStatus,
            CortexNodeType,
            CortexTree,
            CortexTreeStatus,
            MemoryDomain,
            ScopeLevel,
        )
        from sqlalchemy import select

        # One platform-scoped tree per company.
        result = await self.db.execute(
            select(CortexTree).where(
                CortexTree.company_id == self.company_id,
                CortexTree.entity_id.is_(None),
                CortexTree.memory_domain == MemoryDomain.INTELLIGENCE,
                CortexTree.scope_level == ScopeLevel.TENANT,
                CortexTree.status != CortexTreeStatus.ARCHIVED,
            )
        )
        tree = result.scalar_one_or_none()
        if tree:
            return tree

        tree = CortexTree(
            id=uuid4(),
            company_id=self.company_id,
            entity_id=None,
            task_description="Meta-Agent platform intelligence",
            status=CortexTreeStatus.ACTIVE,
            memory_domain=MemoryDomain.INTELLIGENCE,
            scope_level=ScopeLevel.TENANT,
            is_persistent=True,
            total_nodes=0,
            max_children=200,
            page_size_tokens=8000,
            context_budget_pct=30,
        )
        self.db.add(tree)
        await self.db.flush()

        root = CortexNode(
            id=uuid4(),
            tree_id=tree.id,
            parent_id=None,
            node_type=CortexNodeType.ROOT,
            title="🧠 Meta Intelligence",
            summary="Platform-scoped intelligence owned by the Meta-Agent role.",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=0,
            sibling_order=0,
        )
        self.db.add(root)
        await self.db.flush()
        tree.root_node_id = root.id
        tree.total_nodes = 1

        for idx, (key, title) in enumerate(SECTIONS.items()):
            section = CortexNode(
                id=uuid4(),
                tree_id=tree.id,
                parent_id=root.id,
                node_type=CortexNodeType.GROUP,
                title=title,
                summary=f"Meta-intelligence section: {key}",
                content=None,
                status=CortexNodeStatus.ACTIVE,
                depth=1,
                sibling_order=idx,
            )
            self.db.add(section)
            tree.total_nodes += 1
        await self.db.flush()
        return tree

    async def section_node(self, section_key: str) -> Optional[Any]:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        title = SECTIONS.get(section_key)
        if not title:
            raise ValueError(f"Unknown MetaIntelligenceTree section: {section_key}")
        tree = await self.ensure_tree()
        node = (await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree.id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.title == title,
            )
        )).scalar_one_or_none()
        if node is not None:
            return node
        # Lazily create a section missing on an older tree (a new SECTIONS entry
        # added after the tree was first built). Idempotent.
        return await self._create_section(tree, title)

    async def _create_section(self, tree: Any, title: str) -> Any:
        from sqlalchemy import func, select
        from src.ai.memory.cortex_models import CortexNode, CortexNodeStatus, CortexNodeType
        order = (await self.db.execute(
            select(func.coalesce(func.max(CortexNode.sibling_order), -1))
            .where(CortexNode.parent_id == tree.root_node_id)
        )).scalar() + 1
        section = CortexNode(
            id=uuid4(),
            tree_id=tree.id,
            parent_id=tree.root_node_id,
            node_type=CortexNodeType.GROUP,
            title=title,
            summary=f"Meta-intelligence section: {title}",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=1,
            sibling_order=order,
        )
        self.db.add(section)
        await self.db.flush()
        return section

    # ------------------------------------------------------------------
    # Anti-patterns (Critic)
    # ------------------------------------------------------------------

    async def add_anti_pattern(
        self,
        *,
        title: str,
        suggestion: str = "",
        evidence_count: int = 1,
        related_tags: Optional[list[str]] = None,
        severity: str = "med",
    ) -> Optional[UUID]:
        if not title:
            return None
        section = await self.section_node("anti_patterns")
        if section is None:
            return None
        # De-dup by title — bump evidence_count if it already exists.
        existing = await self._find_in_section(section.id, title)
        if existing is not None:
            meta = dict(existing.metadata_extra or {})
            meta["evidence_count"] = int(meta.get("evidence_count", 1)) + evidence_count
            meta["last_seen"] = datetime.utcnow().isoformat()
            existing.metadata_extra = meta
            await self.db.flush()
            return cast(UUID, existing.id)
        node_id = await self._add_node(
            section_id=section.id,
            kind="anti_pattern",
            title=title[:120],
            summary=(suggestion or title)[:300],
            content=json.dumps({
                "title": title, "suggestion": suggestion,
                "related_tags": list(related_tags or []),
                "severity": severity,
            }),
            metadata={
                "evidence_count": evidence_count,
                "related_tags": list(related_tags or []),
                "severity": severity,
                "last_seen": datetime.utcnow().isoformat(),
            },
        )
        await self._maybe_prune_section(section.id)
        return node_id

    async def query_anti_patterns(
        self,
        *,
        entity_type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> list[AntiPatternRow]:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        section = await self.section_node("anti_patterns")
        if section is None:
            return []
        rows = (await self.db.execute(
            select(CortexNode).where(
                CortexNode.parent_id == section.id,
            ).order_by(CortexNode.updated_at.desc()).limit(top_k * 5)
        )).scalars().all()

        wanted_tags = {t.lower() for t in (tags or [])}
        out: list[AntiPatternRow] = []
        for r in rows:
            meta = r.metadata_extra or {}
            if (meta.get("kind") or "") != "anti_pattern":
                continue
            row_tags = {str(t).lower() for t in (meta.get("related_tags") or [])}
            if wanted_tags and not (row_tags & wanted_tags):
                continue
            try:
                payload = json.loads(r.content or "{}")
            except Exception:
                payload = {}
            out.append(AntiPatternRow(
                title=str(payload.get("title", r.title)),
                suggestion=str(payload.get("suggestion", "")),
                evidence_count=int(meta.get("evidence_count", 1)),
                related_tags=list(meta.get("related_tags") or []),
                last_seen=meta.get("last_seen"),
                node_id=r.id,
            ))
            if len(out) >= top_k:
                break
        return out

    # ------------------------------------------------------------------
    # Curator decisions
    # ------------------------------------------------------------------

    async def record_curator_decision(
        self,
        *,
        decision: str,
        candidates: list[dict[str, Any]] | None = None,
        rationale: str = "",
        outcome: Optional[str] = None,
    ) -> Optional[UUID]:
        section = await self.section_node("curator_dec")
        if section is None:
            return None
        return await self._add_node(
            section_id=section.id,
            kind="curator_decision",
            title=f"{decision}"[:80],
            summary=rationale[:300] or f"Curator decided: {decision}",
            content=json.dumps({
                "decision": decision,
                "candidates": list(candidates or [])[:5],
                "rationale": rationale,
                "outcome": outcome,
            }, default=str),
            metadata={"decision": decision, "outcome": outcome},
        )

    # ------------------------------------------------------------------
    # Test failures (TestDriver)
    # ------------------------------------------------------------------

    async def add_test_failure(
        self, *, entity_id: Optional[UUID], tag: str, kind: str = "smoke",
    ) -> Optional[UUID]:
        section = await self.section_node("test_failures")
        if section is None:
            return None
        title = f"{kind}:{tag}"[:120]
        existing = await self._find_in_section(section.id, title)
        if existing is not None:
            meta = dict(existing.metadata_extra or {})
            meta["count"] = int(meta.get("count", 1)) + 1
            meta["last_seen"] = datetime.utcnow().isoformat()
            existing.metadata_extra = meta
            await self.db.flush()
            return cast(UUID, existing.id)
        return await self._add_node(
            section_id=section.id, kind="test_failure",
            title=title,
            summary=f"Test {kind} flagged tag={tag}",
            content=json.dumps({"tag": tag, "kind": kind,
                                "entity_id": str(entity_id) if entity_id else None}),
            metadata={"tag": tag, "kind": kind, "count": 1,
                      "last_seen": datetime.utcnow().isoformat()},
        )

    # ------------------------------------------------------------------
    # Tool reliability samples
    # ------------------------------------------------------------------

    async def add_tool_reliability_sample(
        self, *, tool_id: str, task_class: str, success: bool,
    ) -> Optional[UUID]:
        section = await self.section_node("tool_reliab")
        if section is None:
            return None
        title = f"{tool_id}@{task_class}"[:120]
        existing = await self._find_in_section(section.id, title)
        if existing is not None:
            meta = dict(existing.metadata_extra or {})
            meta["pulls"] = int(meta.get("pulls", 0)) + 1
            if success:
                meta["successes"] = int(meta.get("successes", 0)) + 1
            existing.metadata_extra = meta
            await self.db.flush()
            return cast(UUID, existing.id)
        return await self._add_node(
            section_id=section.id, kind="tool_reliability",
            title=title,
            summary=f"Reliability sample for tool {tool_id} on {task_class}",
            content=json.dumps({"tool_id": tool_id, "task_class": task_class}),
            metadata={"tool_id": tool_id, "task_class": task_class,
                      "pulls": 1, "successes": int(bool(success))},
        )

    # ------------------------------------------------------------------
    # Cross-entity composition graph (Phase 12 `06` §4.2)
    # ------------------------------------------------------------------

    async def record_composition(
        self, *, parent_id: UUID, child_id: UUID, outcome_score: float,
    ) -> Optional[UUID]:
        """Record a ``parent composed child`` edge + its rolling outcome score.

        ``outcome_score`` ∈ [0,1]; repeated edges accumulate a running mean so the
        Curator/Architect can prefer proven compositions over novel ones.
        """
        section = await self.section_node("composition")
        if section is None:
            return None
        title = f"{parent_id}->{child_id}"[:120]
        score = max(0.0, min(1.0, float(outcome_score)))
        existing = await self._find_in_section(section.id, title)
        if existing is not None:
            meta = dict(existing.metadata_extra or {})
            n = int(meta.get("count", 0)) + 1
            mean = float(meta.get("outcome_score", 0.0))
            meta["count"] = n
            meta["outcome_score"] = mean + (score - mean) / n  # incremental mean
            existing.metadata_extra = meta
            await self.db.flush()
            return cast(UUID, existing.id)
        return await self._add_node(
            section_id=section.id, kind="composition", title=title,
            summary=f"{parent_id} composed {child_id}",
            content=json.dumps({"parent_id": str(parent_id), "child_id": str(child_id)}),
            metadata={"parent_id": str(parent_id), "child_id": str(child_id),
                      "count": 1, "outcome_score": score},
        )

    async def query_compositions(
        self, *, parent_id: Optional[UUID] = None, child_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List composition edges, optionally filtered by parent and/or child."""
        rows = await self._list_kind("composition", "composition", limit * 4)
        out: list[dict[str, Any]] = []
        for r in rows:
            meta = r.get("metadata") or {}
            if parent_id and meta.get("parent_id") != str(parent_id):
                continue
            if child_id and meta.get("child_id") != str(child_id):
                continue
            out.append({
                "parent_id": meta.get("parent_id"),
                "child_id": meta.get("child_id"),
                "count": int(meta.get("count", 0)),
                "outcome_score": float(meta.get("outcome_score", 0.0)),
            })
        out.sort(key=lambda d: (d["outcome_score"], d["count"]), reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------
    # Spec patterns / skill candidates (Curator + SkillLibrary)
    # ------------------------------------------------------------------

    async def add_skill_candidate(
        self,
        *,
        source_entity_id: UUID,
        chain: list[str],
        frequency: int,
        suggestion: str = "",
    ) -> Optional[UUID]:
        section = await self.section_node("spec_patterns")
        if section is None:
            return None
        title = f"Skill: {' → '.join(chain)[:100]}"
        return await self._add_node(
            section_id=section.id,
            kind="skill_candidate",
            title=title[:120],
            summary=(suggestion or f"Tool chain seen {frequency}× — promote to SKILL?")[:300],
            content=json.dumps({
                "chain": list(chain),
                "frequency": int(frequency),
                "source_entity_id": str(source_entity_id),
                "suggestion": suggestion,
            }),
            metadata={
                "kind": "skill_candidate",
                "frequency": int(frequency),
                "source_entity_id": str(source_entity_id),
            },
        )

    async def list_skill_candidates(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._list_kind("spec_patterns", "skill_candidate", limit)

    async def get_skill_candidate(self, node_id: UUID) -> Optional[dict[str, Any]]:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        row = (await self.db.execute(
            select(CortexNode).where(CortexNode.id == node_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        meta = row.metadata_extra or {}
        if (meta.get("kind") or "") != "skill_candidate":
            return None
        try:
            content = json.loads(row.content or "{}")
        except Exception:
            content = {}
        return {
            "node_id": str(row.id),
            "title": row.title,
            "summary": row.summary,
            "metadata": dict(meta),
            "content": content,
        }

    async def mark_skill_candidate_promoted(
        self, node_id: UUID, *, promoted_entity_id: UUID,
    ) -> bool:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        row = (await self.db.execute(
            select(CortexNode).where(CortexNode.id == node_id)
        )).scalar_one_or_none()
        if row is None:
            return False
        meta = dict(row.metadata_extra or {})
        if meta.get("kind") != "skill_candidate":
            return False
        meta["promoted"] = True
        meta["promoted_at"] = datetime.utcnow().isoformat()
        meta["promoted_entity_id"] = str(promoted_entity_id)
        row.metadata_extra = meta
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Prompt-update candidates (HITL-gated)
    # ------------------------------------------------------------------

    async def add_prompt_update_candidate(
        self,
        *,
        prompt_diff: str,
        rationale: str,
        evidence_run_ids: Optional[list[str]] = None,
    ) -> Optional[UUID]:
        section = await self.section_node("prompt_cand")
        if section is None:
            return None
        return await self._add_node(
            section_id=section.id,
            kind="prompt_update_candidate",
            title=(rationale or "Meta-Agent prompt candidate")[:120],
            summary=rationale[:300],
            content=json.dumps({
                "prompt_diff": prompt_diff,
                "rationale": rationale,
                "evidence_run_ids": list(evidence_run_ids or []),
            }),
            metadata={
                "kind": "prompt_update_candidate",
                "approved": False,
            },
        )

    async def list_prompt_candidates(self, *, only_pending: bool = True, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self._list_kind("prompt_cand", "prompt_update_candidate", limit * 3)
        if only_pending:
            rows = [r for r in rows if not (r.get("metadata", {}).get("approved"))]
        return rows[:limit]

    async def approve_prompt_candidate(self, node_id: UUID) -> bool:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        row = (await self.db.execute(
            select(CortexNode).where(CortexNode.id == node_id)
        )).scalar_one_or_none()
        if row is None:
            return False
        meta = dict(row.metadata_extra or {})
        if meta.get("kind") != "prompt_update_candidate":
            return False
        meta["approved"] = True
        meta["approved_at"] = datetime.utcnow().isoformat()
        row.metadata_extra = meta
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _add_node(
        self,
        *,
        section_id: UUID,
        kind: str,
        title: str,
        summary: str,
        content: str,
        metadata: dict[str, Any],
    ) -> Optional[UUID]:
        from sqlalchemy import select, func
        from src.ai.memory.cortex_models import (
            CortexNode,
            CortexNodeStatus,
            CortexNodeType,
        )
        # Choose node_type by kind for prettier listings.
        node_type = {
            "anti_pattern":            CortexNodeType.INSTRUCTION,
            "skill_candidate":         CortexNodeType.STRATEGY,
            "curator_decision":        CortexNodeType.STRATEGY,
            "test_failure":            CortexNodeType.FINDING,
            "tool_reliability":        CortexNodeType.FINDING,
            "prompt_update_candidate": CortexNodeType.INSTRUCTION,
            "composition":             CortexNodeType.FINDING,
        }.get(kind, CortexNodeType.FINDING)

        section = (await self.db.execute(
            select(CortexNode).where(CortexNode.id == section_id)
        )).scalar_one_or_none()
        if section is None:
            return None

        order = (await self.db.execute(
            select(func.coalesce(func.max(CortexNode.sibling_order), -1))
            .where(CortexNode.parent_id == section_id)
        )).scalar() + 1

        meta = dict(metadata or {})
        meta.setdefault("kind", kind)

        node = CortexNode(
            id=uuid4(),
            tree_id=section.tree_id,
            parent_id=section_id,
            node_type=node_type,
            title=title,
            summary=summary,
            content=content,
            status=CortexNodeStatus.ACTIVE,
            depth=section.depth + 1,
            sibling_order=order,
            metadata_extra=meta,
        )
        self.db.add(node)
        await self.db.flush()
        return node.id

    async def _find_in_section(self, section_id: UUID, title: str) -> Any:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        return (await self.db.execute(
            select(CortexNode).where(
                CortexNode.parent_id == section_id,
                CortexNode.title == title,
            )
        )).scalar_one_or_none()

    async def _list_kind(self, section_key: str, kind: str, limit: int) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from src.ai.memory.cortex_models import CortexNode
        section = await self.section_node(section_key)
        if section is None:
            return []
        rows = (await self.db.execute(
            select(CortexNode).where(
                CortexNode.parent_id == section.id,
            ).order_by(CortexNode.created_at.desc()).limit(limit * 3)
        )).scalars().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            meta = r.metadata_extra or {}
            if (meta.get("kind") or "") != kind:
                continue
            try:
                content = json.loads(r.content or "{}")
            except Exception:
                content = {}
            out.append({
                "node_id": str(r.id),
                "title": r.title,
                "summary": r.summary,
                "metadata": dict(meta),
                "content": content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
            if len(out) >= limit:
                break
        return out

    async def _maybe_prune_section(self, section_id: UUID) -> None:
        from sqlalchemy import select, func
        from src.ai.memory.cortex_models import CortexNode
        count = (await self.db.execute(
            select(func.count(CortexNode.id)).where(CortexNode.parent_id == section_id)
        )).scalar() or 0
        if count <= MAX_ROWS_PER_SECTION:
            return
        # Delete the oldest rows beyond the cap.
        excess = count - MAX_ROWS_PER_SECTION
        oldest = (await self.db.execute(
            select(CortexNode).where(CortexNode.parent_id == section_id)
            .order_by(CortexNode.updated_at.asc()).limit(excess)
        )).scalars().all()
        for row in oldest:
            await self.db.delete(row)
        await self.db.flush()
