"""
platform_schema_compiler.py — Compiles the platform capability surface into
a structured JSON schema that serves as the Meta-Agent's "firmware".

Two modes of operation:
  1. compile()       — Build-time / deploy-time full compilation
  2. refresh()       — Runtime incremental refresh (tenant-scoped tools, models)

The compiled schema is injected into the Meta-Agent's system prompt context
via the platform_introspect meta-tool.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class PlatformSchemaCompiler:
    """Compiles the HireBuddha platform surface into a queryable schema."""

    def __init__(self, db: Optional[AsyncSession] = None, company_id: Optional[UUID] = None) -> None:
        self.db = db
        self.company_id = company_id
        self._cached_schema: Optional[Dict[str, Any]] = None
        self._cached_hash: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compile(self, include_tenant_tools: bool = True) -> Dict[str, Any]:
        """Full compilation of platform schema.

        Returns a dict containing:
          - entity_types: available entity types and their semantics
          - step_types: available execution step types
          - reasoning_modes: available LLM reasoning strategies
          - execution_modes: STANDARD vs AUTONOMOUS
          - tools: all available tools with function schemas
          - model_endpoints: configured LLM providers/models (tenant-scoped)
          - constraints: execution limits and governance parameters
          - composition_rules: how entities compose into hierarchies
          - schema_version: hash for drift detection
        """
        schema: Dict[str, Any] = {
            "compiled_at": datetime.now(timezone.utc).isoformat(),
            "entity_types": self._compile_entity_types(),
            "step_types": self._compile_step_types(),
            "reasoning_modes": self._compile_reasoning_modes(),
            "execution_modes": self._compile_execution_modes(),
            "tools": self._compile_tools(include_tenant=include_tenant_tools),
            "model_endpoints": await self._compile_model_endpoints(),
            "constraints": self._compile_constraints(),
            "composition_rules": self._compile_composition_rules(),
            "memory_modes": self._compile_memory_modes(),
            "hitl_triggers": self._compile_hitl_triggers(),
            "io_contract_spec": self._compile_io_contract_spec(),
            "behavioral_annotations": self._compile_behavioral_annotations(),
        }

        # Compute schema hash for drift detection
        schema_str = json.dumps(schema, sort_keys=True, default=str)
        schema["schema_version"] = hashlib.sha256(schema_str.encode()).hexdigest()[:16]

        self._cached_schema = schema
        self._cached_hash = schema["schema_version"]

        logger.info(
            f"Platform schema compiled: {len(schema['tools'])} tools, "
            f"version={schema['schema_version']}"
        )
        return schema

    async def refresh(self) -> Dict[str, Any]:
        """Runtime refresh — recompiles tenant-scoped sections only.

        Cheaper than full compile(): skips static enum extraction and
        only refreshes tools (tenant additions) and model endpoints
        (integration changes).
        """
        if not self._cached_schema:
            return await self.compile()

        # Refresh mutable sections
        self._cached_schema["tools"] = self._compile_tools(include_tenant=True)
        self._cached_schema["model_endpoints"] = await self._compile_model_endpoints()
        self._cached_schema["compiled_at"] = datetime.now(timezone.utc).isoformat()

        # Recompute hash
        schema_str = json.dumps(self._cached_schema, sort_keys=True, default=str)
        new_hash = hashlib.sha256(schema_str.encode()).hexdigest()[:16]

        if new_hash != self._cached_hash:
            logger.info(f"Platform schema drift detected: {self._cached_hash} → {new_hash}")
            self._cached_hash = new_hash
            self._cached_schema["schema_version"] = new_hash

        return self._cached_schema

    def get_cached(self) -> Optional[Dict[str, Any]]:
        """Return cached schema without recompilation."""
        return self._cached_schema

    async def compile_summary(self) -> str:
        """Compile a compact platform summary (~2-4K tokens) for prompt injection.

        This is the Tier 1 meta-cognition payload. It gives any agent enough
        knowledge to make intelligent dynamic planning and tool selection
        decisions without the full schema overhead.

        Sections:
          1. Available tools (name + 1-line description + category)
          2. Step type definitions (when to use each)
          3. Entity type hierarchy (composition rules)
          4. Execution modes and reasoning strategies
          5. Key behavioral rules (top 8 most critical)
          6. Memory modes
        """
        # Use cached full schema or compile fresh
        schema = self._cached_schema
        if not schema:
            schema = await self.compile(include_tenant_tools=True)

        lines = [
            "# HireBuddha Platform — Capability Manifest",
            "",
        ]

        # 1. Tools
        tools = schema.get("tools", [])
        if tools:
            lines.append("## Available Tools")
            for t in tools:
                cat = t.get("category", "utility")
                desc = (t.get("description") or "No description")[:140]
                lines.append(f"- **{t['tool_id']}** [{cat}]: {desc}")
            lines.append("")

        # 2. Step Types
        lines.append("## Step Types (use in planning)")
        for st in schema.get("step_types", []):
            lines.append(f"- **{st['type']}**: {st['description'][:160]}")
        lines.append("")

        # 3. Entity Type Hierarchy
        lines.append("## Entity Types (composition hierarchy)")
        for et in schema.get("entity_types", []):
            children = "Can have children" if et.get("can_have_children") else "Leaf node"
            lines.append(f"- **{et['type']}**: {et['description'][:120]} ({children})")
        lines.append("")

        # 4. Reasoning & Execution Modes
        lines.append("## Reasoning Modes")
        for rm in schema.get("reasoning_modes", []):
            lines.append(f"- **{rm['mode']}**: {rm['description']}")
        lines.append("")
        lines.append("## Execution Modes")
        for em in schema.get("execution_modes", []):
            lines.append(f"- **{em['mode']}**: {em['description'][:120]}")
        lines.append("")

        # 5. Key Behavioral Rules (top 8)
        annotations = schema.get("behavioral_annotations", [])
        if annotations:
            lines.append("## Critical Platform Rules")
            for ann in annotations[:8]:
                lines.append(f"- **{ann['rule']}**: {ann['description'][:180]}")
            lines.append("")

        # 6. Memory Modes
        for mm in schema.get("memory_modes", []):
            lines.append(f"- **{mm['mode']}** memory: {mm['description'][:140]}")
        lines.append("")

        # 7. Composition Rules
        comp = schema.get("composition_rules", [])
        if comp:
            lines.append("## Composition Rules")
            for rule in comp[:5]:
                lines.append(f"- {rule[:180]}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Entity Types
    # ------------------------------------------------------------------

    def _compile_entity_types(self) -> List[Dict[str, Any]]:
        """Extract entity types from schemas.py enums with semantic descriptions."""
        return [
            {
                "type": "ACTION",
                "description": "Atomic unit of work. Single LLM reasoning step or tool call. "
                               "Cannot have children. Always has exactly one step in its plan.",
                "can_have_children": False,
                "typical_step_count": "1",
            },
            {
                "type": "SKILL",
                "description": "Reusable multi-step capability. Can chain multiple "
                               "TOOL_CALL and ACTION steps. No child entities.",
                "can_have_children": False,
                "typical_step_count": "2-5",
            },
            {
                "type": "AGENT",
                "description": "Autonomous reasoning entity with tools, memory, and "
                               "optional CORTEX cognitive tree. Supports AUTONOMOUS execution "
                               "mode with self-reflection and goal validation.",
                "can_have_children": False,
                "typical_step_count": "3-10",
            },
            {
                "type": "PROCESS",
                "description": "Orchestration entity that coordinates child entities "
                               "(AGENTs, SKILLs) via CHILD_ENTITY_INVOCATION steps. "
                               "Supports DAG execution with parallel branches.",
                "can_have_children": True,
                "typical_step_count": "2-20",
            },
        ]

    # ------------------------------------------------------------------
    # Step Types
    # ------------------------------------------------------------------

    def _compile_step_types(self) -> List[Dict[str, str]]:
        return [
            {
                "type": "THOUGHT",
                "description": "Pure LLM reasoning step. No tool call. Uses prompt_template "
                               "to structure the reasoning task. Output stored in context.",
            },
            {
                "type": "ACTION",
                "description": "LLM-driven action step. The LLM receives context from prior "
                               "steps and generates output. Core workhorse for data transformation.",
            },
            {
                "type": "TOOL_CALL",
                "description": "Direct tool invocation. Requires target.tool_id. The LLM "
                               "generates tool arguments, then the tool is executed. Uses "
                               "REACT loop for multi-turn tool interactions.",
            },
            {
                "type": "CHILD_ENTITY_INVOCATION",
                "description": "Delegates execution to a child HierarchicalEntity. Requires "
                               "target.entity_id pointing to an existing entity within the "
                               "same company. Creates a child ExecutionRun.",
            },
            {
                "type": "NAVIGATE",
                "description": "CORTEX-native. Moves the cursor to a specific node in the "
                               "cognitive tree. Updates __cortex_viewport__.",
            },
            {
                "type": "READ",
                "description": "CORTEX-native. Reads paginated content from a tree node.",
            },
            {
                "type": "WRITE",
                "description": "CORTEX-native. Creates a new finding/output node in the tree.",
            },
            {
                "type": "RECURSE",
                "description": "CORTEX-native. Spawns a sub-task as a child execution run "
                               "rooted at a tree node.",
            },
            {
                "type": "AWAIT_CHILDREN",
                "description": "CORTEX-native. Waits for all child RECURSE executions to "
                               "complete and collects their results.",
            },
        ]

    # ------------------------------------------------------------------
    # Reasoning & Execution Modes
    # ------------------------------------------------------------------

    def _compile_reasoning_modes(self) -> List[Dict[str, str]]:
        # D-3: only REACT and CHAIN_OF_THOUGHT remain selectable per-step.
        # REFLECTION is handled by the AgentLoop Reflector; multi-branch
        # exploration is the Strategist-selected DebateExecutor — neither is
        # an author-facing per-entity reasoning mode any longer.
        return [
            {"mode": "REACT", "description": "Reason-Act cycle. LLM reasons, calls tools, observes, repeats."},
            {"mode": "CHAIN_OF_THOUGHT", "description": "Step-by-step reasoning before acting."},
        ]

    def _compile_execution_modes(self) -> List[Dict[str, Any]]:
        return [
            {
                "mode": "STANDARD",
                "description": "Static plan-execute. Steps run in order. No self-reflection.",
            },
            {
                "mode": "AUTONOMOUS",
                "description": "Goal-centric with self-reflection. Agent validates progress "
                               "every N steps, can re-plan on failure, and early-exits when "
                               "goal is achieved. Requires: goal field set on entity.",
                "config_keys": [
                    "goal_validation_interval",
                    "confidence_threshold",
                    "max_replanning_attempts",
                    "self_reflection_enabled",
                ],
            },
        ]

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def _compile_tools(self, include_tenant: bool = True) -> List[Dict[str, Any]]:
        """Extract all registered tools with their function schemas."""
        from src.ai.tools.base import ToolRegistry

        if include_tenant and self.company_id:
            tools = ToolRegistry.get_tools_for_company(self.company_id)
        else:
            tools = ToolRegistry._tools

        compiled = []
        for name, tool in tools.items():
            # Skip meta-tools from the compilation (avoid self-reference)
            if name.startswith("meta_"):
                continue

            schema = tool.get_function_schema()
            compiled.append({
                "tool_id": name,
                "description": tool.description,
                "function_schema": schema,
                "supports_context": tool.supports_context(),
                "category": self._categorize_tool(name),
            })
        return compiled

    def _categorize_tool(self, tool_name: str) -> str:
        """Heuristic tool categorization for the Meta-Agent's understanding."""
        categories = {
            "search": ["web_search", "scraper_tool"],
            "document": ["pdf_generator", "file_writer", "docx_tool", "pptx_tool", "excel"],
            "communication": ["email_ingest", "email_classify", "email_draft", "email_send",
                              "whatsapp_send_tenant"],
            "media": ["image_generation", "video_generate", "video_edit", "video_add_sound"],
            "code": ["sandbox_code", "terminal_tool"],
            "browser": ["headless_browser"],
            "social": ["linkedin", "twitter", "facebook", "instagram", "youtube",
                       "tiktok", "reddit", "quora", "pinterest"],
            "ads": ["google_ads", "meta_ads", "linkedin_ads", "youtube_ads",
                    "x_ads", "snapchat_ads"],
            "crm": ["crm_update_lead", "google_calendar", "get_current_datetime"],
            "utility": ["calculator"],
        }
        name_lower = tool_name.lower()
        for category, keywords in categories.items():
            if any(kw in name_lower for kw in keywords):
                return category
        return "utility"

    # ------------------------------------------------------------------
    # Model Endpoints (tenant-scoped)
    # ------------------------------------------------------------------

    async def _compile_model_endpoints(self) -> List[Dict[str, Any]]:
        """Query IntegrationRegistry for available LLM endpoints."""
        if not self.db or not self.company_id:
            return []

        try:
            from src.config.models import IntegrationRegistry

            # IntegrationRegistry has no is_enabled/category/is_default columns.
            # Enabled rows are status=='active'; LLM endpoints are the LLM /
            # LLM_LIVE service categories. Provider/model come from
            # provider_name/model_name.
            result = await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == self.company_id,
                    IntegrationRegistry.status == "active",
                    IntegrationRegistry.service_category.in_(["LLM", "LLM_LIVE"]),
                )
            )
            integrations = result.scalars().all()

            endpoints = []
            for integ in integrations:
                endpoints.append({
                    "provider": integ.provider_name,
                    "model_name": integ.model_name,
                    "category": integ.service_category,
                    "service_sku": integ.service_sku,
                })
            return endpoints
        except Exception as e:
            logger.debug(f"Model endpoint compilation failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Constraints & Rules
    # ------------------------------------------------------------------

    def _compile_constraints(self) -> Dict[str, Any]:
        from src.ai.constants import (
            MAX_REACT_TURNS,
            MAX_CONTENT_CHARS,
            MAX_CONTEXT_TRUNCATION_CHARS,
            CONTEXT_SUMMARIZE_THRESHOLD,
        )
        return {
            "max_react_turns": MAX_REACT_TURNS,
            "max_content_chars": MAX_CONTENT_CHARS,
            "context_summarize_threshold": CONTEXT_SUMMARIZE_THRESHOLD,
            "max_context_truncation_chars": MAX_CONTEXT_TRUNCATION_CHARS,
            "max_recursion_depth_default": 5,
            "max_tool_rate_default": None,
            "cortex_max_children_per_node": 12,
            "cortex_page_size_tokens": 8000,
        }

    def _compile_composition_rules(self) -> List[str]:
        return [
            "PROCESS entities contain child AGENTs/SKILLs via hierarchy.children[].child_id",
            "CHILD_ENTITY_INVOCATION steps MUST have target.entity_id pointing to a valid "
            "HierarchicalEntity within the same company_id scope",
            "Children share the parent's CORTEX tree via __cortex_tree_id__ context propagation",
            "DAG execution: steps with input_dependencies run in parallel when independent",
            "Step outputs are referenced via {{step_id}} template variables in prompt_template",
            "Context flows from parent to child via input_data; child result flows back "
            "via context_state[step_name]",
            "Max composition depth enforced by governance.max_recursion_depth (default 5)",
        ]

    def _compile_memory_modes(self) -> List[Dict[str, str]]:
        return [
            {
                "mode": "STANDARD",
                "description": "Episodic (last N interactions) + Semantic (pgvector document search). "
                               "Suitable for short-lived, stateless agent executions.",
            },
            {
                "mode": "CORTEX",
                "description": "Cognitive tree for unbounded context. Enables long-running tasks "
                               "with persistent state, knowledge ingestion, and sub-task delegation. "
                               "Required for AUTONOMOUS execution mode with self-reflection.",
            },
        ]

    def _compile_hitl_triggers(self) -> List[Dict[str, str]]:
        return [
            {"trigger": "BEFORE_STEP", "description": "Pause before a named step executes"},
            {"trigger": "AFTER_STEP", "description": "Pause after a named step completes"},
            {"trigger": "COST_THRESHOLD", "description": "Pause when accumulated cost exceeds USD threshold"},
            {"trigger": "TOOL_CALL", "description": "Pause before a specific tool is called"},
            {"trigger": "CUSTOM", "description": "Custom expression: step_count > N, cost > N, has_key('X')"},
        ]

    def _compile_io_contract_spec(self) -> Dict[str, Any]:
        return {
            "description": "Every entity can define input_schema and output_schema as JSON Schema objects. "
                           "The execution engine validates input_data against input_schema before execution.",
            "input_schema_default": {"type": "object", "properties": {}},
            "output_schema_default": {"type": "object", "properties": {}},
            "variable_resolution": {
                "pattern": "{{variable_name}}",
                "sources": [
                    "input_data fields",
                    "prior step outputs (by step_id or step name)",
                    "context_state keys",
                    "__cortex_viewport__ (CORTEX mode)",
                    "__memory_context__ (episodic/semantic memory)",
                ],
            },
        }

    # ------------------------------------------------------------------
    # Behavioral Annotations (V2 — execution semantics)
    # ------------------------------------------------------------------

    def _compile_behavioral_annotations(self) -> List[Dict[str, Any]]:
        """Encode critical execution semantics that cannot be extracted from enums.

        These rules describe non-obvious runtime behaviors of the execution
        engine, context propagation, and CORTEX system.  They are injected
        into the Meta-Agent's context alongside the structural schema so it
        can generate agents that respect platform invariants.
        """
        return [
            {
                "rule": "CORTEX_TREE_PROPAGATION",
                "description": (
                    "When a PROCESS invokes a child via CHILD_ENTITY_INVOCATION, "
                    "the __cortex_tree_id__ from parent context is automatically "
                    "propagated to the child's input_data. All entities in a "
                    "hierarchy share one CORTEX tree."
                ),
                "affects": ["CHILD_ENTITY_INVOCATION", "CORTEX"],
            },
            {
                "rule": "CHILD_CONTEXT_STRIPPING",
                "description": (
                    "Before a child entity receives context from its parent, "
                    "all generic step_id keys (step_1, step_2, ...) are stripped "
                    "to prevent step-skip collision. Named step outputs and "
                    "internal keys are preserved."
                ),
                "affects": ["CHILD_ENTITY_INVOCATION", "context_state"],
            },
            {
                "rule": "PARENT_MEMORY_ISOLATION",
                "description": (
                    "Parent-scoped memory keys (__memory__, __episodic_memory__, "
                    "__semantic_context__) are stripped from child context to "
                    "prevent child entities from being confused by parent's "
                    "past execution history."
                ),
                "affects": ["CHILD_ENTITY_INVOCATION", "memory"],
            },
            {
                "rule": "AUTONOMOUS_REQUIRES_GOAL",
                "description": (
                    "execution_mode=AUTONOMOUS requires: entity.goal is set, "
                    "logic_gate.reasoning_config.self_reflection_enabled=true, "
                    "goal_validation_interval > 0. Without these, the engine "
                    "falls back to STANDARD mode silently."
                ),
                "affects": ["AUTONOMOUS", "goal_validation"],
            },
            {
                "rule": "SCRAPER_AUTO_INGEST",
                "description": (
                    "When scraper_tool or headless_browser executes during a "
                    "CORTEX-enabled run, the output is automatically written as "
                    "a knowledge node under the tree's Knowledge Root."
                ),
                "affects": ["scraper_tool", "headless_browser", "CORTEX"],
            },
            {
                "rule": "REACT_TOOL_INJECTION",
                "description": (
                    "Only tools with usage='AUTONOMOUS' or 'BOTH' are injected "
                    "into the LLM prompt for REACT reasoning. Tools with "
                    "usage='PLANNED' are executed deterministically by the "
                    "static plan executor and never shown to the LLM."
                ),
                "affects": ["REACT", "tools"],
            },
            {
                "rule": "VARIABLE_RESOLUTION_ORDER",
                "description": (
                    "{{variable}} in prompt_template resolves in order: "
                    "1) input_data fields, 2) prior step outputs (by step_id), "
                    "3) prior step outputs (by step name), 4) context_state keys. "
                    "Double-brace {{var}} takes priority over single-brace {var}."
                ),
                "affects": ["prompt_template", "context_state"],
            },
            {
                "rule": "TOOL_CALL_SELF_HEALING",
                "description": (
                    "When a TOOL_CALL step fails with a formatting error, the "
                    "engine automatically asks the LLM to reformat the input and "
                    "retries once. Infrastructure errors (auth, timeout) are not retried."
                ),
                "affects": ["TOOL_CALL"],
            },
            {
                "rule": "CHILD_RESULT_ACCUMULATION",
                "description": (
                    "When a CHILD_ENTITY_INVOCATION completes, ALL child step "
                    "outputs are accumulated and joined (not just the last step). "
                    "This ensures multi-step child agents pass their full work "
                    "to the parent."
                ),
                "affects": ["CHILD_ENTITY_INVOCATION"],
            },
            {
                "rule": "CREDIT_CIRCUIT_BREAKER",
                "description": (
                    "After each step, the engine checks the company's credit "
                    "balance. If exhausted, execution stops with PARTIAL_COMPLETE "
                    "status and partial results are saved. A child entity also "
                    "gets a credit gate check before being spawned."
                ),
                "affects": ["governance", "billing"],
            },
            {
                "rule": "DAG_PARALLEL_ISOLATION",
                "description": (
                    "When multiple steps run in parallel (DAG execution), each "
                    "step gets its own AsyncSession and a deep-copied context. "
                    "This prevents PendingRollbackError and cross-contamination."
                ),
                "affects": ["DAG", "parallel"],
            },
            {
                "rule": "PROCESS_REQUIRES_HIERARCHY",
                "description": (
                    "PROCESS entities must define hierarchy.children[] with "
                    "child_id entries and corresponding CHILD_ENTITY_INVOCATION "
                    "steps in the static plan. Each child_id must point to an "
                    "existing entity within the same company_id scope."
                ),
                "affects": ["PROCESS", "hierarchy"],
            },
            {
                "rule": "UNCERTAINTY_SIGNAL",
                "description": (
                    "During THOUGHT/ACTION steps, if the LLM includes "
                    '{"needs_clarification": true, "question": "..."} in its '
                    "response, the engine raises an UncertaintySignal instead "
                    "of treating it as normal output. This can trigger HITL."
                ),
                "affects": ["THOUGHT", "ACTION", "HITL"],
            },
            {
                "rule": "CONTEXT_SUMMARIZATION",
                "description": (
                    "When context exceeds the summarize_threshold (default 8000 "
                    "chars), older step outputs are summarized by the LLM to "
                    "fit within the context window. Domain-specific keys listed "
                    "in context_policy.preserve_keys are kept verbatim."
                ),
                "affects": ["context_policy", "SLIDING_WINDOW"],
            },
            {
                "rule": "META_TOOL_ISOLATION",
                "description": (
                    "All meta-tools (meta_platform_introspect, meta_registry_search, "
                    "meta_schema_validator, meta_entity_creator, meta_entity_executor) "
                    "use isolated AsyncSession instances to prevent DB transaction "
                    "poisoning during validation or execution steps."
                ),
                "affects": ["meta_tools", "database"],
            },
            {
                "rule": "HITL_TIMEOUT_BEHAVIOR",
                "description": (
                    "HITL checkpoints block execution until approved, rejected, "
                    "or timed out. If auto_approve_on_timeout=True, the checkpoint "
                    "auto-approves when timeout expires. Otherwise, the execution "
                    "fails with a timeout error."
                ),
                "affects": ["HITL", "governance"],
            },
        ]


# ---------------------------------------------------------------------------
# Convenience: module-level compile function
# ---------------------------------------------------------------------------

async def compile_platform_schema(
    db: Optional[AsyncSession] = None,
    company_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """One-shot schema compilation."""
    compiler = PlatformSchemaCompiler(db=db, company_id=company_id)
    return await compiler.compile()


# ---------------------------------------------------------------------------
# Tier 1: Platform Awareness — Summarized manifest for system prompt injection
# ---------------------------------------------------------------------------

_MANIFEST_CACHE_TTL = 300  # 5 minutes

async def get_platform_summary(
    db: AsyncSession,
    company_id: UUID,
    redis: Any = None,
) -> str:
    """Return a compact (~2-4K token) platform summary for prompt injection.

    Uses Redis cache with 5-minute TTL per tenant. Falls back to in-memory
    compilation if Redis is unavailable.

    This is the primary entry point for Tier 1 meta-cognition. Injected into:
      - build_sandwich_prompt() as Layer 3.5: Platform Awareness
      - the PlanGenerator (v2) planning system prompt
    """
    cache_key = f"meta:manifest:{company_id}"

    # Try Redis cache first
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached
        except Exception as e:
            logger.debug(f"Redis cache miss for manifest: {e}")

    # Compile fresh summary
    compiler = PlatformSchemaCompiler(db=db, company_id=company_id)
    summary = await compiler.compile_summary()

    # Cache in Redis
    if redis:
        try:
            await redis.set(cache_key, summary, ex=_MANIFEST_CACHE_TTL)
        except Exception as e:
            logger.debug(f"Redis cache write failed for manifest: {e}")

    return summary


async def load_entity_children(
    db: AsyncSession,
    entity_id: UUID,
    company_id: UUID,
) -> List[Any]:
    """Load the live child ORM rows referenced by an entity's hierarchy.

    Single source of truth for "what children does this entity have" — used
    both by :func:`describe_entity_children` (for the planner prompt) and by
    :class:`PlannerService` when it needs to synthesise CHILD_ENTITY_INVOCATION
    steps for a routing PROCESS/AGENT whose dynamic plan failed to delegate.
    Returns ``[]`` when the entity is missing or has no resolvable children.
    """
    from src.ai.models import HierarchicalEntity

    result = await db.execute(
        select(HierarchicalEntity).where(
            HierarchicalEntity.id == entity_id,
            HierarchicalEntity.company_id == company_id,
        )
    )
    entity = result.scalar_one_or_none()
    if not entity:
        return []

    hierarchy = entity.hierarchy or {}
    children_refs = hierarchy.get("children", [])
    child_ids = [c.get("child_id") for c in children_refs if c.get("child_id")]
    if not child_ids:
        return []

    children_result = await db.execute(
        select(HierarchicalEntity).where(
            HierarchicalEntity.company_id == company_id,
            HierarchicalEntity.id.in_(
                [UUID(cid) if isinstance(cid, str) else cid for cid in child_ids]
            ),
        )
    )
    return list(children_result.scalars().all())


async def describe_entity_children(
    db: AsyncSession,
    entity_id: UUID,
    company_id: UUID,
    children: Optional[List[Any]] = None,
) -> str:
    """Describe an entity's children for injection into the dynamic planner.

    Returns a markdown summary of all child entities referenced in the
    entity's hierarchy.children[]. Used by PlannerService to give the
    dynamic planner awareness of available child agents. Pass ``children``
    to reuse an already-loaded list (e.g. from :func:`load_entity_children`)
    and skip the extra DB round-trip.
    """
    if children is None:
        children = await load_entity_children(db, entity_id, company_id)
    if not children:
        return ""

    lines = ["## Available Child Entities (for CHILD_ENTITY_INVOCATION steps)"]
    lines.append(
        "IMPORTANT: When creating CHILD_ENTITY_INVOCATION steps, you MUST use the "
        "exact `entity_id` UUID shown below for each child entity. "
        "Do NOT use the entity name — only the UUID is valid.\n"
    )
    for child in children:
        identity = child.identity or {}
        role = identity.get("role") or identity.get("persona", {}).get("role", "")
        tools = child.capabilities.get("tools", []) if child.capabilities else []
        tool_names = [t.get("tool_id", "") for t in tools]
        goal = child.goal or child.description or "No description"

        lines.append(f"### {child.name} ({child.type})")
        lines.append(f"- **entity_id (USE THIS EXACT UUID):** `{child.id}`")
        if role:
            lines.append(f"- **Role:** {role}")
        lines.append(f"- **Goal:** {goal[:200]}")
        if tool_names:
            lines.append(f"- **Tools:** {', '.join(tool_names[:8])}")
        lines.append("")

    return "\n".join(lines)



def resolve_meta_cognition(entity: Any) -> Dict[str, Any]:
    """Resolve effective meta-cognition config for an entity.

    Phase 11 Track 5 default change:
      * ``platform_awareness`` — auto-enabled when dynamic_planning is
        enabled OR reasoning_mode=REACT (unchanged).
      * ``registry_search`` — **opt-in by default** (was: auto-ON for
        AGENT/PROCESS). Entities that need it must set it explicitly.
      * ``self_modification`` — **opt-in by default** (same).
      * Meta-Agent entities (identified via
        ``metadata_extensions.is_meta_agent``) opt in to both flags
        automatically — they are the only entities that build others.

    Existing live entities that were relying on the prior auto-on
    default are preserved via
    ``ai.meta.meta_cognition_migration.backfill_meta_cognition`` which
    must run BEFORE this code deploys.

    Returns a dict with resolved boolean flags and limits.
    """
    caps = entity.capabilities or {}
    explicit = caps.get("meta_cognition", {})

    # Start with defaults
    config = {
        "platform_awareness": explicit.get("platform_awareness", True),
        "registry_search": explicit.get("registry_search", False),
        "self_modification": explicit.get("self_modification", False),
        # Introspection meta-tools (`06` §3.1). Defaults are filled in by
        # entity type below (per the §1 matrix) unless explicitly set.
        "self_introspection": explicit.get("self_introspection", None),
        "reflection": explicit.get("reflection", None),
        "max_runtime_creations": explicit.get("max_runtime_creations", 3),
        "max_registry_searches": explicit.get("max_registry_searches", 5),
    }

    entity_type = getattr(entity, "type", None) or entity.get("type", "")
    if isinstance(entity_type, str):
        entity_type = entity_type.upper()

    # Tier 1: auto-enable for dynamic planning or REACT
    planning = entity.planning if hasattr(entity, "planning") else (entity.get("planning") or {})
    logic_gate = entity.logic_gate if hasattr(entity, "logic_gate") else (entity.get("logic_gate") or {})

    if isinstance(planning, dict):
        dyn = planning.get("dynamic_planning", {})
    else:
        dyn = {}
    if isinstance(logic_gate, dict):
        reasoning = logic_gate.get("reasoning_config", {})
    else:
        reasoning = {}

    dynamic_enabled = dyn.get("enabled", False)
    reasoning_mode = reasoning.get("reasoning_mode", "REACT")

    # Tier 1: only inject when LLM is making decisions
    if "platform_awareness" not in explicit:
        config["platform_awareness"] = dynamic_enabled or reasoning_mode == "REACT"

    # Tiers 2 & 3 — Phase 11 Track 5 opt-in defaults.
    # Entities that previously relied on the auto-on default were
    # backfilled with explicit `true` by the preserve-migration; this
    # branch is now intentionally a no-op for non-meta entities so new
    # entities default OFF and have to opt in.
    if "registry_search" not in explicit:
        config["registry_search"] = False
    if "self_modification" not in explicit:
        config["self_modification"] = False

    # The Meta-Agent template itself MUST keep both tiers ON — it is
    # the only entity whose job is to build other entities.
    metadata_extensions = (
        entity.metadata_extensions if hasattr(entity, "metadata_extensions")
        else (entity.get("metadata_extensions") or {})
    )
    is_meta_agent = (
        isinstance(metadata_extensions, dict)
        and bool(metadata_extensions.get("is_meta_agent"))
    )
    if is_meta_agent:
        config["registry_search"] = True
        config["self_modification"] = True

    # Introspection defaults per the §1 matrix (only when not explicitly set):
    #   self-introspection → SKILL (r/o) + AGENT + PROCESS
    #   reflection         → AGENT + PROCESS (SKILL is run-scoped only)
    if config["self_introspection"] is None:
        config["self_introspection"] = entity_type in ("SKILL", "AGENT", "PROCESS")
    if config["reflection"] is None:
        config["reflection"] = entity_type in ("AGENT", "PROCESS")

    return config

