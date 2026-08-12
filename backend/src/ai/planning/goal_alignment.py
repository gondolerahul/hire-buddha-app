"""
goal_alignment.py — Post-Step Goal Alignment Verification (Phase 9 Hardening)

Lightweight LLM-based verification that checks whether a step's output
aligns with the entity's declared goal. Catches topic drift (e.g., an
agent producing "AI in Asset Management" when the goal is "Brain Modeling").

Usage (from worker.py):
    verifier = GoalAlignmentVerifier(db, company_id)
    result = await verifier.verify_step_alignment(
        entity_goal="Research brain modeling",
        task_desc="Find academic sources on computational neuroscience",
        step_output="... output text ...",
        step_name="Rank and Deduplicate Sources",
    )
    if not result["aligned"]:
        # Re-execute with correction hint
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


VERIFICATION_PROMPT = """You are a strict quality control checker for an autonomous AI agent pipeline.

The entity's GOAL is: {goal}
The entity's current TASK is: {task_description}

A step named "{step_name}" just completed with the following output (first 2000 chars):
---
{step_output}
---

Does this output align with the stated goal and task? Consider:
1. Is the topic/subject matter correct? (e.g., if goal is about "brain modeling", output should NOT be about "asset management")
2. Does the output contain relevant data for the goal?
3. Are there any signs of topic drift, hallucination, or off-topic content?
4. Is the output substantive (not just error messages or empty)?

Respond with ONLY a JSON object:
{{
    "aligned": true or false,
    "confidence": 0.0 to 1.0,
    "issues": ["list of detected issues, empty if aligned"],
    "correction_hint": "if misaligned, what the step SHOULD have produced"
}}"""


class GoalAlignmentVerifier:
    """
    Post-step verification: checks that step output aligns with the entity's
    declared goal. Uses a cheap, fast LLM call with low temperature.
    """

    def __init__(self, db: AsyncSession, company_id: UUID):
        self.db = db
        self.company_id = company_id

    async def verify_step_alignment(
        self,
        entity_goal: str,
        task_desc: str,
        step_output: str,
        step_name: str,
    ) -> Dict[str, Any]:
        """
        Verify that a step's output aligns with the entity's goal.

        Returns:
            {
                "aligned": bool,
                "confidence": float (0-1),
                "issues": List[str],
                "correction_hint": str
            }
        """
        if not entity_goal or not step_output:
            return {"aligned": True, "confidence": 1.0, "issues": [], "correction_hint": ""}

        # Skip verification for error/failure outputs — those are already handled
        output_prefix = step_output.strip()[:50].lower()
        if any(output_prefix.startswith(p) for p in [
            "[tool_empty]", "[failed]", "[timeout]", "[error]",
            "[dependency_failed]", "[data_missing]",
        ]):
            return {"aligned": True, "confidence": 1.0, "issues": [], "correction_hint": ""}

        try:
            from src.ai.llm.router import LLMRouter
            llm = LLMRouter(db=self.db, company_id=self.company_id)

            prompt = VERIFICATION_PROMPT.format(
                goal=entity_goal,
                task_description=task_desc,
                step_name=step_name,
                step_output=step_output[:2000],
            )

            response = await llm.call_llm(
                task_type="text_generation",
                system_prompt="You are a strict quality control verifier. Respond with JSON only.",
                user_prompt=prompt,
                temperature=0.1,  # Low temperature for consistent judgments
                max_tokens=500,
            )

            try:
                from src.ai.usage_service import UsageService
                svc = UsageService(self.db)
                model = getattr(response, "model_name", "") or ""
                if model:
                    if response.prompt_tokens:
                        await svc.log_usage(
                            company_id=self.company_id,
                            service_sku=f"{model}-in",
                            raw_quantity=float(response.prompt_tokens),
                            attribution="critic_align",
                        )
                    if response.completion_tokens:
                        await svc.log_usage(
                            company_id=self.company_id,
                            service_sku=f"{model}-out",
                            raw_quantity=float(response.completion_tokens),
                            attribution="critic_align",
                        )
            except Exception:                                                    # pragma: no cover
                pass

            return self._parse_response(response.output)

        except Exception as e:
            logger.warning(f"Goal alignment verification failed: {e}")
            # On error, assume aligned to avoid blocking execution
            return {"aligned": True, "confidence": 0.5, "issues": [f"Verification error: {e}"], "correction_hint": ""}

    def _parse_response(self, output: str) -> Dict[str, Any]:
        """Parse the LLM's JSON response, with fallback for malformed output."""
        default = {"aligned": True, "confidence": 0.5, "issues": [], "correction_hint": ""}

        if not output:
            return default

        # Try to extract JSON from the output
        text = output.strip()

        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            result = json.loads(text)
            return {
                "aligned": bool(result.get("aligned", True)),
                "confidence": float(result.get("confidence", 0.5)),
                "issues": list(result.get("issues", [])),
                "correction_hint": str(result.get("correction_hint", "")),
            }
        except (json.JSONDecodeError, TypeError, ValueError):
            # If we can't parse, try to detect obvious misalignment signals
            lower = output.lower()
            if '"aligned": false' in lower or '"aligned":false' in lower:
                return {
                    "aligned": False,
                    "confidence": 0.7,
                    "issues": ["Output parsed as misaligned (JSON parse failed)"],
                    "correction_hint": output[:200],
                }
            return default
