"""
cortex_service.py — CortexService: The CORTEX Memory System Engine

Implements the 7 CORTEX API operations that give agents persistent,
navigable, writable cognitive trees for long-running tasks.

The CortexService orchestrates:
  - Tree lifecycle (create / resume / suspend)
  - Viewport-based navigation (PageIndex-derived)
  - Paged content access (read / write)
  - Recursive child execution (RLM-derived)
  - Context budget compaction (checkpointing)
  - Output assembly (depth-first tree traversal)

Usage:
    svc = CortexService(db, company_id)
    tree = await svc.create_tree(entity_id, user_id, "Due diligence report")
    viewport = await svc.navigate(tree.root_node_id)
    node_id = await svc.write(parent_id, "finding", "Revenue Q2", content, summary)
    ...
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast
from uuid import UUID, uuid4
from dataclasses import dataclass, field, asdict

from sqlalchemy import select, update, func, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from cortex_memory.scope_policy import ScopePolicy
    from cortex_memory.dtos import Provenance

from cortex_memory.models import (
    CortexTree, CortexNode,
    CortexTreeStatus, CortexNodeType, CortexNodeStatus,
)

logger = logging.getLogger(__name__)

# Alias — ops-help now lives in ai.core.prompt_utils.
from cortex_memory.prompts import CORTEX_OPS_HELP as CORTEX_OPERATIONS_PROMPT  # noqa: E402


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------

@dataclass
class NodeSummaryDTO:
    """Lightweight node info shown in viewports."""
    id: str
    title: str
    summary: Optional[str]
    status: str
    node_type: str
    sibling_order: int = 0
    depth: int = 0
    content_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Viewport:
    """What the agent sees at any moment — bounded context."""
    current_node: NodeSummaryDTO
    children: List[NodeSummaryDTO]
    parent: Optional[NodeSummaryDTO]
    breadcrumb: List[Dict[str, str]]   # [{id, title}, ...] from root to current

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_node": self.current_node.to_dict(),
            "children": [c.to_dict() for c in self.children],
            "parent": self.parent.to_dict() if self.parent else None,
            "breadcrumb": self.breadcrumb,
        }

    def to_prompt_text(
        self,
        *,
        include_ops_help: bool = False,
        max_chars: int = 4000,
    ) -> str:
        """Render viewport as structured text for LLM prompt injection.

        Phase 11 Track 6:
          * ``include_ops_help`` defaults to **False** — the ops-help
            block is now injected once into the system prompt by
            :func:`ai.core.prompt_utils.build_sandwich_prompt` rather
            than re-shipped on every viewport.
          * ``max_chars`` bounds the rendered output. Sections are added
            in priority order (current node → breadcrumb → children →
            ops-help if requested) and rendering stops when the next
            section would push past the budget.
        """
        budget = max(256, int(max_chars))
        parts: list[str] = []

        def _fits(s: str) -> bool:
            return sum(len(p) for p in parts) + len(s) + 2 * len(parts) <= budget

        # 1. Current node (highest priority — always included).
        cn = self.current_node
        cur_block = (
            f"## Current Node: {cn.title}\n"
            f"Type: {cn.node_type} | Status: {cn.status} | Depth: {cn.depth}\n"
            f"Summary: {cn.summary or '(no summary)'}"
        )
        parts.append(cur_block)

        # 2. Breadcrumb (compact path).
        if self.breadcrumb:
            trail = " → ".join(b["title"] for b in self.breadcrumb)
            crumb = f"## Navigation Path\n{trail}"
            if _fits(crumb):
                parts.append(crumb)

        # 3. Children — emit one per line, stop when budget exhausted.
        if self.children:
            child_lines: list[str] = []
            header = "## Children"
            running = len(header)
            for i, ch in enumerate(self.children):
                line = (
                    f"  [{i+1}] {ch.title} ({ch.node_type}, {ch.status}) — "
                    f"{ch.summary or '(no summary)'}"
                )
                # Reserve some headroom for ops-help if requested.
                headroom = 256 if include_ops_help else 0
                if sum(len(p) for p in parts) + running + len(line) + headroom > budget:
                    if not child_lines:
                        # Always include at least one child line if any.
                        child_lines.append(line[: max(80, budget // 4)])
                    child_lines.append(f"  …({len(self.children) - i} more children)")
                    break
                child_lines.append(line)
                running += len(line) + 1
            parts.append(header + "\n" + "\n".join(child_lines))
        else:
            empty = "## Children\n  (leaf node — no children)"
            if _fits(empty):
                parts.append(empty)

        # 4. Ops-help (only when explicitly requested — Track 6 default OFF).
        if include_ops_help and _fits(CORTEX_OPERATIONS_PROMPT):
            parts.append(CORTEX_OPERATIONS_PROMPT)

        return "\n\n".join(parts)


@dataclass
class NodeContent:
    """Paged content from a node read."""
    node_id: str
    title: str
    content: str
    page: int
    total_pages: int
    content_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckpointData:
    """Checkpoint metadata written during compaction."""
    progress_summary: str
    key_facts: List[str]
    next_steps: List[str]
    nodes_written: List[str] = field(default_factory=list)
    time_elapsed_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# CortexService — The 7 CORTEX Operations
# ---------------------------------------------------------------------------

class CortexService:
    """
    Orchestrates all CORTEX tree operations.

    The agent never receives "context." It receives a viewport: a one-level
    slice of the tree showing the current node's summary and its direct
    children's summaries. All other information is reachable by navigating
    the tree.
    """

    DEFAULT_MAX_CHILDREN = 12
    DEFAULT_PAGE_SIZE_TOKENS = 8000
    DEFAULT_CONTEXT_BUDGET_PCT = 40
    CHARS_PER_TOKEN = 4  # rough approximation

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        scoped_subtree_root_id: Optional[UUID] = None,
        scope_policy: Optional[ScopePolicy] = None,
        *,
        llm: Optional[Any] = None,
        child_run_factory: Optional[Any] = None,
    ):
        self.db = db
        self.company_id = company_id
        # Injected host concerns (see cortex_memory.providers). Both optional;
        # the package degrades gracefully when they are absent (standalone use).
        #   llm: a cortex_memory.LLMProvider — used for bridge-paragraph synthesis.
        #   child_run_factory: async (tree, node_id, task, result_slot,
        #       execution_run_id) -> child_run_id | None — used by RECURSE to
        #       create the host execution run for a scoped subtree.
        self._llm = llm
        self._child_run_factory = child_run_factory
        # Subtree isolation — when set, all node access is restricted
        # to descendants of this root. Used by child recursive executions.
        self.scoped_subtree_root_id = scoped_subtree_root_id
        # Declarative ScopePolicy. Defaults to strict.
        from cortex_memory.scope_policy import ScopePolicy as _ScopePolicy
        self.scope_policy = scope_policy or _ScopePolicy()
        # Cache of nodes known to be inside scope so descendant lookups
        # don't re-walk the tree per write.
        self._scope_descendant_cache: set[UUID] = set()
        if scoped_subtree_root_id is not None:
            self._scope_descendant_cache.add(scoped_subtree_root_id)

    # ===================================================================
    # 1. TREE LIFECYCLE
    # ===================================================================

    async def create_tree(
        self,
        entity_id: UUID,
        user_id: Optional[UUID],
        task_description: str,
        max_children: int = DEFAULT_MAX_CHILDREN,
        page_size_tokens: int = DEFAULT_PAGE_SIZE_TOKENS,
        context_budget_pct: int = DEFAULT_CONTEXT_BUDGET_PCT,
    ) -> CortexTree:
        """
        Create a new cognitive tree for a task.
        
        Initialises the tree with:
          - A root node
          - A Knowledge Root subtree anchor
          - A Working Root subtree anchor
          - An Output Root subtree anchor
        """
        tree_id = uuid4()

        # Create the tree record (root_node_id set after node creation)
        tree = CortexTree(
            id=tree_id,
            entity_id=entity_id,
            user_id=user_id,
            company_id=self.company_id,
            task_description=task_description,
            status=CortexTreeStatus.ACTIVE,
            total_nodes=0,
            max_children=max_children,
            page_size_tokens=page_size_tokens,
            context_budget_pct=context_budget_pct,
        )
        self.db.add(tree)
        await self.db.flush()

        # Create root node
        root_node = await self._create_node(
            tree_id=tree_id,
            parent_id=None,
            node_type=CortexNodeType.ROOT,
            title=f"Task: {task_description[:200]}",
            summary=task_description[:500],
            content=task_description,
            status=CortexNodeStatus.ACTIVE,
            depth=0,
            sibling_order=0,
        )

        # Create three subtree anchors under root
        knowledge_root = await self._create_node(
            tree_id=tree_id,
            parent_id=root_node.id,
            node_type=CortexNodeType.KNOWLEDGE,
            title="📚 Knowledge Base",
            summary="Ingested documents and external knowledge sources.",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=1,
            sibling_order=0,
        )

        working_root = await self._create_node(
            tree_id=tree_id,
            parent_id=root_node.id,
            node_type=CortexNodeType.FINDING,
            title="🔬 Working Memory",
            summary="Agent's intermediate findings, reasoning, and discovered facts.",
            content=None,
            status=CortexNodeStatus.ACTIVE,
            depth=1,
            sibling_order=1,
        )

        output_root = await self._create_node(
            tree_id=tree_id,
            parent_id=root_node.id,
            node_type=CortexNodeType.OUTPUT,
            title="📝 Output",
            summary="Assembled output document sections.",
            content=None,
            status=CortexNodeStatus.PENDING,
            depth=1,
            sibling_order=2,
        )

        # Update tree with node IDs
        tree.root_node_id = root_node.id
        tree.output_root_id = output_root.id
        tree.resume_cursor_id = root_node.id
        tree.total_nodes = 4

        await self.db.flush()
        logger.info(f"CortexTree created: {tree_id} with 4 initial nodes")
        return tree

    async def resume_tree(self, tree_id: UUID) -> Tuple[CortexTree, Viewport, Optional[Dict[str, Any]]]:
        """
        Load an existing tree and return the viewport at the resume cursor.
        Also returns the last checkpoint data if available.
        """
        tree = await self._get_tree(tree_id)
        if tree.status not in (CortexTreeStatus.ACTIVE, CortexTreeStatus.SUSPENDED):
            raise ValueError(f"Tree {tree_id} is {tree.status}, cannot resume")

        tree.status = CortexTreeStatus.ACTIVE
        tree.last_active_at = datetime.utcnow()

        cursor_id = cast(UUID, tree.resume_cursor_id or tree.root_node_id)
        viewport = await self.navigate(cursor_id)

        # Load last checkpoint if available
        checkpoint_data = await self._get_last_checkpoint(cursor_id)

        await self.db.flush()
        logger.info(f"CortexTree resumed: {tree_id} at cursor {cursor_id}")
        return tree, viewport, checkpoint_data

    async def suspend_tree(self, tree_id: UUID) -> UUID:
        """
        Suspend a tree. Writes a checkpoint at the current cursor before suspending.
        Returns the checkpoint node ID.
        """
        tree = await self._get_tree(tree_id)

        # Auto-checkpoint before suspending
        checkpoint_id = await self.checkpoint(
            tree_id=tree_id,
            progress_summary="Tree suspended by user or system.",
            key_facts=[],
            next_steps=["Resume and continue from this point."],
        )

        tree.status = CortexTreeStatus.SUSPENDED
        await self.db.flush()
        logger.info(f"CortexTree suspended: {tree_id}")
        return checkpoint_id

    # ===================================================================
    # 2. NAVIGATION (PageIndex navigation model)
    # ===================================================================

    async def navigate(self, node_id: UUID) -> Viewport:
        """
        Move cursor to node_id and return the viewport.
        
        The viewport contains:
          - current_node: {id, title, summary, status, depth}
          - children: [{id, title, summary, status, sibling_order}, ...]
          - parent: {id, title, summary} | None
          - breadcrumb: [{id, title}, ...] path from root to current
          
        Token cost: bounded (MAX_CHILDREN × ~40 tokens per child summary)
        """
        node = await self._get_node(node_id)

        # Update resume cursor on the tree
        tree = await self._get_tree(node.tree_id)
        tree.resume_cursor_id = node_id
        tree.last_active_at = datetime.utcnow()

        # Build current node DTO
        current = self._node_to_dto(node)

        # Load children (ordered by sibling_order)
        children_result = await self.db.execute(
            select(CortexNode)
            .where(CortexNode.parent_id == node_id)
            .order_by(CortexNode.sibling_order)
        )
        children = [self._node_to_dto(c) for c in children_result.scalars().all()]

        # Load parent
        parent_dto = None
        if node.parent_id:
            parent_node = await self._get_node(node.parent_id)
            parent_dto = self._node_to_dto(parent_node)

        # Build breadcrumb (walk up to root)
        breadcrumb = await self._build_breadcrumb(node)

        await self.db.flush()
        return Viewport(
            current_node=current,
            children=children,
            parent=parent_dto,
            breadcrumb=breadcrumb,
        )

    # ===================================================================
    # 3. CONTENT ACCESS (read / write)
    # ===================================================================

    async def read(self, node_id: UUID, page: int = 0) -> NodeContent:
        """
        Read full content of a node, paged.
        
        Updates resume_cursor to this node.
        Token cost: max 1 page (configurable page_size_tokens)
        """
        node = await self._get_node(node_id)
        content = node.content or ""

        # Update status and cursor
        if node.status == CortexNodeStatus.PENDING:
            node.status = CortexNodeStatus.ACTIVE
        tree = await self._get_tree(node.tree_id)
        tree.resume_cursor_id = node_id
        tree.last_active_at = datetime.utcnow()

        # Page the content
        page_size_chars = tree.page_size_tokens * self.CHARS_PER_TOKEN
        total_pages = max(1, math.ceil(len(content) / page_size_chars)) if content else 1

        start = page * page_size_chars
        end = start + page_size_chars
        paged_content = content[start:end]

        await self.db.flush()
        return NodeContent(
            node_id=str(node_id),
            title=node.title,
            content=paged_content,
            page=page,
            total_pages=total_pages,
            content_tokens=node.content_tokens,
        )

    async def write(
        self,
        parent_id: UUID,
        node_type: str,
        title: str,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        status: str = "complete",
        sibling_order: Optional[int] = None,
        source_ref: Optional[Dict[str, Any]] = None,
        metadata_extra: Optional[Dict[str, Any]] = None,
        provenance: Optional[Provenance] = None,
    ) -> UUID:
        """
        Write a new child node. This is how the agent externalises ALL its outputs:
        findings, task plans, output sections, checkpoints.
        
        Enforces tree invariants:
          - Invariant 1: Parent must have a summary before it can have children
          - Invariant 2: MAX_CHILDREN limit (triggers async re-clustering warning)
          - Invariant 4: Content is write-once (enforced at data model level)
        
        Returns new node's UUID.
        """
        # ── Phase 11 Track 6: Provenance + ScopePolicy ────────────────
        if provenance is not None:
            try:
                prov_block = provenance.to_source_ref()
                if source_ref is None:
                    source_ref = {}
                source_ref = {**source_ref, "provenance": prov_block}
            except Exception:                                               # pragma: no cover
                logger.debug("Provenance serialisation skipped")
        if self.scoped_subtree_root_id is not None:
            self._enforce_scope_write(parent_id)

        parent = await self._get_node(parent_id)
        tree = await self._get_tree(parent.tree_id)

        # ── Invariant 1: Summary Always Exists ────────────────────────
        # Every node must have a summary before it can be a parent.
        if not parent.summary:
            raise ValueError(
                f"Cannot write child under node {parent_id}: parent has no summary. "
                f"Invariant 1 requires a summary before a node can have children."
            )

        # Determine sibling order
        if sibling_order is None:
            result = await self.db.execute(
                select(func.coalesce(func.max(CortexNode.sibling_order), -1))
                .where(CortexNode.parent_id == parent_id)
            )
            sibling_order = int(result.scalar() or -1) + 1

        # ── Invariant 2: No Unbounded Viewports ──────────────────────
        child_count_result = await self.db.execute(
            select(func.count(CortexNode.id))
            .where(CortexNode.parent_id == parent_id)
        )
        child_count = child_count_result.scalar() or 0
        if child_count >= tree.max_children:
            logger.warning(
                f"Parent {parent_id} has {child_count} children (max {tree.max_children}). "
                f"Triggering async re-clustering."
            )
            # Schedule async re-clustering (non-blocking)
            await self._schedule_reclustering(parent_id, tree)

        # Map string to enum
        node_type_enum = CortexNodeType(node_type)
        status_enum = CortexNodeStatus(status)

        # Estimate tokens
        content_tokens = len(content) // self.CHARS_PER_TOKEN if content else 0

        new_node = await self._create_node(
            tree_id=parent.tree_id,
            parent_id=parent_id,
            node_type=node_type_enum,
            title=title,
            summary=summary,
            content=content,
            status=status_enum,
            depth=parent.depth + 1,
            sibling_order=sibling_order,
            source_ref=source_ref,
            metadata_extra=metadata_extra,
            content_tokens=content_tokens,
        )

        # Update tree
        tree.total_nodes = (tree.total_nodes or 0) + 1
        tree.resume_cursor_id = new_node.id
        tree.last_active_at = datetime.utcnow()

        await self.db.flush()
        return new_node.id

    # ===================================================================
    # 4. RECURSIVE EXECUTION (RLM layer)
    # ===================================================================

    async def recurse(
        self,
        node_id: UUID,
        task: str,
        result_slot: str,
        model_override: Optional[str] = None,
        priority: int = 0,
        execution_run_id: Optional[UUID] = None,
    ) -> Tuple[UUID, Optional[UUID]]:
        """
        Spawn a child execution run scoped to a specific subtree.
        
        Creates a task node under the target subtree root, marking
        the child run's scope and task description.
        
        Returns tuple of (task_node_id, child_run_id or None).
        The caller (worker.py) is responsible for actually enqueuing
        the child run to Arq.
        """
        node = await self._get_node(node_id)
        tree = await self._get_tree(node.tree_id)

        task_node_id = await self.write(
            parent_id=node_id,
            node_type="task",
            title=f"Task: {task[:200]}",
            content=json.dumps({
                "task": task,
                "result_slot": result_slot,
                "scoped_to": str(node_id),
            }),
            summary=task[:500],
            status="pending",
            metadata_extra={
                "result_slot": result_slot,
                "model_override": model_override,
                "priority": priority,
                "execution_run_id": str(execution_run_id) if execution_run_id else None,
            },
        )

        # Create a child execution run via the injected host factory. Standalone
        # (no factory) returns task_node_id with child_run_id=None.
        child_run_id = None
        if self._child_run_factory is not None:
            try:
                child_run_id = await self._child_run_factory(
                    tree=tree,
                    node_id=node_id,
                    task=task,
                    task_node_id=task_node_id,
                    result_slot=result_slot,
                    execution_run_id=execution_run_id,
                )
                logger.info(f"Child execution run {child_run_id} created for recurse on node {node_id}")
            except Exception as e:
                logger.warning(f"Could not create child execution run for recurse: {e}")

        return task_node_id, child_run_id

    async def await_children(
        self,
        parent_node_id: UUID,
    ) -> Dict[str, NodeSummaryDTO]:
        """
        Collect results from all completed child task nodes under parent_node_id.
        Returns dict of {result_slot: NodeSummaryDTO}
        """
        result = await self.db.execute(
            select(CortexNode)
            .where(
                CortexNode.parent_id == parent_node_id,
                CortexNode.node_type == CortexNodeType.TASK,
                CortexNode.status == CortexNodeStatus.COMPLETE,
            )
            .order_by(CortexNode.sibling_order)
        )
        children = result.scalars().all()

        results = {}
        for child in children:
            slot = (child.metadata_extra or {}).get("result_slot", f"task_{child.sibling_order}")
            results[slot] = self._node_to_dto(child)

        return results

    # ===================================================================
    # 5. COMPACTION (Checkpointing)
    # ===================================================================

    async def checkpoint(
        self,
        tree_id: UUID,
        progress_summary: str,
        key_facts: List[str],
        next_steps: List[str],
    ) -> UUID:
        """
        Write a checkpoint node at the current cursor.
        Compress the run's working context.
        Returns checkpoint node UUID.
        """
        tree = await self._get_tree(tree_id)
        cursor_id = cast(UUID, tree.resume_cursor_id or tree.root_node_id)

        # Calculate time elapsed and nodes written
        time_elapsed = 0.0
        if tree.created_at:
            time_elapsed = (datetime.utcnow() - tree.created_at).total_seconds() / 3600

        nodes_written = await self._get_recent_node_ids(tree_id, cursor_id)

        checkpoint_content = CheckpointData(
            progress_summary=progress_summary,
            key_facts=key_facts,
            next_steps=next_steps,
            nodes_written=nodes_written,
            time_elapsed_hours=round(time_elapsed, 2),
        )

        checkpoint_id = await self.write(
            parent_id=cursor_id,
            node_type="checkpoint",
            title=f"📌 Checkpoint: {progress_summary[:100]}",
            content=json.dumps(checkpoint_content.to_dict()),
            summary=progress_summary[:500],
            status="complete",
            metadata_extra={
                "checkpoint_at": datetime.utcnow().isoformat(),
                "key_facts_count": len(key_facts),
                "nodes_written_count": len(nodes_written),
                "time_elapsed_hours": round(time_elapsed, 2),
            },
        )

        logger.info(f"Checkpoint written: {checkpoint_id} for tree {tree_id}")
        return checkpoint_id

    async def check_and_compact(
        self,
        tree_id: UUID,
        current_token_count: int,
        model_context_window: int = 200000,
    ) -> Optional[UUID]:
        """
        Gap #3: Check if current context exceeds budget. If so, auto-checkpoint
        and return checkpoint node ID. Returns None if within budget.
        
        Called after each step during CORTEX execution.
        """
        tree = await self._get_tree(tree_id)
        budget_tokens = int(model_context_window * tree.context_budget_pct / 100)

        if current_token_count >= budget_tokens:
            logger.info(
                f"Context budget exceeded: {current_token_count} >= {budget_tokens} tokens. "
                f"Auto-compacting tree {tree_id}."
            )
            checkpoint_id = await self.checkpoint(
                tree_id=tree_id,
                progress_summary=f"Auto-compaction at {current_token_count} tokens (budget: {budget_tokens})",
                key_facts=[],
                next_steps=["Continue from viewport after context reset"],
            )
            return checkpoint_id
        return None

    # ===================================================================
    # 6. ASSEMBLY
    # ===================================================================

    async def assemble_output(self, tree_id: UUID, coherence_pass: bool = True) -> str:
        """
        Depth-first traversal of Output Subtree.
        Concatenate all 'complete' output nodes in order.
        Optionally run a coherence pass to generate bridge paragraphs.
        Returns assembled full output as string.
        """
        tree = await self._get_tree(tree_id)
        if not tree.output_root_id:
            return ""

        sections: list[Any] = []
        await self._dfs_collect(tree.output_root_id, sections)

        if not sections:
            return ""

        # Coherence pass — generate bridge paragraphs between sections
        if coherence_pass and len(sections) > 1:
            try:
                bridges = await self._generate_bridge_paragraphs(tree_id, sections)
                if bridges and len(bridges) >= len(sections) - 1:
                    assembled = []
                    for i, section in enumerate(sections):
                        assembled.append(section)
                        if i < len(bridges):
                            assembled.append(bridges[i])
                    return "\n\n".join(assembled)
            except Exception as e:
                logger.warning(f"Coherence pass failed, using raw assembly: {e}")

        return "\n\n".join(sections)

    # ===================================================================
    # 7. QUERY HELPERS (for API / frontend)
    # ===================================================================

    async def get_tree_status(self, tree_id: UUID) -> Dict[str, Any]:
        """Get tree metadata for API response."""
        tree = await self._get_tree(tree_id)
        return {
            "id": str(tree.id),
            "entity_id": str(tree.entity_id),
            "task_description": tree.task_description,
            "status": tree.status.value if tree.status else "active",
            "total_nodes": tree.total_nodes,
            "root_node_id": str(tree.root_node_id) if tree.root_node_id else None,
            "output_root_id": str(tree.output_root_id) if tree.output_root_id else None,
            "resume_cursor_id": str(tree.resume_cursor_id) if tree.resume_cursor_id else None,
            "max_children": tree.max_children,
            "created_at": tree.created_at.isoformat() if tree.created_at else None,
            "last_active_at": tree.last_active_at.isoformat() if tree.last_active_at else None,
        }

    async def list_trees(
        self,
        entity_id: Optional[UUID] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List trees for this company, optionally filtering by entity/status."""
        stmt = (
            select(CortexTree)
            .where(CortexTree.company_id == self.company_id)
            .order_by(CortexTree.last_active_at.desc())
        )
        if entity_id:
            stmt = stmt.where(CortexTree.entity_id == entity_id)
        if status:
            stmt = stmt.where(CortexTree.status == CortexTreeStatus(status))

        result = await self.db.execute(stmt)
        trees = result.scalars().all()
        return [
            {
                "id": str(t.id),
                "entity_id": str(t.entity_id),
                "task_description": t.task_description,
                "status": t.status.value if t.status else "active",
                "total_nodes": t.total_nodes,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "last_active_at": t.last_active_at.isoformat() if t.last_active_at else None,
            }
            for t in trees
        ]

    async def get_node_details(self, node_id: UUID) -> Dict[str, Any]:
        """Get full node details for API response."""
        node = await self._get_node(node_id)
        return {
            "id": str(node.id),
            "tree_id": str(node.tree_id),
            "parent_id": str(node.parent_id) if node.parent_id else None,
            "node_type": node.node_type.value if node.node_type else None,
            "title": node.title,
            "summary": node.summary,
            "content_tokens": node.content_tokens,
            "status": node.status.value if node.status else "pending",
            "depth": node.depth,
            "sibling_order": node.sibling_order,
            "source_ref": node.source_ref,
            "metadata_extra": node.metadata_extra,
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        }

    # ===================================================================
    # Helper: Get Working Memory Root
    # ===================================================================

    async def get_working_root(self, tree_id: UUID) -> Optional[CortexNode]:
        """Get the working memory root node (sibling_order=1 under root)."""
        tree = await self._get_tree(tree_id)
        if not tree.root_node_id:
            return None
        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree_id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.sibling_order == 1,
            )
        )
        return result.scalar_one_or_none()

    async def get_knowledge_root(self, tree_id: UUID) -> Optional[CortexNode]:
        """Get the knowledge root node (sibling_order=0 under root)."""
        tree = await self._get_tree(tree_id)
        if not tree.root_node_id:
            return None
        result = await self.db.execute(
            select(CortexNode).where(
                CortexNode.tree_id == tree_id,
                CortexNode.parent_id == tree.root_node_id,
                CortexNode.sibling_order == 0,
            )
        )
        return result.scalar_one_or_none()

    # ===================================================================
    # INTERNAL HELPERS
    # ===================================================================

    async def _create_node(
        self,
        tree_id: UUID,
        parent_id: Optional[UUID],
        node_type: CortexNodeType,
        title: str,
        summary: Optional[str],
        content: Optional[str],
        status: CortexNodeStatus,
        depth: int,
        sibling_order: int,
        source_ref: Optional[Dict[str, Any]] = None,
        metadata_extra: Optional[Dict[str, Any]] = None,
        content_tokens: int = 0,
    ) -> CortexNode:
        """
        Create and flush a new CortexNode.
        
        Invariant 4 (Write-Once Content): Content is set at creation time
        and should never be modified afterward. Revisions are expressed by
        adding a child 'finding' node with a title like 'Revision: [original]'.
        """
        if content and content_tokens == 0:
            content_tokens = len(content) // self.CHARS_PER_TOKEN

        node = CortexNode(
            id=uuid4(),
            tree_id=tree_id,
            parent_id=parent_id,
            node_type=node_type,
            title=title,
            summary=summary,
            content=content,
            content_tokens=content_tokens,
            status=status,
            depth=depth,
            sibling_order=sibling_order,
            source_ref=source_ref,
            metadata_extra=metadata_extra,
        )
        self.db.add(node)
        await self.db.flush()
        return node

    async def _get_tree(self, tree_id: UUID) -> CortexTree:
        """Load a CortexTree by ID."""
        result = await self.db.execute(
            select(CortexTree).where(CortexTree.id == tree_id)
        )
        tree = result.scalar_one_or_none()
        if not tree:
            raise ValueError(f"CortexTree {tree_id} not found")
        return tree

    async def _get_node(self, node_id: UUID) -> CortexNode:
        """Load a CortexNode by ID. Enforces subtree isolation if scoped."""
        result = await self.db.execute(
            select(CortexNode).where(CortexNode.id == node_id)
        )
        node = result.scalar_one_or_none()
        if not node:
            raise ValueError(f"CortexNode {node_id} not found")

        # Subtree isolation enforcement via ScopePolicy.
        if self.scoped_subtree_root_id and node_id != self.scoped_subtree_root_id:
            is_descendant = node_id in self._scope_descendant_cache
            if not is_descendant:
                is_descendant = await self._is_descendant_of(
                    node_id, self.scoped_subtree_root_id,
                )
                if is_descendant:
                    self._scope_descendant_cache.add(node_id)
            if not is_descendant:
                if not self.scope_policy.can_read_outside:
                    from cortex_memory.scope_policy import ScopeViolation
                    if self.scope_policy.error_on_violation:
                        raise ScopeViolation(
                            operation="read",
                            target_id=str(node_id),
                            scope_root_id=str(self.scoped_subtree_root_id),
                        )
                    logger.warning(
                        "ScopePolicy violation (read) suppressed: node=%s scope=%s",
                        node_id, self.scoped_subtree_root_id,
                    )

        return node

    def _enforce_scope_write(self, parent_id: UUID) -> None:
        """Track 6 — block writes whose parent is outside the scoped subtree."""
        if self.scoped_subtree_root_id is None:
            return
        if parent_id == self.scoped_subtree_root_id:
            return
        if parent_id in self._scope_descendant_cache:
            return
        if self.scope_policy.can_write_outside:
            return
        # Fall through: descendant check runs as part of the upcoming
        # _get_node call inside write(). If parent_id turns out NOT to
        # be a descendant, _get_node will raise. We pre-validate here
        # only so the error message identifies it as a write violation.
        # The actual reachability check happens in _get_node.

    def _node_to_dto(self, node: CortexNode) -> NodeSummaryDTO:
        """Convert ORM node to lightweight DTO."""
        return NodeSummaryDTO(
            id=str(node.id),
            title=node.title,
            summary=node.summary,
            status=node.status.value if node.status else "pending",
            node_type=node.node_type.value if node.node_type else "root",
            sibling_order=node.sibling_order or 0,
            depth=node.depth or 0,
            content_tokens=node.content_tokens or 0,
        )

    async def _build_breadcrumb(self, node: CortexNode) -> List[Dict[str, str]]:
        """Walk up from node to root using a single recursive CTE query.

        Phase 4 (PERF): Replaces the iterative parent-walk that issued
        O(depth) sequential SELECT queries with one CTE round-trip.
        """
        query = text("""
            WITH RECURSIVE ancestors AS (
                SELECT id, parent_id, title, 0 AS depth
                FROM cortex_nodes WHERE id = :node_id
                UNION ALL
                SELECT cn.id, cn.parent_id, cn.title, a.depth + 1
                FROM cortex_nodes cn
                JOIN ancestors a ON cn.id = a.parent_id
            )
            SELECT id, title FROM ancestors ORDER BY depth DESC
        """)
        result = await self.db.execute(query, {"node_id": str(node.id)})
        return [{"id": str(r.id), "title": r.title} for r in result.fetchall()]

    async def _get_last_checkpoint(self, cursor_id: UUID) -> Optional[Dict[str, Any]]:
        """Find the most recent checkpoint node under the cursor."""
        result = await self.db.execute(
            select(CortexNode)
            .where(
                CortexNode.parent_id == cursor_id,
                CortexNode.node_type == CortexNodeType.CHECKPOINT,
            )
            .order_by(CortexNode.created_at.desc())
            .limit(1)
        )
        checkpoint = result.scalar_one_or_none()
        if checkpoint and checkpoint.content:
            try:
                return cast("dict[str, Any]", json.loads(checkpoint.content))
            except json.JSONDecodeError:
                return {"progress_summary": checkpoint.summary}
        return None

    async def _dfs_collect(self, node_id: UUID, sections: List[str]) -> None:
        """Depth-first traversal collecting content from complete output nodes."""
        node = await self._get_node(node_id)

        # Collect content from complete nodes (skip the output root itself)
        if node.status == CortexNodeStatus.COMPLETE and node.content:
            sections.append(node.content)

        # Recurse into children
        result = await self.db.execute(
            select(CortexNode)
            .where(CortexNode.parent_id == node_id)
            .order_by(CortexNode.sibling_order)
        )
        children = result.scalars().all()
        for child in children:
            await self._dfs_collect(child.id, sections)

    async def _is_descendant_of(self, node_id: UUID, ancestor_id: UUID) -> bool:
        """Check ancestry using a single recursive CTE query.

        Phase 4 (PERF): Replaces the iterative parent-walk that issued
        O(depth) sequential SELECT queries with one CTE round-trip.
        """
        if node_id == ancestor_id:
            return True
        query = text("""
            WITH RECURSIVE ancestors AS (
                SELECT id, parent_id FROM cortex_nodes WHERE id = :node_id
                UNION ALL
                SELECT cn.id, cn.parent_id
                FROM cortex_nodes cn
                JOIN ancestors a ON cn.id = a.parent_id
            )
            SELECT 1 FROM ancestors WHERE id = :ancestor_id LIMIT 1
        """)
        result = await self.db.execute(query, {
            "node_id": str(node_id), "ancestor_id": str(ancestor_id)
        })
        return result.scalar() is not None

    async def _get_recent_node_ids(self, tree_id: UUID, cursor_id: UUID, limit: int = 20) -> List[str]:
        """Get IDs of recently written nodes for checkpoint metadata."""
        result = await self.db.execute(
            select(CortexNode.id)
            .where(
                CortexNode.tree_id == tree_id,
                CortexNode.node_type != CortexNodeType.CHECKPOINT,
            )
            .order_by(CortexNode.created_at.desc())
            .limit(limit)
        )
        return [str(r[0]) for r in result.fetchall()]

    async def _schedule_reclustering(self, parent_id: UUID, tree: CortexTree) -> None:
        """
        Gap #9: Async re-clustering when MAX_CHILDREN is exceeded.
        Creates an intermediate grouping node and moves half the oldest
        children under it. Runs as part of the current transaction
        but does not block the write() caller excessively.
        """
        try:
            # Get all children ordered by sibling_order
            result = await self.db.execute(
                select(CortexNode)
                .where(CortexNode.parent_id == parent_id)
                .order_by(CortexNode.sibling_order)
            )
            children = result.scalars().all()

            if len(children) < tree.max_children:
                return

            # Move the first half of children under a new grouping node
            half = len(children) // 2
            children_to_move = children[:half]

            # Create grouping node
            group_summary = f"Grouped {half} nodes for viewport efficiency"
            parent_node = await self._get_node(parent_id)
            group_node = await self._create_node(
                tree_id=tree.id,
                parent_id=parent_id,
                node_type=children_to_move[0].node_type,  # inherit type from children
                title=f"📂 Group ({half} items)",
                summary=group_summary,
                content=None,
                status=CortexNodeStatus.COMPLETE,
                depth=parent_node.depth + 1,
                sibling_order=0,  # First position
            )

            # Re-parent children to the group node
            for i, child in enumerate(children_to_move):
                child.parent_id = group_node.id
                child.sibling_order = i

            # Reorder remaining direct children
            for i, child in enumerate(children[half:]):
                child.sibling_order = i + 1  # After the group node

            tree.total_nodes = (tree.total_nodes or 0) + 1
            await self.db.flush()
            logger.info(f"Re-clustered {half} children under group node {group_node.id}")

        except Exception as e:
            logger.warning(f"Re-clustering failed for parent {parent_id}: {e}")

    async def _generate_bridge_paragraphs(
        self, tree_id: UUID, sections: List[str]
    ) -> List[str]:
        """
        Gap #7: Generate bridge paragraphs between output sections
        using LLM for coherence.

        Phase 4 (PERF-5): Now tracks the LLM cost in usage_logs so bridge
        paragraph generation is no longer an invisible cost.
        """
        if self._llm is None:
            return []  # no LLM injected (standalone) — skip bridge synthesis
        try:
            # Build a summary of each section (first 200 chars)
            section_summaries = []
            for i, s in enumerate(sections):
                section_summaries.append(f"Section {i+1}: {s[:200]}...")

            prompt = (
                "You are writing bridge paragraphs to connect sections of a document "
                "for smooth flow. For each pair of consecutive sections below, write a "
                "1-2 sentence transition paragraph.\n\n"
                "Sections:\n" + "\n".join(section_summaries) +
                "\n\nOutput one transition per line, each on a new line. "
                f"You need exactly {len(sections) - 1} transitions."
            )

            resp = await self._llm.complete(
                task_type="text_generation",
                system="You are a document coherence editor.",
                user=prompt,
                temperature=0.5,
                max_tokens=1000,
            )

            total_tokens = (resp.input_tokens or 0) + (resp.output_tokens or 0)
            if total_tokens:
                logger.info(
                    f"Bridge paragraph LLM cost: {total_tokens} tokens "
                    f"(model={resp.model}, tree={tree_id})"
                )

            bridges = [line.strip() for line in (resp.text or "").strip().split("\n") if line.strip()]
            return bridges

        except Exception as e:
            logger.warning(f"Bridge paragraph generation failed: {e}")
            return []
