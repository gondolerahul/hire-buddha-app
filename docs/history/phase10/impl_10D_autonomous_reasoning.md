# Phase 10D — Autonomous Reasoning: Implementation Plan

> **Prerequisite:** Phase 10B and 10C complete  
> **Estimated Effort:** 4–5 days  
> **Risk Level:** High  
> **Goal:** Production-ize `RecursiveReasoningEngine`. Implement Meta-Agent hooks. Create GoalGuard middleware.

---

## Step 1: Production `RecursiveReasoningEngine`

### Source: `ai/core/recursive_engine.py` (stub from Phase 10A extraction)

### Target: Complete rewrite (same file)

### 1.1 Current Gaps to Fix

| Gap | Fix |
|-----|-----|
| No `company_id` in `__init__` | Pass through to parent |
| No depth limit | Add `MAX_DEPTH = 5` class constant + `max_depth` config |
| No cost tracking | Accumulate step costs via `GovernanceService` |
| No CORTEX integration | Write goal tree to CORTEX as execution proceeds |
| Hardcoded confidence=0.7 | Configurable per-entity via `reasoning_config` |
| No error handling for `_expand_goal` | Graceful degradation to leaf execution |
| No total expansion limit | Add `MAX_TOTAL_EXPANSIONS = 20` |

### 1.2 Implementation

```python
"""
ai.core.recursive_engine — Production recursive goal decomposition engine.

Unlike the flat DAG executor, this engine:
1. Takes a high-level goal
2. Recursively decomposes it until sub-goals are atomic or confidence is high
3. Executes leaf goals via StepExecutorService
4. Synthesizes results bottom-up
5. Writes the entire goal tree to CORTEX
"""
import json
import logging
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from src.ai.core.execution_engine import ExecutionEngine
from src.ai.schemas import GoalNode, PlanStep, StepType

logger = logging.getLogger(__name__)


class RecursiveReasoningEngine(ExecutionEngine):
    """
    Autonomous goal decomposition engine.

    Gated behind entity.reasoning_config.engine_type == "RECURSIVE".
    Falls back to standard ExecutionEngine for all other entity types.
    """

    # Safety limits
    MAX_DEPTH = 5
    MAX_TOTAL_EXPANSIONS = 20
    DEFAULT_CONFIDENCE_THRESHOLD = 0.7

    def __init__(self, db, redis_pool, company_id=None):
        super().__init__(db, redis_pool, company_id=company_id)
        self._expansion_count = 0
        self._total_cost = Decimal("0")

    async def execute_tree(
        self,
        run_id: UUID,
        root_goal: str,
        context: dict,
        tree_id: Optional[UUID] = None,
    ) -> dict:
        """
        Main entry point for recursive goal execution.

        Args:
            run_id: The ExecutionRun ID (for billing, logging)
            root_goal: High-level natural-language goal
            context: Initial context state
            tree_id: Optional CORTEX tree ID for writing goal nodes
        """
        run = await self._load_run(run_id)
        entity = await self._load_entity(run.entity_id)
        self._ensure_services(entity.company_id, run)

        # Get per-entity config
        reasoning_config = (entity.logic_gate or {}).get("reasoning_config", {})
        max_depth = reasoning_config.get("max_depth", self.MAX_DEPTH)
        confidence_threshold = reasoning_config.get(
            "confidence_threshold", self.DEFAULT_CONFIDENCE_THRESHOLD
        )
        cost_ceiling = Decimal(str(reasoning_config.get("cost_ceiling_usd", "1.00")))

        # Build root goal node
        root = GoalNode(goal=root_goal, depth=0)
        self._expansion_count = 0
        self._total_cost = Decimal("0")

        try:
            result = await self._execute_node(
                run, entity, root, context,
                max_depth=max_depth,
                confidence_threshold=confidence_threshold,
                cost_ceiling=cost_ceiling,
                tree_id=tree_id,
            )
            return {
                "output": result,
                "goal_tree": root.to_dict(),
                "total_expansions": self._expansion_count,
                "total_cost_usd": str(self._total_cost),
            }
        except Exception as e:
            logger.error(f"RecursiveReasoningEngine failed: {e}")
            return {
                "error": str(e),
                "goal_tree": root.to_dict(),
                "total_expansions": self._expansion_count,
            }

    async def _execute_node(
        self, run, entity, node: GoalNode, context: dict, *,
        max_depth: int, confidence_threshold: float,
        cost_ceiling: Decimal, tree_id: Optional[UUID],
    ) -> str:
        """Recursively execute a goal node."""
        node.status = "running"

        # Safety: check cost ceiling
        if self._total_cost >= cost_ceiling:
            node.status = "failed"
            node.result = f"Cost ceiling ({cost_ceiling}) exceeded"
            logger.warning(f"RecursiveEngine: Cost ceiling hit at depth {node.depth}")
            return node.result

        # Safety: check depth limit
        if node.depth >= max_depth:
            logger.info(f"RecursiveEngine: Max depth ({max_depth}) reached, executing as leaf")
            return await self._execute_leaf(run, entity, node, context, tree_id)

        # Safety: check expansion limit
        if self._expansion_count >= self.MAX_TOTAL_EXPANSIONS:
            logger.info(f"RecursiveEngine: Max expansions ({self.MAX_TOTAL_EXPANSIONS}) hit")
            return await self._execute_leaf(run, entity, node, context, tree_id)

        # Assess confidence — can we execute this goal directly?
        confidence = await self._assess_confidence(entity, node, context)
        node.confidence = confidence

        if confidence >= confidence_threshold:
            return await self._execute_leaf(run, entity, node, context, tree_id)

        # Decompose into sub-goals
        try:
            children = await self._expand_goal(entity, node, context)
        except Exception as e:
            logger.warning(f"Goal expansion failed, executing as leaf: {e}")
            return await self._execute_leaf(run, entity, node, context, tree_id)

        if not children:
            return await self._execute_leaf(run, entity, node, context, tree_id)

        # Execute children recursively
        results = []
        for child in children:
            child_result = await self._execute_node(
                run, entity, child, context,
                max_depth=max_depth,
                confidence_threshold=confidence_threshold,
                cost_ceiling=cost_ceiling,
                tree_id=tree_id,
            )
            results.append(child_result)

            # Inject child result into context for sibling steps
            context[f"__subgoal_{child.depth}_{len(results)}__"] = child_result

        # Synthesize results
        synthesis = await self._synthesize(entity, node, results, context)
        node.result = synthesis
        node.status = "completed"

        # Write to CORTEX
        if tree_id:
            await self._write_goal_to_cortex(tree_id, node, synthesis)

        return synthesis

    async def _assess_confidence(self, entity, node: GoalNode, context: dict) -> float:
        """Ask the LLM to self-assess confidence for this goal."""
        try:
            from src.ai.llm_router import LLMRouter
            llm = LLMRouter(db=self.db, company_id=entity.company_id)

            prompt = (
                f"On a scale of 0.0 to 1.0, how confident are you that you can "
                f"directly accomplish the following goal WITHOUT needing to break it "
                f"into sub-tasks?\n\n"
                f"Goal: {node.goal}\n"
                f"Depth: {node.depth}\n\n"
                f"Respond with ONLY a number between 0.0 and 1.0."
            )
            response = await llm.call_llm(
                task_type="text_generation",
                system_prompt="You are an AI planning assistant. Respond with only a confidence number.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=10,
            )
            return min(1.0, max(0.0, float(response.output.strip())))
        except Exception:
            return 0.5  # Default: uncertain

    async def _expand_goal(self, entity, node: GoalNode, context: dict) -> List[GoalNode]:
        """Decompose a goal into sub-goals via LLM."""
        self._expansion_count += 1

        from src.ai.llm_router import LLMRouter
        llm = LLMRouter(db=self.db, company_id=entity.company_id)

        prompt = (
            f"Break down the following goal into 2-5 concrete, actionable sub-goals.\n\n"
            f"Goal: {node.goal}\n"
            f"Current depth: {node.depth}\n\n"
            f"Respond with a JSON array of strings, each being a sub-goal:\n"
            f'["sub-goal 1", "sub-goal 2", ...]'
        )
        response = await llm.call_llm(
            task_type="text_generation",
            system_prompt="You are a goal decomposition expert. Respond with JSON only.",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=500,
        )

        from src.ai.shared.json_utils import parse_json_array
        sub_goals = parse_json_array(response.output)

        # Track cost
        cost = Decimal(str(response.cost_usd or 0))
        self._total_cost += cost

        children = []
        for sg in sub_goals:
            if isinstance(sg, str):
                child = GoalNode(
                    goal=sg,
                    depth=node.depth + 1,
                    parent=node,
                )
                children.append(child)
                node.children.append(child)
            elif isinstance(sg, dict) and "goal" in sg:
                child = GoalNode(
                    goal=sg["goal"],
                    depth=node.depth + 1,
                    parent=node,
                )
                children.append(child)
                node.children.append(child)

        return children

    async def _execute_leaf(self, run, entity, node: GoalNode, context: dict, tree_id=None) -> str:
        """Execute a leaf goal as a single THOUGHT step."""
        step = PlanStep(
            name=f"Goal: {node.goal[:60]}",
            type=StepType.THOUGHT,
            description=node.goal,
        )
        result = await self._step_executor._execute_step(run, entity, step, context)
        output = result.get("output", "") if isinstance(result, dict) else str(result)

        # Track cost
        if isinstance(result, dict):
            cost = Decimal(str(result.get("cost_usd", 0) or 0))
            self._total_cost += cost

        node.result = output
        node.status = "completed"

        # Write to CORTEX
        if tree_id:
            await self._write_goal_to_cortex(tree_id, node, output)

        return output

    async def _synthesize(self, entity, node: GoalNode, results: list, context: dict) -> str:
        """Synthesize child results into a unified answer for the parent goal."""
        from src.ai.llm_router import LLMRouter
        llm = LLMRouter(db=self.db, company_id=entity.company_id)

        results_text = "\n\n".join([f"Sub-result {i+1}: {r[:2000]}" for i, r in enumerate(results)])
        prompt = (
            f"You have completed the following sub-tasks for the goal: {node.goal}\n\n"
            f"{results_text}\n\n"
            f"Synthesize these results into a comprehensive answer for the original goal."
        )
        response = await llm.call_llm(
            task_type="text_generation",
            system_prompt="You are a synthesis expert. Combine sub-task results into a coherent answer.",
            user_prompt=prompt,
            temperature=0.5,
            max_tokens=2000,
        )

        cost = Decimal(str(response.cost_usd or 0))
        self._total_cost += cost

        return response.output

    async def _write_goal_to_cortex(self, tree_id: UUID, node: GoalNode, output: str):
        """Write a goal node and its result to the CORTEX tree."""
        try:
            cortex = self._cortex_bridge._get_cortex_service()
            working_root = await cortex.get_working_root(tree_id)
            if working_root:
                await cortex.write(
                    parent_id=working_root.id,
                    node_type="finding",
                    title=f"🎯 Goal (d={node.depth}): {node.goal[:80]}",
                    summary=output[:300],
                    content=output[:50000],
                    status="complete" if node.status == "completed" else "failed",
                    source_ref={
                        "type": "recursive_goal",
                        "depth": node.depth,
                        "confidence": node.confidence,
                        "expansions": self._expansion_count,
                    },
                )
        except Exception as e:
            logger.debug(f"CORTEX goal write failed: {e}")
```

### 1.3 Entry Point Integration

Add routing in `execute_run()` — check if the entity uses recursive reasoning:

```python
# In ExecutionEngine.execute_run(), before the standard step loop:
reasoning_config = (entity.logic_gate or {}).get("reasoning_config", {})
engine_type = reasoning_config.get("engine_type", "DAG")  # "DAG" or "RECURSIVE"

if engine_type == "RECURSIVE":
    from src.ai.core.recursive_engine import RecursiveReasoningEngine
    recursive = RecursiveReasoningEngine(self.db, self.redis, company_id=entity.company_id)
    result = await recursive.execute_tree(
        run_id=run.id,
        root_goal=entity.goal or entity.name,
        context=context_state,
        tree_id=tree.id if tree else None,
    )
    # ... finalization ...
    return result
```

### 1.4 Configuration schema

Add to entity `reasoning_config`:

```json
{
  "engine_type": "RECURSIVE",      // "DAG" (default) or "RECURSIVE"
  "max_depth": 4,                   // Max goal tree depth
  "confidence_threshold": 0.75,     // Expand if below this
  "cost_ceiling_usd": "2.00",       // Stop if total cost exceeds this
  "max_replanning_attempts": 3      // Existing field, kept for DAG mode
}
```

---

## Step 2: Meta-Agent Supervisory Hooks

### 2.1 Create `ai/core/meta_review.py`

```python
"""
ai.core.meta_review — Meta-Agent review hooks for execution monitoring.

Periodically invokes the Meta-Agent to assess execution quality and
recommend adjustments (continue, replan, abort).
"""
import logging
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MetaReviewer:
    """
    Lightweight wrapper that invokes the Meta-Agent for execution review.

    Called by the execution loop every N steps to assess:
    - Is the execution on track toward the goal?
    - Should we replan?
    - Should we abort?
    """

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def review_execution(
        self,
        entity_goal: str,
        completed_steps: List[Dict],
        remaining_steps: List[Dict],
        total_cost_usd: float = 0,
        context_summary: str = "",
    ) -> Dict:
        """
        Ask the Meta-Agent to review execution progress.

        Returns:
            {
                "recommendation": "CONTINUE" | "REPLAN" | "ABORT",
                "confidence": 0.0–1.0,
                "reasoning": "...",
                "adjustments": [...]  # Optional suggested changes
            }
        """
        try:
            from src.ai.llm_router import LLMRouter
            llm = LLMRouter(db=self.db, company_id=self.company_id)

            completed_summary = "\n".join([
                f"  {i+1}. {s.get('step_name', 'Unknown')}: "
                f"{'✅' if not s.get('error') else '❌'} "
                f"{str(s.get('output', ''))[:100]}"
                for i, s in enumerate(completed_steps[-5:])  # Last 5 steps
            ])

            remaining_summary = "\n".join([
                f"  {i+1}. {s.get('name', 'Unknown')} ({s.get('type', '?')})"
                for i, s in enumerate(remaining_steps[:5])  # Next 5 steps
            ])

            prompt = (
                f"## Execution Review Request\n\n"
                f"**Goal:** {entity_goal}\n"
                f"**Completed steps ({len(completed_steps)}):**\n{completed_summary}\n\n"
                f"**Remaining steps ({len(remaining_steps)}):**\n{remaining_summary}\n\n"
                f"**Total cost so far:** ${total_cost_usd:.4f}\n\n"
                f"Assess whether this execution is on track. Respond with JSON:\n"
                f'{{"recommendation": "CONTINUE|REPLAN|ABORT", '
                f'"confidence": 0.0-1.0, "reasoning": "..."}}'
            )

            response = await llm.call_llm(
                task_type="text_generation",
                system_prompt=(
                    "You are a Meta-Agent supervisor reviewing an AI agent's execution. "
                    "Be concise. Respond with JSON only."
                ),
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=300,
            )

            from src.ai.shared.json_utils import parse_json_object
            result = parse_json_object(response.output)
            if result:
                return {
                    "recommendation": result.get("recommendation", "CONTINUE").upper(),
                    "confidence": float(result.get("confidence", 0.5)),
                    "reasoning": result.get("reasoning", ""),
                    "adjustments": result.get("adjustments", []),
                }

        except Exception as e:
            logger.warning(f"Meta-review failed (non-fatal): {e}")

        return {"recommendation": "CONTINUE", "confidence": 0.5, "reasoning": "Review unavailable"}
```

### 2.2 Wire into execution loop

**Location:** Sequential step loop in `execute_run()`

```python
# After step execution, before the existing goal validation gate:
governance_config = entity.governance or {}
meta_review_enabled = governance_config.get("meta_review_enabled", False)
meta_review_interval = int(governance_config.get("meta_review_interval", 5))

if meta_review_enabled and step_idx > 0 and step_idx % meta_review_interval == 0:
    from src.ai.core.meta_review import MetaReviewer
    reviewer = MetaReviewer(self.db, entity.company_id)
    meta_result = await reviewer.review_execution(
        entity_goal=entity.goal or entity.name,
        completed_steps=all_step_results,
        remaining_steps=steps[step_idx + 1:],
        total_cost_usd=float(run.total_cost_usd or 0),
    )

    if meta_result["recommendation"] == "REPLAN":
        logger.info(f"Meta-Agent recommends REPLAN: {meta_result['reasoning']}")
        if replanning_count < max_replans:
            replanning_count += 1
            revised = await self._planner.adapt_plan(
                steps, all_step_results, {}, entity.goal or entity.name
            )
            if revised:
                steps = steps[:step_idx + 1] + revised
    elif meta_result["recommendation"] == "ABORT":
        logger.warning(f"Meta-Agent recommends ABORT: {meta_result['reasoning']}")
        from src.ai.core.exceptions import MetaAgentAbort
        raise MetaAgentAbort(meta_result["reasoning"])
```

---

## Step 3: GoalGuard Unified Middleware

### 3.1 Create `ai/planning/goal_guard.py`

```python
"""
ai.planning.goal_guard — Unified post-step goal validation.

Combines:
1. GoalAlignmentVerifier (step output vs entity goal) — triggers retry
2. PlannerService.validate_goal_progress (overall progress) — triggers replan/early-exit

Replaces the two separate inline checks in execute_run().
"""
import logging
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class GoalGuard:
    """
    Post-step goal validation middleware.

    Usage:
        guard = GoalGuard(db, company_id, entity_goal, planner)
        action = await guard.check(step_result, step_name, step_idx, total_steps)
        # action.type: "CONTINUE" | "RETRY" | "REPLAN" | "EARLY_EXIT"
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        entity_goal: str,
        task_description: str,
        planner=None,
        confidence_threshold: float = 0.85,
    ):
        self.db = db
        self.company_id = company_id
        self.entity_goal = entity_goal
        self.task_description = task_description
        self.planner = planner
        self.confidence_threshold = confidence_threshold

    async def check(
        self,
        step_result: dict,
        step_name: str,
        step_idx: int,
        all_results: list,
        total_steps: int,
        is_autonomous: bool = False,
        goal_interval: int = 2,
    ) -> Dict:
        """
        Run post-step goal validation.

        Returns:
            {
                "action": "CONTINUE" | "RETRY" | "REPLAN" | "EARLY_EXIT",
                "reason": str,
                "correction_hint": str (if RETRY),
                "revised_steps": list (if REPLAN),
            }
        """
        result = {"action": "CONTINUE", "reason": ""}

        # Check 1: Step-level alignment (is this step's output on-topic?)
        if step_result and isinstance(step_result, dict):
            output = str(step_result.get("output", ""))[:2000]
            if output and not step_result.get("error"):
                from src.ai.planning.goal_alignment import GoalAlignmentVerifier
                verifier = GoalAlignmentVerifier(self.db, self.company_id)
                alignment = await verifier.verify_step_alignment(
                    entity_goal=self.entity_goal,
                    task_desc=self.task_description,
                    step_output=output,
                    step_name=step_name,
                )
                if not alignment["aligned"]:
                    return {
                        "action": "RETRY",
                        "reason": f"Step '{step_name}' misaligned: {alignment['issues']}",
                        "correction_hint": alignment.get("correction_hint", ""),
                    }

        # Check 2: Overall goal progress (autonomous mode only)
        if is_autonomous and step_idx > 0 and step_idx % goal_interval == 0:
            if self.planner:
                try:
                    validation = await self.planner.validate_goal_progress(
                        goal=self.entity_goal,
                        completed_steps=all_results,
                        total_steps=total_steps,
                    )
                    score = validation.get("score", 0)
                    if score > self.confidence_threshold * 100:
                        return {
                            "action": "EARLY_EXIT",
                            "reason": f"Goal achieved (score={score})",
                        }
                    elif score < 30 and step_idx > total_steps // 2:
                        return {
                            "action": "REPLAN",
                            "reason": f"Low progress ({score}) past midpoint",
                        }
                except Exception as e:
                    logger.debug(f"Goal validation failed: {e}")

        return result
```

### 3.2 Integration into the execution loop

Replace the two separate inline checks (~50 lines) with:

```python
# Initialize once before the step loop:
goal_guard = GoalGuard(
    db=self.db,
    company_id=entity.company_id,
    entity_goal=entity.goal or entity.name,
    task_description=task_desc,
    planner=self._planner,
    confidence_threshold=confidence_threshold,
)

# After each step execution:
guard_result = await goal_guard.check(
    step_result=step_result,
    step_name=step_obj.name,
    step_idx=step_idx,
    all_results=all_step_results,
    total_steps=len(steps),
    is_autonomous=is_autonomous,
    goal_interval=goal_interval,
)

if guard_result["action"] == "RETRY":
    # Re-execute step with correction hint
    step_obj.description += f"\n\nCORRECTION: {guard_result['correction_hint']}"
    step_result = await self._execute_step_wrapper(run, entity, step_obj, context_state)
elif guard_result["action"] == "REPLAN" and replanning_count < max_replans:
    replanning_count += 1
    revised = await self._planner.adapt_plan(steps, all_step_results, {}, entity.goal or entity.name)
    if revised:
        steps = steps[:step_idx + 1] + revised
elif guard_result["action"] == "EARLY_EXIT":
    logger.info(f"GoalGuard: {guard_result['reason']}")
    break
```

---

## Validation Checklist (Phase 10D Complete)

- [ ] `RecursiveReasoningEngine` runs with depth limit, cost ceiling, and CORTEX integration
- [ ] Entity with `engine_type: "RECURSIVE"` decomposes goals and synthesizes results
- [ ] Entity with `engine_type: "DAG"` (default) behaves identically to before
- [ ] `MetaReviewer` triggers REPLAN/ABORT when appropriate
- [ ] `GoalGuard` replaces inline goal checks in the execution loop
- [ ] All autonomous features gated behind entity-level config flags
- [ ] Cost ceiling prevents unbounded LLM expenditure
- [ ] `python -m arq src.ai.worker.WorkerSettings` starts without errors
- [ ] End-to-end test with recursive entity → verify goal tree in CORTEX

---

> **Next:** [impl_10E_hardening_testing.md](./impl_10E_hardening_testing.md)
