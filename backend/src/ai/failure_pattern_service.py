"""
failure_pattern_service.py — Failure Pattern Extraction (Phase 9 Hardening)

Extracts actionable failure patterns from an entity's recent execution history
and formats them as warnings for prompt injection. This replaces raw episodic
data injection with intelligence-first memory.

Usage (from worker.py):
    fps = FailurePatternService(db)
    patterns = await fps.get_failure_patterns(entity_id, limit=5)
    # Returns: [{"description": "...", "suggestion": "...", "frequency": N}, ...]
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error classification rules
# ---------------------------------------------------------------------------

_ERROR_CLASSIFIERS = [
    {
        "type": "TOOL_EMPTY",
        "keywords": ["[tool_empty]", "returned no results", "empty output"],
        "suggestion": "Simplify search queries or use alternative tools (e.g., headless_browser instead of web_search).",
    },
    {
        "type": "TIMEOUT",
        "keywords": ["[timeout]", "timed out", "deadline exceeded"],
        "suggestion": "Reduce input complexity or increase timeout budget in entity governance settings.",
    },
    {
        "type": "FORMAT_ERROR",
        "keywords": ["invalid json", "parse error", "format error", "decode error"],
        "suggestion": "Ensure tool inputs are properly formatted JSON. Double-check escaping.",
    },
    {
        "type": "API_ERROR",
        "keywords": ["api key", "unauthorized", "403", "401", "not configured"],
        "suggestion": "Check that required API integrations are configured in Service Integrations page.",
    },
    {
        "type": "SCRAPER_BLOCKED",
        "keywords": ["access denied", "cloudflare", "captcha", "bot detection", "403 forbidden"],
        "suggestion": "Use headless_browser instead of scraper_tool for sites with bot protection.",
    },
    {
        "type": "DEPENDENCY_FAILED",
        "keywords": ["[dependency_failed]", "required data from"],
        "suggestion": "Ensure upstream steps complete successfully before dependent steps execute.",
    },
    {
        "type": "DATA_MISSING",
        "keywords": ["[data_missing]", "could not be resolved"],
        "suggestion": "Check that step variables ({{step_N}}) reference valid upstream step IDs.",
    },
]


class FailurePatternService:
    """
    Extracts actionable failure patterns from recent execution history.
    Injects concise warnings into the entity's prompt instead of raw episodic data.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_failure_patterns(
        self,
        entity_id: UUID,
        limit: int = 5,
        lookback_days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Extract failure patterns from recent execution runs.

        Returns list of:
            {"type": "TOOL_EMPTY", "description": "...", "suggestion": "...", "frequency": N}
        """
        try:
            from src.ai.models import ExecutionRun

            cutoff = datetime.utcnow() - timedelta(days=lookback_days)
            result = await self.db.execute(
                select(ExecutionRun).where(
                    ExecutionRun.entity_id == entity_id,
                    ExecutionRun.created_at >= cutoff,
                    ExecutionRun.status.in_(["FAILED", "PARTIAL_COMPLETE"]),
                ).order_by(desc(ExecutionRun.created_at)).limit(20)
            )
            failed_runs = result.scalars().all()

            if not failed_runs:
                return []

            # Classify errors across all failed runs
            error_counts: Counter = Counter()
            error_details: Dict[str, Dict] = {}

            for run in failed_runs:
                ctx = run.context_state or {}
                error_msg = run.error_message or ""

                # Check all context values for error patterns
                all_text = error_msg.lower()
                for key, val in ctx.items():
                    if isinstance(val, str):
                        all_text += " " + val.lower()

                for classifier in _ERROR_CLASSIFIERS:
                    if any(kw in all_text for kw in classifier["keywords"]):
                        error_counts[classifier["type"]] += 1
                        if classifier["type"] not in error_details:
                            error_details[classifier["type"]] = {
                                "type": classifier["type"],
                                "suggestion": classifier["suggestion"],
                            }

            # Build patterns sorted by frequency
            patterns = []
            for error_type, count in error_counts.most_common(limit):
                detail = error_details[error_type]
                patterns.append({
                    "type": error_type,
                    "description": f"{error_type} occurred in {count} of last {len(failed_runs)} failed runs.",
                    "suggestion": detail["suggestion"],
                    "frequency": count,
                })

            return patterns

        except Exception as e:
            logger.debug(f"Failure pattern extraction failed: {e}")
            return []

    async def get_tool_failure_stats(
        self,
        entity_id: UUID,
        lookback_days: int = 30,
    ) -> Dict[str, Dict]:
        """
        Get per-tool failure statistics from ToolInteractionLogs.

        Returns: {"web_search": {"total": 10, "failed": 3, "empty": 2}, ...}
        """
        try:
            from src.ai.models import ToolInteractionLog, ExecutionRun

            cutoff = datetime.utcnow() - timedelta(days=lookback_days)
            result = await self.db.execute(
                select(ToolInteractionLog).join(
                    ExecutionRun, ToolInteractionLog.run_id == ExecutionRun.id
                ).where(
                    ExecutionRun.entity_id == entity_id,
                    ToolInteractionLog.created_at >= cutoff,
                ).order_by(desc(ToolInteractionLog.created_at)).limit(100)
            )
            logs = result.scalars().all()

            stats: Dict[str, Dict] = {}
            for log in logs:
                tool = log.tool_id
                if tool not in stats:
                    stats[tool] = {"total": 0, "failed": 0, "empty": 0}
                stats[tool]["total"] += 1
                if not log.success:
                    stats[tool]["failed"] += 1
                if log.output_result and (
                    not log.output_result.strip()
                    or "[tool_empty]" in log.output_result.lower()
                ):
                    stats[tool]["empty"] += 1

            return stats

        except Exception as e:
            logger.debug(f"Tool failure stats extraction failed: {e}")
            return {}
