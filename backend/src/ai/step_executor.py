"""
step_executor.py — Step execution logic extracted from ExecutionEngine.

Extracted during Phase 6 gap closure to reduce worker.py from ~2,826
to ~1,700 lines. Contains all step-level execution handlers:
THOUGHT/ACTION, TOOL_CALL, CHILD_ENTITY_INVOCATION, and supporting
methods (reasoning modes, review, usage logging, context summarization).
"""
import asyncio
import copy
import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
from uuid import UUID

from src.ai.constants import INTERNAL_CONTEXT_KEYS, MAX_REACT_TURNS
from src.ai.models import (
    ExecutionRun, HierarchicalEntity, LLMInteractionLog,
    ToolInteractionLog, RunStatus,
)
from src.ai.schemas import StepType, PlanStep
from src.ai.tool_executor import ToolExecutor
from src.ai.llm.router import LLMRouter
from src.ai.usage_service import UsageService
from src.billing.credit_service import InsufficientCreditsError
from sqlalchemy import select, update, func

logger = logging.getLogger(__name__)


# Direct imports from ai.core (no circular dependency).
from src.ai.core.prompt_utils import parse_variables, build_sandwich_prompt, filter_context_for_step
from src.ai.core.exceptions import UncertaintySignal
from src.ai.schemas import DEFAULT_REVIEW_SYSTEM_PROMPT as DEFAULT_REVIEW_PROMPT


class StepExecutorService:
    """Handles individual step execution: THOUGHT, TOOL_CALL, CHILD_ENTITY_INVOCATION.

    Extracted from ExecutionEngine to reduce monolith size. Receives
    dependencies via constructor; does NOT own the DB session or run lifecycle.
    """

    def __init__(self, db, redis, company_id: UUID, usage_service: UsageService, cortex_bridge=None, governance=None):
        self.db = db
        self.redis = redis
        self.company_id = company_id
        self.usage_service = usage_service
        self._cortex_bridge = cortex_bridge
        # GovernanceService dependency for credit gates.
        self._governance = governance

    # ------------------------------------------------------------------
    # CORTEX delegation
    # ------------------------------------------------------------------

    async def _ingest_tool_result_to_cortex(self, run, tool_id, tool_output, context):
        """Delegate to CortexBridge if available."""
        if self._cortex_bridge:
            await self._cortex_bridge.ingest_tool_result(run, tool_id, tool_output, context)

    async def _bump_run_cost(self, run: ExecutionRun, cost_delta=Decimal("0"), token_delta: int = 0) -> None:
        """Atomically fold cost/tokens into ``run.total_cost_usd`` on the DB row.

        Why not ``run.total_cost_usd += delta``? The parallel DAG path
        (``ExecutionEngine._execute_steps_dag``) runs each step in its OWN
        AsyncSession with its OWN reloaded copy of this run row. An in-place ORM
        mutation is flushed as an *absolute* full-row UPDATE
        (``SET total_cost_usd = <my local value>``), so when several isolated
        sessions commit concurrently the last writer wins and every other
        step's cost is silently dropped — the Phase 11 billing leak where a
        ~$6 run settled at ~$0.88.

        An atomic ``SET total_cost_usd = total_cost_usd + :delta`` is
        read-modify-write under a row lock, so concurrent increments sum
        correctly. We then ``refresh`` only these two columns so the in-memory
        object mirrors the new value WITHOUT being marked dirty (a dirty flush
        would re-introduce the clobbering absolute write).
        """
        cost_delta = Decimal(str(cost_delta or 0))
        token_delta = int(token_delta or 0)
        if cost_delta == 0 and token_delta == 0:
            return
        await self.db.execute(
            update(ExecutionRun)
            .where(ExecutionRun.id == run.id)
            .values(
                total_cost_usd=func.coalesce(ExecutionRun.total_cost_usd, 0) + cost_delta,
                total_tokens=func.coalesce(ExecutionRun.total_tokens, 0) + token_delta,
            )
        )
        # Commit immediately to release the run-row lock the UPDATE just took.
        # In the parallel DAG every isolated-session step bumps the SAME run
        # row; if the lock were held until the step's next (infrequent) commit,
        # the parallel steps would serialise and block on each other for the
        # whole step body (LLM + sandbox work) — observed as multi-minute
        # ``transactionid`` lock waits. A short acquire-update-commit cycle keeps
        # the atomic increment correct without the contention. Safe because the
        # session uses ``expire_on_commit=False`` (no attribute expiry → no
        # MissingGreenlet) and ``log_usage`` already commits per call.
        await self.db.commit()
        await self.db.refresh(run, attribute_names=["total_cost_usd", "total_tokens"])

    async def _execute_step(self, run: ExecutionRun, entity: HierarchicalEntity, step: PlanStep, context: dict) -> dict:
        """Routes execution to specific step handler."""
        if step.type == StepType.CHILD_ENTITY_INVOCATION:
            # Child entities run as their own isolated runs via the loop's
            # ChildEntityExecutor (create_child_run + async suspend/resume), not
            # inline on this session. Reaching here is a routing bug.
            from src.ai.core.exceptions import AgentError
            raise AgentError(
                "CHILD_ENTITY_INVOCATION reached the inline step path; child "
                "entities are dispatched asynchronously by ChildEntityExecutor."
            )
        elif step.type == StepType.TOOL_CALL:
            return await self._execute_tool_call(run, entity, step, context)
        elif step.type == StepType.THOUGHT or step.type == StepType.ACTION:
            return await self._execute_thought(run, entity, step, context)
        return {"error": "Unknown step type"}

    async def create_child_run(self, run: ExecutionRun, entity: HierarchicalEntity, step: PlanStep, context: dict) -> ExecutionRun:
        """Resolve + create (but do NOT execute) a child ExecutionRun row.

        Shared by the inline path (``_execute_child_invocation``) and the
        async-dispatch path (the loop's ``ChildEntityExecutor``, which enqueues
        the child as its own job and suspends the parent). Returns the committed
        PENDING child run.
        """
        # Resolve the child entity_id through the single source of truth:
        # ai.planning.child_resolver (UUID passthrough → static-plan name
        # match → hierarchy index → entity_name_hint DB lookup). A miss
        # surfaces as the AgentError the engine has always raised here.
        from src.ai.planning.child_resolver import (
            resolve_child_entity_id,
            EntityNotFoundError as ChildResolveError,
        )
        try:
            entity_id = await resolve_child_entity_id(step, entity, self.db)
        except ChildResolveError:
            from src.ai.core.exceptions import AgentError
            raise AgentError(f"Child invocation missing entity_id for step {step.name}")

        # ── Runtime safety net: validate child entity exists ──
        # The pre-flight check in trigger_execution() already validated
        # company-scoped access. Here we just confirm the entity exists
        # and hasn't been deleted since execution was enqueued.
        child_entity_check = await self.db.execute(
            select(HierarchicalEntity).where(
                HierarchicalEntity.id == entity_id,
                HierarchicalEntity.status != "DELETED",
            )
        )
        if not child_entity_check.scalar_one_or_none():
            from src.ai.core.exceptions import EntityNotFoundError
            raise EntityNotFoundError(
                str(entity_id),
                context=(
                    f"not found or deleted. "
                    f"The process template may not have been fully cloned."
                ),
            )

        # Propagate CORTEX tree ID so all entities share one tree.
        child_input = dict(context)
        # input_data is a JSON column — drop any live runtime handle that an
        # AgentLoop-driven parent may have left in context (the Redis client is
        # not JSON-serializable and would poison the INSERT). Belt-and-braces:
        # AgentState now keeps redis off context_state entirely.
        child_input.pop("__redis__", None)
        if "__cortex_tree_id__" in context:
            child_input["cortex_tree_id"] = context["__cortex_tree_id__"]
            logger.info(f"Propagating CORTEX tree {context['__cortex_tree_id__']} to child entity {entity_id}")

        # Set child's 'input' key to the RENDERED prompt_template.
        # Without this, the child inherits the parent's raw 'input' key (often
        # just the original topic string).  The prompt_template typically
        # references variables like {{step_1}} or {{Research Phase}} that
        # contain the actual research data.  After rendering, the full content
        # becomes the child's 'input', so {{input}} at the child level
        # resolves to the complete data instead of the original topic.
        if step.target and step.target.prompt_template:
            rendered_input = parse_variables(step.target.prompt_template, context)
            # Only override if the template actually resolved (isn't just "{{input}}")
            if rendered_input != step.target.prompt_template and rendered_input.strip():
                child_input["input"] = rendered_input
                logger.info(
                    f"Set child input to rendered prompt_template "
                    f"({len(rendered_input)} chars) for step '{step.name}'"
                )

        # Strip parent step_id keys to prevent child step-skip collision.
        # The parent context contains keys like "step_1", "step_2" from its own
        # execution.  When passed to the child, the child's execute_run loop
        # sees "step_1" already in context_state and wrongly skips the child's
        # own step_1.  We remove all generic step_id keys (step_N pattern) while
        # keeping named step outputs and internal context keys.
        import re as _re
        _step_id_pattern = _re.compile(r'^step_\d+$')
        parent_step_keys = [k for k in child_input if _step_id_pattern.match(k)]
        for k in parent_step_keys:
            del child_input[k]
        if parent_step_keys:
            logger.info(
                f"Stripped {len(parent_step_keys)} parent step_id keys from child "
                f"context to prevent step-skip collision: {parent_step_keys}"
            )

        # Strip parent-scoped memory/episodic context to prevent
        # child entities from being confused by previous execution history.
        # The parent's CORTEX __memory__ contains past run summaries that
        # cause child agents to replicate past actions instead of analyzing
        # the current instruction.
        _parent_only_keys = [
            "__memory__", "__episodic_memory__", "__semantic_context__",
            "__memory_context__", "__context_sources__",
            "__completed_steps__", "__goal_check_counter__",
        ]
        stripped_parent_keys = [k for k in _parent_only_keys if k in child_input]
        for k in stripped_parent_keys:
            del child_input[k]
        if stripped_parent_keys:
            logger.info(
                f"Stripped {len(stripped_parent_keys)} parent-scoped memory keys "
                f"from child context: {stripped_parent_keys}"
            )

        # ── Credit gate before spawning child run ─────────────────────────
        # Check that the parent still has credits remaining before launching
        # a potentially expensive child entity (e.g. Research Director).
        # Route through GovernanceService instead of direct CreditService.
        _parent_accumulated = Decimal(str(run.total_cost_usd or 0))
        if self._governance:
            await self._governance.check_child_credit_gate(
                run.company_id, _parent_accumulated, child_entity_id=str(entity_id)
            )
        else:
            logger.warning("GovernanceService not injected — skipping child credit gate")

        # Create Child Run
        child_run = ExecutionRun(
            company_id=run.company_id,
            user_id=run.user_id,
            entity_id=entity_id,
            parent_run_id=run.id,
            trace_id=run.trace_id,
            input_data=child_input,
            status=RunStatus.PENDING
        )
        self.db.add(child_run)
        await self.db.commit()
        await self.db.refresh(child_run)
        return child_run

    async def _execute_tool_call(self, run: ExecutionRun, entity: HierarchicalEntity, step: PlanStep, context: dict) -> dict:
        tool_id = step.target.tool_id if step.target else None
        if not tool_id:
            from src.ai.core.exceptions import ToolExecutionError
            raise ToolExecutionError(step.name, "missing tool_id")
        
        start_time = datetime.utcnow()
        try:
            # Prepare inputs from context/variables
            # Internal keys that should never be passed as tool input
            _INTERNAL_KEYS = INTERNAL_CONTEXT_KEYS
            raw_input = None

            # 1. If the step has a prompt_template, use variable substitution
            if step.target and step.target.prompt_template:
                raw_input = parse_variables(step.target.prompt_template, context)
                # If unresolved {{...}} patterns remain after substitution,
                # the planner used variable names that don't match context keys.
                # Fall back to context-based input resolution instead of
                # sending the literal template string (e.g. "{{url_from_step_2}}")
                # to the tool.
                if re.search(r'\{\{.+?\}\}', raw_input):
                    logger.warning(f"Unresolved variables in tool input after parsing: {raw_input[:200]}")
                    raw_input = None  # trigger fallback below

            # 2. Fallback: use context data
            if raw_input is None:
                if context.get("input"):
                    raw_input = context["input"]
                else:
                    user_ctx = {k: v for k, v in context.items() if k not in _INTERNAL_KEYS}

                    # Prefer the most recent step output (last key that looks like step data)
                    step_keys = [k for k in user_ctx if k.startswith("step_") or "step" in k.lower()]
                    if step_keys:
                        raw_input = str(user_ctx[step_keys[-1]])
                    elif len(user_ctx) == 1:
                        raw_input = str(next(iter(user_ctx.values())))
                    elif user_ctx:
                        raw_input = json.dumps(user_ctx, default=str)
                    else:
                        raw_input = ""
            
            extra_context = {
                "company_id": str(run.company_id),
                "user_id": str(run.user_id) if run.user_id else "default",
                "run_id": str(run.id),
                "agent_id": str(entity.id) if entity is not None else None,
            }

            result = await ToolExecutor.execute_tools([{"tool": tool_id, "input": raw_input}], extra_context=extra_context)
            tool_result = result[0]  # ToolResult dataclass (P3.2)

            # ── Phase 9 Hardening: Extended Self-Healing Retry ────────────
            # Covers FORMAT, IO, EMPTY, and TIMEOUT failures.
            # On persistent failure, tries tool fallback chains.
            _FORMAT_ERROR_KEYWORDS = {"invalid json", "json", "parse", "format", "delimiter", "control character", "expecting", "decode"}
            _IO_ERROR_KEYWORDS = {"no such file or directory", "errno 2", "errno 22", "invalid argument", "file name too long"}
            _EMPTY_KEYWORDS = {"no results", "empty response", "0 results"}
            _TIMEOUT_KEYWORDS = {"timeout", "timed out", "deadline exceeded"}
            tool_output_str = str(tool_result.output or "").lower()

            # Classify failure type
            _is_empty = (
                not tool_result.output
                or (isinstance(tool_result.output, str) and not tool_result.output.strip())
                or any(kw in tool_output_str for kw in _EMPTY_KEYWORDS)
            )
            _is_error_msg = (
                isinstance(tool_result.output, str)
                and tool_result.output.strip().upper().startswith("ERROR:")
            )
            _is_format_err = self._is_format_error(tool_output_str, _FORMAT_ERROR_KEYWORDS)
            _is_io_err = (
                not tool_result.success
                and any(kw in tool_output_str for kw in _IO_ERROR_KEYWORDS)
            )
            _is_timeout = (
                not tool_result.success
                and any(kw in tool_output_str for kw in _TIMEOUT_KEYWORDS)
            )
            _failure_type = (
                "empty" if _is_empty else
                "error_msg" if _is_error_msg else
                "format" if _is_format_err else
                "io" if _is_io_err else
                "timeout" if _is_timeout else
                None
            )

            if _failure_type:
                logger.warning(f"Tool '{tool_id}' failed ({_failure_type}). Output: {tool_output_str[:200]}")

                # Step 1: Try LLM-guided reformat/simplification retry
                reformatted_input = await self._reformat_tool_input(
                    run=run,
                    entity=entity,
                    tool_id=tool_id,
                    original_input=raw_input,
                    error_message=str(tool_result.output or "[EMPTY OUTPUT]"),
                    step_description=step.description or step.name,
                )
                if reformatted_input and reformatted_input != raw_input:
                    logger.info(f"Retrying tool '{tool_id}' with reformatted input ({len(reformatted_input)} chars)")
                    retry_result = await ToolExecutor.execute_tools(
                        [{"tool": tool_id, "input": reformatted_input}],
                        extra_context=extra_context,
                    )
                    retry_tool_result = retry_result[0]
                    retry_output_str = str(retry_tool_result.output or "").lower()
                    _retry_ok = (
                        retry_tool_result.success
                        and retry_tool_result.output
                        and isinstance(retry_tool_result.output, str)
                        and retry_tool_result.output.strip()
                        and not self._is_format_error(retry_output_str, _FORMAT_ERROR_KEYWORDS)
                        and not any(kw in retry_output_str for kw in _IO_ERROR_KEYWORDS)
                    )
                    if _retry_ok:
                        logger.info(f"Retry succeeded for tool '{tool_id}'")
                        tool_result = retry_tool_result
                    else:
                        logger.warning(f"Retry also failed for tool '{tool_id}'")

                # Step 2: If still failing, try tool fallback chain
                _still_failed = (
                    not tool_result.output
                    or (isinstance(tool_result.output, str) and not tool_result.output.strip())
                    or not tool_result.success
                )
                if _still_failed:
                    try:
                        from src.ai.tool_fallback import get_fallback_tool
                        alt_tool_id, alt_input = get_fallback_tool(tool_id, raw_input)
                        if alt_tool_id:
                            # Check entity has access to the fallback tool
                            entity_tools = [t.get("tool_id") for t in (entity.capabilities or {}).get("tools", [])]
                            if alt_tool_id in entity_tools or not entity_tools:
                                logger.info(f"Falling back from '{tool_id}' to '{alt_tool_id}'")
                                alt_result = await ToolExecutor.execute_tools(
                                    [{"tool": alt_tool_id, "input": alt_input}],
                                    extra_context=extra_context,
                                )
                                alt_tool_result = alt_result[0]
                                if alt_tool_result.success and alt_tool_result.output and str(alt_tool_result.output).strip():
                                    logger.info(f"Fallback to '{alt_tool_id}' succeeded!")
                                    tool_result = alt_tool_result
                                    tool_id = f"{tool_id}→{alt_tool_id}"  # Track provenance
                                else:
                                    logger.warning(f"Fallback to '{alt_tool_id}' also failed")
                            else:
                                logger.debug(f"Fallback tool '{alt_tool_id}' not in entity capabilities")
                    except ImportError:
                        pass  # tool_fallback module not yet available
                    except Exception as _fb_err:
                        logger.warning(f"Tool fallback failed: {_fb_err}")

                # Step 3: If STILL empty after all retries, mark as explicit failure
                _final_empty = (
                    not tool_result.output
                    or (isinstance(tool_result.output, str) and not tool_result.output.strip())
                )
                if _final_empty:
                    tool_result.output = (
                        f"[TOOL_EMPTY] Tool '{tool_id}' returned no results after retry. "
                        f"The search/operation may have failed. Original failure type: {_failure_type}."
                    )
                    tool_result.success = False
                    logger.error(f"Tool '{tool_id}' produced no output after all retry attempts")
            # ─────────────────────────────────────────────────────────────
            
            latency = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # Log Tool Call — tool_result is a ToolResult dataclass, not a dict
            log = ToolInteractionLog(
                run_id=run.id,
                tool_id=tool_id,
                tool_name=tool_id,
                input_parameters={"input": raw_input},
                output_result=str(tool_result.output),
                success=tool_result.success,
                latency_ms=latency
            )
            self.db.add(log)

            # ── Track tool cost in run.total_cost_usd ────────────────────────────
            # Look up cost for this tool from integration registry.
            # Match by: service_sku for the tool directly, or by specific
            # service_sku values known to correspond to this tool's backend.
            # Excludes LLM entries to avoid cross-contamination.
            try:
                from src.config.models import IntegrationRegistry as _IR
                from sqlalchemy import select as _sel, or_ as _or
                from decimal import Decimal as _Dec
                # Map built-in tool IDs → known integration registry service_skus
                _TOOL_SKU_MAP = {
                    "web_search": ["serp-api-key"],
                    "batch_web_search": ["serp-api-key"],
                    "scraper_tool": ["firecrawl-api", "firecrawl"],
                    "headless_browser": ["headless-browser"],
                    "pdf_generator": ["pdf-generator"],
                    "image_generation": ["imagen-4.0-generate-001"],
                }
                # Fixed per-call costs for tools that bill independently
                # (used as fallback when IntegrationRegistry has no entry)
                _TOOL_FIXED_COST = {
                    "image_generation": _Dec("0.04"),   # Imagen 4 standard
                    "video_generation": _Dec("0.05"),   # Veo per-call
                    "video_generate": _Dec("0.05"),     # Veo per-call (split tool)
                }
                _sku_matches = _TOOL_SKU_MAP.get(tool_id, [])
                _or_clauses = [
                    _IR.service_sku == tool_id,
                    _IR.service_category == "CUSTOM_API",
                ]
                for _sku in _sku_matches:
                    _or_clauses.append(_IR.service_sku == _sku)
                _ir_result = await self.db.execute(
                    _sel(_IR).where(
                        _IR.company_id == run.company_id,
                        _or(*_or_clauses),
                        _IR.status == "active",
                        _IR.internal_cost.isnot(None),
                        _IR.service_category != "LLM",  # Exclude LLM entries
                    ).limit(1)
                )
                _ir_entry = _ir_result.scalar_one_or_none()
                if _ir_entry and _ir_entry.internal_cost:
                    _tool_cost = _Dec(str(_ir_entry.internal_cost))
                    await self._bump_run_cost(run, _tool_cost, 0)
                    logger.info(f"Tool cost for '{tool_id}': ${_tool_cost} (via {_ir_entry.provider_name}/{_ir_entry.service_sku})")
                    # Log to usage_logs as well
                    from src.ai.models import UsageLog as _UL
                    self.db.add(_UL(
                        company_id=run.company_id,
                        run_id=run.id,
                        sku_id=_ir_entry.id,
                        raw_quantity=_Dec("1"),
                        calculated_cost=_tool_cost,
                        log_metadata={"tool": tool_id, "latency_ms": latency},
                    ))
                elif tool_id in _TOOL_FIXED_COST:
                    _tool_cost = _TOOL_FIXED_COST[tool_id]
                    await self._bump_run_cost(run, _tool_cost, 0)
                    logger.info(f"Tool cost for '{tool_id}': ${_tool_cost} (fixed fallback)")
                else:
                    logger.warning(f"No cost entry found for tool '{tool_id}' — cost not tracked")
            except Exception as _ce:
                logger.warning(f"Could not log tool cost for '{tool_id}': {_ce}")
            # ─────────────────────────────────────────────────────────────────────

            await self.db.commit()
            
            # ── CORTEX Knowledge Ingestion ─────────────────────────────
            # When a scraper/browser tool runs during a CORTEX execution,
            # also write the scraped content as a knowledge node in the
            # CORTEX tree's knowledge subtree. This enables tree-based
            # navigation of research sources.
            if tool_id in ("scraper_tool", "headless_browser") and tool_result.success:
                await self._ingest_tool_result_to_cortex(
                    run=run,
                    tool_id=tool_id,
                    tool_output=tool_result.output,
                    context=context,
                )
            # ───────────────────────────────────────────────────────────
            
            return {"step": step.name, "output": tool_result.output}
        except Exception as e:
            return {"step": step.name, "error": str(e), "success": False}

    def _is_format_error(self, output_lower: str, keywords: set) -> bool:
        """Check if a tool output indicates a formatting/parsing error (not infra)."""
        # Must contain "error" to be an error at all
        if '"error"' not in output_lower and 'error:' not in output_lower:
            return False
        # Exclude infrastructure errors that reformatting can't fix
        _INFRA_KEYWORDS = {"api key", "not configured", "timeout", "connection", "unauthorized", "403", "401", "rate limit"}
        if any(k in output_lower for k in _INFRA_KEYWORDS):
            return False
        # Check for format-related error keywords
        return any(k in output_lower for k in keywords)

    async def _reformat_tool_input(
        self,
        run: 'ExecutionRun',
        entity: 'HierarchicalEntity',
        tool_id: str,
        original_input: str,
        error_message: str,
        step_description: str,
    ) -> Optional[str]:
        """
        Ask the LLM to reformat tool input after a format error.

        Provides the LLM with:
          - The tool's expected JSON schema
          - The original (malformed) input
          - The exact error message from the tool
          - The step's intent (description)

        Returns the reformatted input string, or None if reformatting fails.
        Capped cost: ~200–400 tokens (single fast LLM call).
        """
        try:
            # Get the tool's expected input schema
            tool_schemas = ToolExecutor.get_tool_schemas([tool_id])
            schema_str = json.dumps(tool_schemas[0], indent=2) if tool_schemas else f"Tool '{tool_id}' expects a JSON object."

            system_prompt = (
                "You are a JSON formatting assistant. A tool call failed because "
                "the input was malformed. Your ONLY job is to reformat the input "
                "into valid JSON that matches the tool's expected schema.\n\n"
                "Rules:\n"
                "- Output ONLY the corrected JSON. No explanation, no markdown fences.\n"
                "- Escape all special characters properly (newlines as \\n, tabs as \\t).\n"
                "- Do NOT change the semantic content — only fix the formatting.\n"
                "- If the input is a list of items but the tool expects a single item, "
                "  wrap the first item in the correct schema format."
            )

            user_prompt = (
                f"## Tool Schema\n```json\n{schema_str}\n```\n\n"
                f"## Step Intent\n{step_description}\n\n"
                f"## Original Input (malformed)\n```\n{original_input[:3000]}\n```\n\n"
                f"## Error from Tool\n{error_message}\n\n"
                f"Reformat the input to match the tool's expected JSON schema. "
                f"Output ONLY the corrected JSON:"
            )

            llm_router = LLMRouter(db=self.db, company_id=entity.company_id)
            resp = await llm_router.call_llm(
                task_type="text_generation",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,  # Low temperature for deterministic formatting
                max_tokens=4000,
            )

            # Log the reformat LLM call for billing transparency
            reformat_log = LLMInteractionLog(
                run_id=run.id,
                model_provider=resp.provider,
                model_name=resp.model_name,
                input_prompt=f"[REFORMAT] Tool: {tool_id}",
                output_response=resp.output[:500] if resp.output else "",
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                latency_ms=resp.latency_ms,
                reasoning_mode="REFORMAT",
                step_name=(step_description[:100] if step_description else "__reformat__"),
            )
            self.db.add(reformat_log)
            await self._log_usage(run, resp.model_name, resp.prompt_tokens, resp.completion_tokens, reformat_log)

            reformatted = resp.output.strip()

            # Strip markdown fences if the LLM wrapped the output
            if reformatted.startswith("```"):
                lines = reformatted.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                reformatted = "\n".join(lines).strip()

            logger.debug(f"LLM reformatted tool input: {reformatted[:200]}...")
            return reformatted

        except Exception as e:
            logger.warning(f"LLM reformat failed: {e}")
            return None

    async def _execute_thought(self, run: ExecutionRun, entity: HierarchicalEntity, step: PlanStep, context: dict) -> dict:
        """Execute a THOUGHT or ACTION step using the model-agnostic LLMRouter."""
        logger.debug(f"Executing Thought/Action step: {step.name}")
        logic_gate = entity.logic_gate or {}
        config = logic_gate.get("reasoning_config") or {}

        # Resolve task_type from entity config (new model-agnostic field)
        task_type = config.get("task_type", "text_generation")
        # Allow entity-level model override (e.g. Pro for synthesizer).
        model_override = config.get("model_name")

        # Filter and optionally summarize context
        filtered_context = filter_context_for_step(step, context, logic_gate.get("context_policy"))
        filtered_context = await self._maybe_summarize_context(run, entity, filtered_context)

        # --- Extract identity fields ---
        identity = entity.identity or {}
        system_prompt = identity.get("system_prompt", "You are a helpful assistant.")
        if "persona" in identity:
            system_prompt = identity.get("persona", {}).get("system_prompt", system_prompt)

        # Wire identity.role into the system prompt
        entity_role = identity.get("role") or (identity.get("persona", {}) or {}).get("role", "")
        if entity_role and entity_role != "AI Assistant":
            role_prefix = f"You are {entity.name}, a {entity_role}."
            if not system_prompt.startswith(role_prefix):
                system_prompt = f"{role_prefix}\n\n{system_prompt}"

        few_shot_examples = identity.get("few_shot_examples", [])
        if "persona" in identity:
            few_shot_examples = identity.get("persona", {}).get("few_shot_examples", few_shot_examples)

        # --- Extract architecture fields for prompt ---
        entity_goal = entity.goal or ""
        io_contract = entity.io_contract or {}
        output_schema = io_contract.get("output_schema")
        review_config = logic_gate.get("review_mechanism") or {}
        success_criteria = review_config.get("success_criteria") if review_config.get("enabled") else None
        planning = entity.planning or {}
        dynamic_config = planning.get("dynamic_planning", {})
        allowed_deviations = dynamic_config.get("allowed_deviations") if dynamic_config.get("enabled") else None
        governance = entity.governance or {}

        # Build execution constraints dict
        exec_constraints = {}
        exec_limits = governance.get("execution_limits") or {}
        max_tool_calls = exec_limits.get("max_tool_calls")
        if max_tool_calls:
            used = sum(context.get('tool_call_counts', {}).values())
            exec_constraints["Tool calls remaining"] = f"{max_tool_calls - used} of {max_tool_calls}"
        max_cost = governance.get("max_cost_usd")
        if max_cost:
            current_cost = float(run.total_cost_usd or 0)
            exec_constraints["Cost budget"] = f"${current_cost:.4f} spent of ${max_cost:.2f} max"
        max_depth = governance.get("max_recursion_depth")
        if max_depth:
            exec_constraints["Max recursion depth"] = str(max_depth)

        # Budget-aware REACT (Phase 12 `07` §2): surface budget pressure as a
        # soft constraint and, past a threshold, an explicit "finish, don't
        # expand" directive so the LLM plans within budget instead of relying on
        # the hard engine cap alone. budget_pressure is published by the loop in
        # the materialised context (__agent_state__).
        budget_pressure: Optional[float] = None
        _astate = context.get("__agent_state__") if isinstance(context, dict) else None
        if isinstance(_astate, dict) and _astate.get("budget_pressure") is not None:
            try:
                budget_pressure = float(_astate["budget_pressure"])
            except (TypeError, ValueError):
                budget_pressure = None
        if budget_pressure is not None:
            try:
                from src.ai.core.feature_flags import FeatureFlags
                _ff = FeatureFlags(self.db)
                if await _ff.is_on(
                    "agent_loop.budget_aware_react",
                    company_id=run.company_id,
                    entity_id=getattr(entity, "id", None),
                ):
                    _threshold = await _ff.get_float(
                        "agent_loop.budget_pressure_threshold",
                        company_id=run.company_id,
                        entity_id=getattr(entity, "id", None),
                    )
                    from src.ai.core.budget import budget_prompt_lines
                    exec_constraints.update(
                        budget_prompt_lines(budget_pressure, _threshold)
                    )
            except Exception as _bp_err:  # noqa: BLE001 - prompt nudge is best-effort
                logger.debug(f"budget-aware REACT injection skipped: {_bp_err}")

        # --- Build tools ---
        # Only AUTONOMOUS and BOTH tools are injected into the LLM prompt.
        # PLANNED-only tools are executed deterministically by the static plan executor.
        tool_ids = []
        tool_schemas = []
        if entity.capabilities and entity.capabilities.get("tools"):
            all_tools = entity.capabilities.get("tools", [])
            autonomous_tools = [
                t for t in all_tools
                if t.get("usage", "AUTONOMOUS") in ("AUTONOMOUS", "BOTH")
            ]
            tool_ids = [t.get("tool_id") for t in autonomous_tools]

        # ── Meta-Cognition: Auto-inject meta-tools by tier ─────────────
        from src.ai.meta.platform_schema_compiler import resolve_meta_cognition
        meta_config = resolve_meta_cognition(entity)

        # Tier 2: Registry Search (AGENT + PROCESS)
        if meta_config.get("registry_search"):
            if "meta_registry_search" not in tool_ids:
                tool_ids.append("meta_registry_search")
                logger.debug(f"Tier 2: Auto-injected meta_registry_search for {entity.name}")

        # Tier 3: Self-Modification (AGENT + PROCESS)
        if meta_config.get("self_modification"):
            for meta_tool in ["meta_entity_creator", "meta_entity_executor"]:
                if meta_tool not in tool_ids:
                    tool_ids.append(meta_tool)
            logger.debug(f"Tier 3: Auto-injected meta_entity_creator/executor for {entity.name}")

        # Introspection meta-tools (Phase 12 `06` §3.1) per the §1 matrix.
        if meta_config.get("self_introspection") and "agent_introspect" not in tool_ids:
            tool_ids.append("agent_introspect")
        if meta_config.get("reflection") and "agent_reflect" not in tool_ids:
            tool_ids.append("agent_reflect")
        # ───────────────────────────────────────────────────────────────

        tool_schemas = ToolExecutor.get_tool_schemas(tool_ids)

        # ── Tier 1: Platform Awareness ─────────────────────────────────
        platform_awareness_text = None
        if meta_config.get("platform_awareness"):
            try:
                from src.ai.meta.platform_schema_compiler import get_platform_summary
                platform_awareness_text = await get_platform_summary(
                    db=self.db,
                    company_id=run.company_id,
                    redis=self.redis,
                )
                logger.debug(f"Tier 1: Injected platform awareness ({len(platform_awareness_text)} chars) for {entity.name}")
            except Exception as e:
                logger.warning(f"Tier 1: Failed to load platform awareness: {e}")
        # ───────────────────────────────────────────────────────────────

        # --- Build sandwich system prompt with all architecture fields ---
        # Inject context_sources if available
        ctx_sources_text = filtered_context.get("__context_sources__")
        full_system_prompt = build_sandwich_prompt(
            identity=system_prompt,
            goal=entity_goal,
            tools=tool_schemas,
            few_shot_examples=few_shot_examples,
            context=ctx_sources_text,
            current_task="",
            output_schema=output_schema,
            success_criteria=success_criteria,
            allowed_deviations=allowed_deviations,
            execution_constraints=exec_constraints if exec_constraints else None,
            platform_awareness=platform_awareness_text,
        )

        # --- Resolve reasoning mode and dispatch ---
        # Per-step reasoning is selected by the Strategist's per-step
        # ``reasoning_hint`` (D-3 / C13). The deprecated entity-level
        # ``reasoning_config.reasoning_mode`` no longer steers per-step
        # reasoning; absent a hint a step defaults to REACT.
        _step_hint = getattr(step, "reasoning_hint", None)
        reasoning_mode = str(_step_hint).upper() if _step_hint else "REACT"

        input_vars = {**filtered_context}
        raw_template = step.target.prompt_template if step.target and step.target.prompt_template else "{{input}}"
        user_prompt = parse_variables(raw_template, input_vars)

        # ── Phase 9: Detect unresolved {{variables}} in ACTION/THOUGHT prompts ──
        _unresolved_vars = re.findall(r'\{\{(.+?)\}\}', user_prompt)
        if _unresolved_vars:
            logger.warning(
                f"Unresolved variables in prompt for step '{step.name}': {_unresolved_vars}. "
                f"Upstream steps may have failed or not produced output."
            )
            user_prompt += (
                f"\n\n⚠️ DATA_MISSING: The following data references could not be resolved: "
                f"{', '.join(_unresolved_vars)}. "
                f"If you cannot complete this task without this data, respond with: "
                f"[DATA_MISSING] and explain what information is needed. "
                f"Do NOT fabricate or hallucinate data to fill these gaps."
            )

        # ── Enrich user prompt with prior step context ──────────────────────
        # Dynamic-plan THOUGHT/ACTION steps often have descriptions like
        # "Extract URLs from search results" but no explicit {{step_1.output}}
        # in their prompt_template.  Without appending the actual context data,
        # the LLM receives the instruction but none of the data to work with.
        _INTERNAL_KEYS = INTERNAL_CONTEXT_KEYS
        step_outputs = {
            k: v for k, v in filtered_context.items()
            if k not in _INTERNAL_KEYS and v  # skip empty/None
        }
        if step_outputs:
            context_block = "\n\n## Available Context from Previous Steps\n"
            for ctx_key, ctx_val in step_outputs.items():
                val_str = str(ctx_val)
                # Mark failed/empty steps clearly
                if val_str.startswith("[FAILED]") or val_str.startswith("[TOOL_EMPTY]"):
                    context_block += f"\n### ❌ {ctx_key} (FAILED)\n{val_str[:500]}\n"
                elif val_str.startswith("[TIMEOUT]") or val_str.startswith("[ERROR]"):
                    context_block += f"\n### ⏱️ {ctx_key} (ERROR)\n{val_str[:500]}\n"
                else:
                    # Truncate very large values to avoid overwhelming the prompt
                    if len(val_str) > 30000:
                        val_str = val_str[:30000] + "\n... (truncated)"
                    context_block += f"\n### ✅ {ctx_key}\n{val_str}\n"
            user_prompt += context_block

        # Also include the step description as task instruction if it's not
        # already the prompt (i.e., when prompt_template was a {{variable}} reference)
        if step.description and step.description not in user_prompt:
            user_prompt = f"## Current Task\n{step.description}\n\n{user_prompt}"

        logger.debug(f"Routing via LLMRouter → task_type={task_type}, reasoning_mode={reasoning_mode}, model_override={model_override}")
        # Inject model_override into config so reasoning methods can forward it
        config["__model_override"] = model_override

        # Common tool executor setup
        extra_context = {
            **filtered_context,
            "company_id": str(run.company_id),
            "user_id": str(run.user_id) if run.user_id else "default",
            "run_id": str(run.id),
            "agent_id": str(entity.id) if entity is not None else None,
        }
        context['tool_call_counts'] = {}  # Always reset per step to prevent stale counts on retry/resume

        all_tool_results = []

        # Route reasoning-mode tool calls through ToolResilience when enabled so
        # the REACT/AFC path gets the same reformat-retry + fallback healing as
        # the direct TOOL_CALL path. When the flag is off (or setup fails), the
        # closure falls back to the raw executor — behaviour is unchanged.
        _resilience = None
        try:
            from src.ai.core.feature_flags import FeatureFlags
            if await FeatureFlags(self.db).is_on(
                "tools.resilience_v2_enabled",
                company_id=run.company_id,
                entity_id=getattr(entity, "id", None),
            ):
                from src.ai.tools.resilience import ToolResilience
                _resilience = ToolResilience(
                    reformat_fn=self._reformat_tool_input,
                    tool_executor=ToolExecutor,
                )
        except Exception as _res_err:
            logger.debug(f"ToolResilience setup skipped: {_res_err}")
            _resilience = None

        async def _execute_tools(function_calls: list) -> list:
            """Adapter: called by LLMRouter's REACT loop per tool-call turn."""
            results = []
            for fc in function_calls:
                if _resilience is not None:
                    _tr_single = await _resilience.run_function_call(
                        run=run,
                        entity=entity,
                        function_call=fc,
                        extra_context=extra_context,
                        call_counts=context.get('tool_call_counts', {}),
                        step_name=getattr(step, "name", "") or "",
                        step_description=getattr(step, "description", "") or "",
                    )
                    _tr_list = [_tr_single]
                else:
                    _tr_list = await ToolExecutor.execute_from_function_calls(
                        [fc],
                        extra_context=extra_context,
                        call_counts=context.get('tool_call_counts', {}),
                    )
                for _tr in _tr_list:
                    self.db.add(ToolInteractionLog(
                        run_id=run.id,
                        tool_id=_tr.tool,
                        tool_name=_tr.tool,
                        input_parameters=_tr.args,
                        output_result=str(_tr.output),
                        success=_tr.success,
                        latency_ms=_tr.latency_ms,
                    ))
                    all_tool_results.append(_tr.to_dict())
                    results.append({"tool": _tr.tool, "output": _tr.output, "success": _tr.success})

                    # ── Track tool cost in run.total_cost_usd (AFC path) ──
                    try:
                        from src.config.models import IntegrationRegistry as _IR
                        from sqlalchemy import select as _sel, or_ as _or
                        from decimal import Decimal as _Dec
                        _TOOL_SKU_MAP = {
                            "web_search": ["serp-api-key"],
                            "batch_web_search": ["serp-api-key"],
                            "scraper_tool": ["firecrawl-api", "firecrawl"],
                            "headless_browser": ["headless-browser"],
                            "pdf_generator": ["pdf-generator"],
                            "image_generation": ["imagen-4.0-generate-001"],
                        }
                        _TOOL_FIXED_COST = {
                            "image_generation": _Dec("0.04"),
                            "video_generation": _Dec("0.05"),
                            "video_generate": _Dec("0.05"),
                        }
                        _afc_sku_matches = _TOOL_SKU_MAP.get(_tr.tool, [])
                        _afc_or = [
                            _IR.service_sku == _tr.tool,
                            _IR.service_category == "CUSTOM_API",
                        ]
                        for _s in _afc_sku_matches:
                            _afc_or.append(_IR.service_sku == _s)
                        _afc_ir = await self.db.execute(
                            _sel(_IR).where(
                                _IR.company_id == run.company_id,
                                _or(*_afc_or),
                                _IR.status == "active",
                                _IR.internal_cost.isnot(None),
                                _IR.service_category != "LLM",
                            ).limit(1)
                        )
                        _afc_entry = _afc_ir.scalar_one_or_none()
                        if _afc_entry and _afc_entry.internal_cost:
                            _tc = _Dec(str(_afc_entry.internal_cost))
                            await self._bump_run_cost(run, _tc, 0)
                            logger.info(f"Tool cost for '{_tr.tool}': ${_tc} (via {_afc_entry.provider_name}/{_afc_entry.service_sku})")
                        elif _tr.tool in _TOOL_FIXED_COST:
                            _tc = _TOOL_FIXED_COST[_tr.tool]
                            await self._bump_run_cost(run, _tc, 0)
                            logger.info(f"Tool cost for '{_tr.tool}': ${_tc} (fixed fallback)")
                    except Exception as _tc_err:
                        logger.debug(f"AFC tool cost tracking skipped for '{_tr.tool}': {_tc_err}")
                    # ──────────────────────────────────────────────────────

                    # CORTEX: ingest scraper/browser results as knowledge nodes
                    if _tr.tool in ("scraper_tool", "headless_browser") and _tr.success:
                        await self._ingest_tool_result_to_cortex(
                            run=run,
                            tool_id=_tr.tool,
                            tool_output=_tr.output,
                            context=context,
                        )
            return results

        llm_router = LLMRouter(db=self.db, company_id=run.company_id)

        # ═══════════════════════════════════════════════════════════════════
        # Reasoning Mode Dispatch
        # ═══════════════════════════════════════════════════════════════════
        # D-3: REFLECTION and TREE_OF_THOUGHTS are retired as per-entity modes.
        # Their dispatch branches are gone — REFLECTION is superseded by the
        # AgentLoop Reflector, TREE_OF_THOUGHTS by the Strategist-selected
        # DebateExecutor. The p12 data migration rewrites any entity still
        # configured for them to REACT; an un-migrated entity falls through to
        # the REACT default below (with a warning) rather than running the
        # removed paths.
        from src.ai.schemas.enums import DEPRECATED_REASONING_MODES
        if reasoning_mode in DEPRECATED_REASONING_MODES:
            logger.warning(
                "Entity %s uses retired reasoning_mode=%s (D-3); the per-entity "
                "branch was removed — running REACT instead. Migrate config to "
                "REACT or CHAIN_OF_THOUGHT (debate is now Strategist-selected).",
                getattr(entity, "id", "?"), reasoning_mode,
            )
            reasoning_mode = "REACT"
        if reasoning_mode == "CHAIN_OF_THOUGHT":
            output, response = await self._execute_chain_of_thought(
                llm_router, full_system_prompt, user_prompt, task_type,
                config, tool_schemas, _execute_tools
            )
        else:
            # Default: REACT mode (tool-calling loop)
            response = await llm_router.call_llm_react(
                task_type=task_type,
                system_prompt=full_system_prompt,
                user_prompt=user_prompt,
                tool_schemas=tool_schemas,
                execute_tool_fn=_execute_tools,
                temperature=config.get("temperature", 0.7),
                max_tokens=config.get("max_tokens"),
                max_react_turns=MAX_REACT_TURNS,
                model_override=model_override,
            )
            output = response.output

        # If tools ran, always append a structured summary of tool results
        # so downstream consumers (critic, context) see the full picture.
        if all_tool_results:
            tool_summary = ToolExecutor.format_tool_results(all_tool_results)
            if not output.strip():
                # LLM gave no final text — use tool results as the output
                output = tool_summary
            else:
                # LLM DID produce analysis text — append tool results as reference
                output = output + "\n\n=== Tool Execution Results ===\n" + tool_summary

        # Detect UncertaintySignal from LLM output
        if output and '"needs_clarification": true' in output.lower():
            try:
                _parsed = json.loads(output)
                if _parsed.get("needs_clarification"):
                    raise UncertaintySignal(
                        question=_parsed.get("question", "Uncertain about how to proceed."),
                        confidence=_parsed.get("confidence", 0.0),
                        alternatives=_parsed.get("alternatives", []),
                    )
            except json.JSONDecodeError:
                pass

        logger.debug(f"{reasoning_mode} complete. Tokens: {response.prompt_tokens}+{response.completion_tokens}, latency: {response.latency_ms}ms")

        # Log the interaction
        log = LLMInteractionLog(
            run_id=run.id,
            model_provider=response.provider,
            model_name=response.model_name,
            input_prompt=f"System: {full_system_prompt[:2000]}\nUser: {user_prompt[:2000]}",
            output_response=output,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
            reasoning_mode=reasoning_mode,
            step_name=step.name,
        )
        self.db.add(log)

        await self._log_usage(run, response.model_name, response.prompt_tokens, response.completion_tokens, log)
        await self.db.commit()
        return {"step": step.name, "output": output}

    # ═══════════════════════════════════════════════════════════════════════
    # Reasoning Mode Implementations
    # ═══════════════════════════════════════════════════════════════════════

    async def _execute_chain_of_thought(self, llm_router, system_prompt, user_prompt,
                                         task_type, config, tool_schemas, execute_tool_fn):
        """CHAIN_OF_THOUGHT: Structured thinking with explicit reasoning chain extraction."""
        cot_system = system_prompt + """

## Reasoning Instructions
Think through this problem step by step. Structure your response as:

<thinking>
Step 1: [your analysis]
Step 2: [your analysis]
...
</thinking>

<answer>
[Your final answer here]
</answer>"""

        response = await llm_router.call_llm_react(
            task_type=task_type,
            system_prompt=cot_system,
            user_prompt=user_prompt,
            tool_schemas=tool_schemas,
            execute_tool_fn=execute_tool_fn,
            temperature=config.get("temperature", 0.5),
            max_tokens=config.get("max_tokens"),
            max_react_turns=MAX_REACT_TURNS,
            model_override=config.get("__model_override"),
        )

        output = response.output
        # Extract <answer> block if present, otherwise use full output
        answer_match = re.search(r'<answer>(.*?)</answer>', output, re.DOTALL)
        if answer_match:
            output = answer_match.group(1).strip()

        return output, response

    async def _log_usage(self, run, model_name: str, prompt_tokens: int, completion_tokens: int, log):
        """Helper to log LLM usage stats using model_name from LLMResponse."""
        input_sku = f"{model_name}-in" if model_name else "unknown-in"
        output_sku = f"{model_name}-out" if model_name else "unknown-out"

        logger.debug(f"Logging LLM usage: model={model_name}, in={prompt_tokens}, out={completion_tokens}")

        input_usage = await self.usage_service.log_usage(
            company_id=run.company_id,
            service_sku=input_sku,
            raw_quantity=float(prompt_tokens),
            execution_id=run.id
        )

        output_usage = await self.usage_service.log_usage(
            company_id=run.company_id,
            service_sku=output_sku,
            raw_quantity=float(completion_tokens),
            execution_id=run.id
        )

        # Ensure null-safe accumulation
        if log.cost_usd is None:
            log.cost_usd = Decimal("0")

        # Accumulate the per-interaction log cost in-memory (distinct row per
        # call — never clobbered) and fold the run-level cost in atomically via
        # _bump_run_cost so concurrent isolated-session steps don't lose cost.
        _cost_delta = Decimal("0")
        if input_usage:
            log.cost_usd += input_usage.calculated_cost
            _cost_delta += input_usage.calculated_cost
            logger.info(f"LLM input cost ({input_sku}): {prompt_tokens} tokens → ${input_usage.calculated_cost}")
        else:
            logger.warning(f"No registry entry for SKU '{input_sku}' — input cost not tracked")

        if output_usage:
            log.cost_usd += output_usage.calculated_cost
            _cost_delta += output_usage.calculated_cost
            logger.info(f"LLM output cost ({output_sku}): {completion_tokens} tokens → ${output_usage.calculated_cost}")
        else:
            logger.warning(f"No registry entry for SKU '{output_sku}' — output cost not tracked")

        await self._bump_run_cost(run, _cost_delta, prompt_tokens + completion_tokens)
        logger.info(f"Run total cost so far: ${run.total_cost_usd}, total tokens: {run.total_tokens}")

    async def _maybe_summarize_context(self, run, entity, context_state: dict) -> dict:
        """Smartly trim context if it exceeds threshold, preserving critical keys."""
        if not entity.logic_gate:
            return context_state

        context_policy = (entity.logic_gate or {}).get("context_policy") or {}
        threshold = context_policy.get("summarize_threshold") or 20000

        context_str = json.dumps(context_state, default=str)
        if len(context_str) <= threshold:
            return context_state

        logger.debug(f"Context size {len(context_str)} exceeds threshold {threshold}. Smart-trimming...")

        always_keep = {"input"}
        explicit_preserve = set(context_policy.get("preserve_keys", []))
        always_keep |= explicit_preserve

        all_keys = list(context_state.keys())
        step_keys = [k for k in all_keys if k not in always_keep]
        recent_keys = set(step_keys[-3:]) if step_keys else set()

        trimmed = {k: context_state[k] for k in all_keys if k in always_keep or k in recent_keys}

        trimmed_str = json.dumps(trimmed, default=str)
        if len(trimmed_str) <= threshold:
            logger.debug(f"Smart-trim reduced context to {len(trimmed_str)} chars.")
            return trimmed

        old_keys = [k for k in step_keys if k not in recent_keys]
        if old_keys:
            old_context_str = json.dumps(
                {k: context_state[k] for k in old_keys}, default=str
            )
            try:
                llm_router = LLMRouter(db=self.db, company_id=run.company_id)
                summary_resp = await llm_router.call_llm(
                    task_type="text_generation",
                    system_prompt=(
                        "Summarise the following execution context into 2-3 concise sentences. "
                        "Preserve any specific names, numbers, facts, or JSON structures mentioned."
                    ),
                    user_prompt=old_context_str,
                    temperature=0.3,
                    max_tokens=800,
                )
                trimmed["earlier_context_summary"] = summary_resp.output
            except Exception as e:
                logger.warning(f"Context summarization failed: {e}. Using trimmed context without summary.")

        final_str = json.dumps(trimmed, default=str)
        logger.debug(f"Context trimmed {len(context_str)} -> {len(final_str)} chars.")
        return trimmed

    def _should_exit(self, step: PlanStep, context: dict) -> bool:
        """Evaluates exit conditions for early termination."""
        for condition in step.exit_conditions:
            # Simplified evaluation
            if "error" in str(context.get(step.name, "")).lower():
                if condition.next_step == 'ESCALATE':
                    return True
        return False

