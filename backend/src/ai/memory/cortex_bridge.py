"""
cortex_bridge.py — CORTEX tree lifecycle management.

Extracted from ExecutionEngine during Phase 6 monolith decomposition
(Step 3.3). Handles all interactions with the CORTEX knowledge tree:
writing step results, ingesting tool output, executing CORTEX-native
step types (NAVIGATE, READ, WRITE, RECURSE, AWAIT_CHILDREN), and
viewport/checkpoint management.
"""
import json
import logging
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from src.ai.memory.cortex_service import CortexService
from src.ai.schemas import StepType, PlanStep, PlanStepTarget
from src.ai.usage_service import UsageService

logger = logging.getLogger(__name__)


# A: Direct import — no circular dependency after extraction to ai.core
from src.ai.core.prompt_utils import parse_variables as _parse_variables


class CortexBridge:
    """Manages CORTEX tree reads, writes, navigation, and checkpoints."""

    VIEWPORT_CACHE_TTL = 30  # seconds

    def __init__(self, db: Any, company_id: UUID, usage_service: Optional[UsageService] = None, redis: Any = None) -> None:
        self.db = db
        self.company_id = company_id
        self.cortex = CortexService(db=db, company_id=company_id)
        self.usage_service = usage_service or UsageService(db)
        self.redis = redis  # optional Redis for viewport caching
        self._write_buffer: list[dict[str, Any]] = []  # batch node write buffer
        self._context_size_bytes: int = 0  # incremental size tracker

    # ------------------------------------------------------------------
    # Context Size Tracking (Phase 6 — PERF-3)
    # ------------------------------------------------------------------

    def update_context_size(self, key: str, old_value: str = "", new_value: str = "") -> None:
        """Incrementally update tracked context size in bytes.

        Called by the orchestrator whenever context_state is mutated
        (e.g. _store_step_output). Avoids O(n) full scan per checkpoint.
        """
        self._context_size_bytes -= len(str(old_value)) if old_value else 0
        self._context_size_bytes += len(str(new_value)) if new_value else 0
        # Clamp to zero in case of drift
        if self._context_size_bytes < 0:
            self._context_size_bytes = 0

    def reset_context_size(self, context_state: dict[str, Any]) -> None:
        """Full recalculation — call once at run start."""
        self._context_size_bytes = sum(len(str(v)) for v in context_state.values())

    # ------------------------------------------------------------------
    # Task Description
    # ------------------------------------------------------------------

    def build_task_description(self, entity: Any, input_data: dict[str, Any]) -> str:
        """Build a CORTEX task description from entity and input."""
        input_summary = ""
        if input_data:
            input_keys = [k for k in input_data.keys() if not k.startswith("__")]
            input_summary = ", ".join(
                f"{k}={str(input_data[k])[:100]}" for k in input_keys[:5]
            )
        task_desc = f"{entity.name}: {input_summary}" if input_summary else entity.name
        return task_desc[:1000]

    # ------------------------------------------------------------------
    # Step Writing
    # ------------------------------------------------------------------

    async def write_step(
        self,
        cortex: CortexService,
        working_root_id: UUID,
        step_result: dict[str, Any],
        run_id: UUID,
    ) -> None:
        """Write a step's result as a finding node in the CORTEX tree."""
        try:
            step_name = step_result.get("step", "Unknown Step")
            step_output = step_result.get("output", step_result.get("result", ""))
            step_type = step_result.get("type", "ACTION")
            step_id = step_result.get("step_id", "")

            if isinstance(step_output, dict):
                step_output = json.dumps(step_output, default=str)[:50000]
            else:
                step_output = str(step_output)[:50000]

            summary = f"[{step_type}] {step_name}: {step_output[:500]}"
            content = f"Step: {step_name}\nType: {step_type}\n\n--- Output ---\n{step_output}"

            await cortex.write(
                parent_id=working_root_id,
                node_type="finding",
                title=step_name,
                summary=summary,
                content=content,
                status="complete",
                metadata_extra={
                    "step_id": step_id,
                    "step_type": step_type,
                    "run_id": str(run_id),
                },
            )
        except Exception as e:
            logger.warning(
                f"Failed to write step '{step_result.get('step')}' to CORTEX tree: {e}"
            )

    # ------------------------------------------------------------------
    # Tool Result Ingestion
    # ------------------------------------------------------------------

    async def ingest_tool_result(
        self,
        run: Any,
        tool_id: str,
        tool_output: str,
        context: dict[str, Any],
    ) -> None:
        """
        Ingest scraper/browser tool output into the CORTEX Knowledge subtree.

        Parses the tool result to extract URL and content, then writes a
        'knowledge' node under the Knowledge Base root. Bridges the gap
        between flat artifact storage and structured CORTEX trees.
        """
        try:
            cortex_tree_id = context.get("__cortex_tree_id__")
            if not cortex_tree_id:
                return  # Not a CORTEX execution

            # Parse the tool output
            try:
                parsed = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
            except (json.JSONDecodeError, TypeError):
                return

            # Handle both single and multi-URL results
            results = []
            if isinstance(parsed, dict):
                if parsed.get("results"):
                    results = parsed["results"]
                elif parsed.get("url"):
                    results = [parsed]

            if not results:
                return

            cortex = CortexService(db=self.db, company_id=run.company_id)
            tree = await cortex._get_tree(UUID(cortex_tree_id))

            # Find the Knowledge Base root
            from sqlalchemy import select as _sel
            from src.ai.memory.cortex_models import CortexNode, CortexNodeType as _CNT
            kb_result = await self.db.execute(
                _sel(CortexNode).where(
                    CortexNode.parent_id == tree.root_node_id,
                    CortexNode.node_type == _CNT.KNOWLEDGE,
                ).limit(1)
            )
            knowledge_root = kb_result.scalar_one_or_none()
            if not knowledge_root:
                return

            for item in results[:10]:  # Cap at 10 per call
                url = item.get("url", "unknown source")
                content = item.get("content", "")
                if not content or len(content) < 50:
                    continue

                # Generate LLM navigation-quality summary
                title = url.split("://")[-1][:80] if url else "Scraped Content"
                summary = await self._generate_summary(
                    run, url, content, title
                )

                await cortex.write(
                    parent_id=knowledge_root.id,
                    node_type="knowledge",
                    title=f"📄 {title}",
                    content=content[:50000],
                    summary=summary,
                    status="complete",
                    source_ref={"url": url, "tool": tool_id},
                    metadata_extra={
                        "run_id": str(run.id),
                        "char_count": len(content),
                        "artifact_id": item.get("artifact_id"),
                        # Provenance tracking
                        "tool_success": True,
                        "verified": False,  # Set to True after fact-checking
                        "provenance_chain": f"{tool_id}→cortex_bridge",
                    },
                )

            await self.db.commit()
            logger.info(
                f"CORTEX: Ingested {len(results)} knowledge node(s) from {tool_id} "
                f"into tree {cortex_tree_id}"
            )
        except Exception as e:
            logger.warning(f"CORTEX knowledge ingestion failed for {tool_id}: {e}")

    async def _generate_summary(
        self, run: Any, url: str, content: str, title: str
    ) -> str:
        """Generate an LLM summary for a knowledge node, with cost tracking."""
        try:
            from src.ai.llm.router import LLMRouter as _LLMRouter
            _llm = _LLMRouter(db=self.db, company_id=run.company_id)
            _resp = await _llm.call_llm(
                task_type="text_generation",
                system_prompt=(
                    "Generate a concise ~200 token summary that helps an AI research agent "
                    "decide if this source contains relevant data. Focus on: key topics, "
                    "claims, statistics, entities, and relevance to the research task."
                ),
                user_prompt=f"Source: {url}\n\nContent:\n{content[:4000]}",
                temperature=0.3,
                max_tokens=300,
            )
            summary = _resp.output[:500]

            # Track CORTEX summarization LLM costs
            if _resp.prompt_tokens or _resp.completion_tokens:
                try:
                    _model = _resp.model_name or "unknown"
                    _in_sku = f"{_model}-in"
                    _out_sku = f"{_model}-out"
                    _in_usage = await self.usage_service.log_usage(
                        company_id=run.company_id,
                        service_sku=_in_sku,
                        raw_quantity=float(_resp.prompt_tokens),
                        execution_id=run.id,
                    )
                    _out_usage = await self.usage_service.log_usage(
                        company_id=run.company_id,
                        service_sku=_out_sku,
                        raw_quantity=float(_resp.completion_tokens),
                        execution_id=run.id,
                    )
                    if run.total_cost_usd is None:
                        run.total_cost_usd = Decimal("0")
                    if _in_usage:
                        run.total_cost_usd += _in_usage.calculated_cost
                    if _out_usage:
                        run.total_cost_usd += _out_usage.calculated_cost
                    if run.total_tokens is None:
                        run.total_tokens = 0
                    run.total_tokens += (_resp.prompt_tokens + _resp.completion_tokens)
                    logger.info(
                        f"CORTEX summary cost tracked: "
                        f"in={_resp.prompt_tokens}, out={_resp.completion_tokens} "
                        f"(${(_in_usage.calculated_cost if _in_usage else 0) + (_out_usage.calculated_cost if _out_usage else 0)})"
                    )
                except Exception as _cost_err:
                    logger.debug(f"CORTEX summary cost tracking failed: {_cost_err}")

            return summary

        except Exception as _sum_err:
            logger.debug(f"LLM summary failed for {url}, using truncation: {_sum_err}")
            summary = content[:300].replace("\n", " ").strip()
            if len(content) > 300:
                summary += "..."
            return summary

    # ------------------------------------------------------------------
    # CORTEX-Native Step Execution
    # ------------------------------------------------------------------

    async def execute_cortex_step(
        self,
        run: Any,
        entity: Any,
        step: PlanStep,
        cortex: CortexService,
        tree: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Handle CORTEX-native step types: NAVIGATE, READ, WRITE, RECURSE, AWAIT_CHILDREN.
        These are the 5 primitives from the CORTEX spec mapped to step types.
        """
        try:
            target = step.target or PlanStepTarget()

            if step.type == StepType.NAVIGATE:
                node_id = self.resolve_node_id(target, context)
                viewport = await cortex.navigate(UUID(node_id))
                output = viewport.to_prompt_text()
                context[step.name] = output
                context["__cortex_viewport__"] = output
                return {
                    "step": step.name, "step_id": step.step_id,
                    "type": "NAVIGATE", "output": output[:2000],
                }

            elif step.type == StepType.READ:
                node_id = self.resolve_node_id(target, context)
                page = int(getattr(target, "page", 0) or 0)
                content = await cortex.read(UUID(node_id), page=page)
                output = content.content
                context[step.name] = output
                return {
                    "step": step.name, "step_id": step.step_id,
                    "type": "READ", "output": output[:5000],
                }

            elif step.type == StepType.WRITE:
                parent_id = self.resolve_node_id(target, context)
                node_type = getattr(target, "node_type", "finding") or "finding"
                title = step.name or "Agent Write"
                content_val = context.get(step.name, step.description or "")
                summary = str(content_val)[:300]
                new_id = await cortex.write(
                    parent_id=UUID(parent_id),
                    node_type=node_type,
                    title=title,
                    content=str(content_val)[:20000],
                    summary=summary,
                    status="complete",
                )
                output = str(new_id)
                context[step.name] = output
                return {
                    "step": step.name, "step_id": step.step_id,
                    "type": "WRITE", "output": output,
                }

            elif step.type == StepType.RECURSE:
                node_id = self.resolve_node_id(target, context)
                task_desc = step.description or step.name
                result_slot = getattr(target, "result_slot", step.name) or step.name
                task_node_id, child_run_id = await cortex.recurse(
                    node_id=UUID(node_id),
                    task=task_desc,
                    result_slot=result_slot,
                    execution_run_id=run.id,
                )
                # Enqueue the child run to Arq
                if child_run_id:
                    try:
                        from arq.connections import ArqRedis
                        arq_redis = ArqRedis(self.redis.client if hasattr(self, 'redis') else None)
                        await arq_redis.enqueue_job("run_execution_recursive", str(child_run_id))
                        logger.info(f"Enqueued child run {child_run_id} for RECURSE")
                    except Exception as enqueue_err:
                        logger.warning(
                            f"Failed to enqueue child run {child_run_id}: {enqueue_err}"
                        )

                output = json.dumps({
                    "task_node_id": str(task_node_id),
                    "child_run_id": str(child_run_id) if child_run_id else None,
                })
                context[step.name] = output
                return {
                    "step": step.name, "step_id": step.step_id,
                    "type": "RECURSE", "output": output,
                }

            elif step.type == StepType.AWAIT_CHILDREN:
                cursor_id = tree.resume_cursor_id or tree.root_node_id
                results = await cortex.await_children(cursor_id)
                output = json.dumps(
                    {k: v.to_dict() for k, v in results.items()}, default=str
                )
                context[step.name] = output
                return {
                    "step": step.name, "step_id": step.step_id,
                    "type": "AWAIT_CHILDREN", "output": output,
                }

            else:
                return {"step": step.name, "error": f"Unknown CORTEX step type: {step.type}"}

        except Exception as e:
            logger.error(f"CORTEX step '{step.name}' ({step.type}) failed: {e}")
            return {
                "step": step.name, "step_id": step.step_id,
                "type": str(step.type), "error": str(e),
            }

    # ------------------------------------------------------------------
    # Node Resolution
    # ------------------------------------------------------------------

    def resolve_node_id(self, target: Any, context: dict[str, Any]) -> str:
        """Resolve a node_id from step target or context."""
        node_id = getattr(target, "node_id", None)
        if node_id:
            return str(node_id)
        if hasattr(target, "prompt_template") and target.prompt_template:
            resolved = _parse_variables(target.prompt_template, context)
            return resolved.strip()
        return str(context.get("__cortex_cursor__", ""))

    # ------------------------------------------------------------------
    # Viewport & Checkpoint
    # ------------------------------------------------------------------

    async def refresh_viewport(
        self, cortex: CortexService, tree: Any, context_state: dict[str, Any]
    ) -> None:
        """Refresh the CORTEX viewport after a step and inject into context.

        Phase 4 (PERF): Caches viewport in Redis with a 30s TTL to avoid
        redundant tree traversals when cursor hasn't moved.
        """
        try:
            cursor_id = tree.resume_cursor_id or tree.root_node_id

            # Try Redis cache first
            if self.redis:
                cache_key = f"cortex:viewport:{tree.id}:{cursor_id}"
                cached = await self.redis.get(cache_key)
                if cached:
                    context_state["__cortex_viewport__"] = cached.decode() if isinstance(cached, bytes) else cached
                    return

            viewport = await cortex.navigate(cursor_id)
            viewport_text = viewport.to_prompt_text()
            context_state["__cortex_viewport__"] = viewport_text

            # Write to Redis cache
            if self.redis:
                try:
                    await self.redis.set(cache_key, viewport_text, ex=self.VIEWPORT_CACHE_TTL)
                except Exception:
                    pass  # Non-fatal: cache miss is fine
        except Exception:
            pass

    async def write_checkpoint(
        self, cortex: CortexService, tree: Any, context_state: dict[str, Any], step_name: str
    ) -> None:
        """Auto-checkpoint: compact the tree if context is getting large."""
        ctx_size = self._context_size_bytes // 4  # Estimated tokens (O(1))
        await cortex.check_and_compact(tree.id, ctx_size)
        logger.debug(f"CORTEX checkpoint after step {step_name}")

    # ------------------------------------------------------------------
    # Batch Write Buffer (Phase 4 — ARCH-3)
    # ------------------------------------------------------------------

    def buffer_node(
        self,
        parent_id: UUID,
        node_type: str,
        title: str,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        status: str = "complete",
        **kwargs: Any,
    ) -> None:
        """Buffer a node write. Call flush_buffer() at the step boundary."""
        self._write_buffer.append({
            "parent_id": parent_id,
            "node_type": node_type,
            "title": title,
            "content": content,
            "summary": summary,
            "status": status,
            **kwargs,
        })

    async def flush_buffer(self, cortex: CortexService) -> int:
        """Batch-insert all buffered nodes. Returns count of flushed nodes."""
        if not self._write_buffer:
            return 0
        count = 0
        for node_data in self._write_buffer:
            try:
                await cortex.write(**node_data)
                count += 1
            except Exception as e:
                logger.warning(f"Buffered node write failed: {e}")
        self._write_buffer.clear()
        await self.db.flush()
        return count

    # ------------------------------------------------------------------
    # Self-Reflection (Phase 5 — Autonomous Loop)
    # ------------------------------------------------------------------

    async def get_relevant_knowledge(
        self, tree_id: UUID, current_task: str
    ) -> str:
        """Query CORTEX knowledge root for relevant prior findings.

        Phase 5: Called before THOUGHT steps when self_reflection_enabled
        to give the agent awareness of what it has already learned.
        Returns a newline-delimited summary of knowledge nodes.
        """
        try:
            knowledge_root = await self.cortex.get_knowledge_root(tree_id)
            if not knowledge_root:
                return ""

            from sqlalchemy import select as _sel
            from src.ai.memory.cortex_models import CortexNode, CortexNodeStatus

            result = await self.db.execute(
                _sel(CortexNode).where(
                    CortexNode.parent_id == knowledge_root.id,
                    CortexNode.status == CortexNodeStatus.COMPLETE,
                ).order_by(CortexNode.created_at.desc()).limit(10)
            )
            children = result.scalars().all()
            if not children:
                return ""

            lines = [
                f"- {c.title}: {c.summary or '(no summary)'}"
                for c in children
            ]
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Knowledge retrieval failed for tree {tree_id}: {e}")
            return ""

    async def write_reflection(
        self,
        tree_id: UUID,
        cursor_id: UUID,
        step_name: str,
        learning: str,
    ) -> None:
        """Write a reflection node after step execution.

        Phase 5: Records what the agent learned from a step's execution
        as a finding node in the CORTEX tree, enabling future steps to
        reference prior learnings via get_relevant_knowledge().
        """
        try:
            await self.cortex.write(
                parent_id=cursor_id,
                node_type="finding",
                title=f"🔍 Reflection: {step_name}",
                content=learning,
                summary=learning[:200],
                status="complete",
                metadata_extra={"reflection": True, "tree_id": str(tree_id)},
            )
        except Exception as e:
            logger.debug(f"Reflection write failed for step {step_name}: {e}")

    # ------------------------------------------------------------------
    # Knowledge Tree Reference Resolution (Phase B)
    # ------------------------------------------------------------------

    async def get_knowledge_tree_references(
        self,
        entity_id: UUID,
        query: str,
        top_k: int = 3,
    ) -> str:
        """
        Search the entity's persistent Knowledge Tree for relevant references.

        Returns a formatted prompt string with knowledge snippets. If no
        Knowledge Tree exists or no results are found, returns empty string.
        """
        try:
            from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
            kt_service = KnowledgeTreeService(self.db, self.company_id)
            refs = await kt_service.get_knowledge_references(
                entity_id=entity_id, query=query, top_k=top_k,
            )
            if not refs:
                return ""

            lines = ["## Relevant Knowledge (from Knowledge Base)"]
            for i, ref in enumerate(refs, 1):
                lines.append(
                    f"  [{i}] {ref['title']} (score: {ref['score']:.2f})\n"
                    f"      {ref['snippet']}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Knowledge Tree reference lookup failed: {e}")
            return ""

    async def write_knowledge_reference(
        self,
        cortex: CortexService,
        knowledge_root_id: UUID,
        knowledge_node_id: str,
        title: str,
        snippet: str,
    ) -> None:
        """
        Write a lightweight reference node into a runtime tree's knowledge
        section that points to a node in the persistent Knowledge Tree.

        Uses cross_refs to maintain the association without duplicating content.
        """
        try:
            await cortex.write(
                parent_id=knowledge_root_id,
                node_type="knowledge",
                title=f"📎 Ref: {title[:100]}",
                content=snippet,
                summary=f"Reference to knowledge node {knowledge_node_id[:8]}... — {title[:200]}",
                status="complete",
                metadata_extra={
                    "is_reference": True,
                    "knowledge_node_id": knowledge_node_id,
                },
            )
        except Exception as e:
            logger.debug(f"Knowledge reference write failed: {e}")

    # ------------------------------------------------------------------
    # Runtime Access Tracking (Phase E)
    # ------------------------------------------------------------------

    async def track_node_access(
        self,
        node_ids: List[UUID],
        run_id: UUID,
    ) -> None:
        """
        Track which nodes were accessed together in this execution step.
        Creates/strengthens 'co_accessed' edges in the semantic graph.
        """
        if len(node_ids) < 2:
            return
        try:
            from src.ai.memory.graph_service import SemanticGraphService
            graph = SemanticGraphService(self.db, self.company_id)
            await graph.track_co_access(node_ids, run_id)
        except Exception as e:
            logger.debug(f"Co-access tracking failed: {e}")
