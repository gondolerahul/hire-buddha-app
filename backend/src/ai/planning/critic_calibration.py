"""
ai.planning.critic_calibration — Weekly critic-calibration job (Phase 11 Track 3).

For each (entity, task class), sample the last N StepHealthRecords
written by the CriticPipeline, cross-reference them with the final
ExecutionRun outcomes and any user_refinement signals, and compute:

  * ``false_pass_rate`` — fraction of PASS verdicts whose run ultimately
    FAILED, was REFINED, or was flagged by the user.
  * ``false_fail_rate`` — fraction of REJECT/REVISE verdicts whose run
    actually completed successfully.

The results are written back as Intelligence rules so the Strategist
(Track 4) and the Planner (Track 7) can consult them.

Design notes:
  * The job is *idempotent and read-mostly*; rerunning has no side
    effects beyond updating Intelligence rule rows.
  * It is intentionally lenient on missing data: if the IntelligenceTree
    service is not available (early rollouts), the calibration still
    computes and logs metrics for telemetry, just skips persistence.
  * No DB migration. Calibrator reads CORTEX node content (the JSON
    blob written by RealCriticPipeline._persist_record) and joins by
    tree → run.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

__all__ = ["CriticCalibrator", "CalibrationResult"]


_SAMPLE_WINDOW_DAYS = 7
_MIN_SAMPLES = 30          # below this, we still log but won't write a rule
_MAX_SAMPLES = 200


@dataclass
class CalibrationResult:
    entity_id: Optional[UUID]
    task_class: str
    samples: int
    pass_count: int = 0
    fail_count: int = 0
    user_flag_count: int = 0
    false_pass_rate: float = 0.0
    false_fail_rate: float = 0.0
    by_tag: dict[str, int] = field(default_factory=dict)

    def to_intel_payload(self) -> dict[str, Any]:
        return {
            "type": "critic_calibration",
            "task_class": self.task_class,
            "samples": self.samples,
            "false_pass_rate": round(self.false_pass_rate, 4),
            "false_fail_rate": round(self.false_fail_rate, 4),
            "tag_distribution": self.by_tag,
            "computed_at": datetime.utcnow().isoformat(),
        }


class CriticCalibrator:
    """Reads StepHealthRecord CORTEX nodes and writes Intelligence rules."""

    def __init__(
        self,
        db: AsyncSession,
        company_id: UUID,
        *,
        window_days: int = _SAMPLE_WINDOW_DAYS,
    ):
        self.db = db
        self.company_id = company_id
        self.window_days = window_days

    async def run(self) -> list[CalibrationResult]:
        from src.ai.memory.cortex_models import CortexNode

        since = datetime.utcnow() - timedelta(days=self.window_days)
        rows = (await self.db.execute(
            select(CortexNode)
            .where(and_(
                CortexNode.node_type == "health_record",
                CortexNode.created_at >= since,
            ))
            .limit(_MAX_SAMPLES * 50)  # broad pull; we group below
        )).scalars().all()

        # Group by (entity, task_class). Each CortexNode has its own
        # execution_run_id FK, so we can fetch runs directly without a
        # tree join.
        from src.ai.orm.execution import ExecutionRun
        from sqlalchemy.orm import selectinload

        run_ids = {r.execution_run_id for r in rows if r.execution_run_id is not None}
        runs_by_id: dict[UUID, Any] = {}
        if run_ids:
            run_rows = (await self.db.execute(
                select(ExecutionRun)
                .options(selectinload(ExecutionRun.entity))
                .where(ExecutionRun.id.in_(run_ids))
            )).scalars().all()
            for run_row in run_rows:
                runs_by_id[run_row.id] = run_row

        buckets: dict[tuple[Optional[UUID], str], list[tuple[dict[str, Any], Any]]] = defaultdict(list)
        for r in rows:
            run = runs_by_id.get(cast(UUID, r.execution_run_id))
            if run is None:
                continue
            # Scope to this calibrator's company; the broad CortexNode pull
            # above is global, so filter out runs from other tenants before
            # we persist rules into this company's Intelligence Tree.
            if getattr(run, "company_id", None) != self.company_id:
                continue
            entity_id = getattr(run, "entity_id", None)
            task_class = self._task_class_for(run)
            try:
                payload = json.loads(cast(str, r.content) or "{}")
            except Exception:
                continue
            buckets[(entity_id, task_class)].append((payload, run))

        results: list[CalibrationResult] = []
        for (entity_id, task_class), records in buckets.items():
            if not records:
                continue
            res = self._compute(entity_id, task_class, records)
            results.append(res)
            logger.info(
                "critic_calibration: entity=%s task_class=%s samples=%d "
                "false_pass=%.3f false_fail=%.3f",
                entity_id, task_class, res.samples,
                res.false_pass_rate, res.false_fail_rate,
            )
            if res.samples >= _MIN_SAMPLES:
                await self._persist_intel_rule(res)

        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _task_class_for(run: Any) -> str:
        """Best-effort task-class identifier for grouping."""
        if getattr(run, "entity", None) is not None and getattr(run.entity, "type", None):
            return f"entity_type:{run.entity.type}"
        return f"run:{getattr(run, 'execution_mode', 'unknown')}"

    @staticmethod
    def _compute(
        entity_id: Optional[UUID],
        task_class: str,
        records: list[tuple[dict[str, Any], Any]],
    ) -> CalibrationResult:
        from src.ai.schemas.enums import RunStatus

        result = CalibrationResult(
            entity_id=entity_id,
            task_class=task_class,
            samples=len(records),
        )
        false_pass = 0
        false_fail = 0
        actual_pass_sample = 0
        actual_fail_sample = 0
        for payload, run in records:
            verdict = payload.get("post_critic_verdict")
            tags = payload.get("post_critic_tags") or []
            for t in tags:
                key = str(t)
                result.by_tag[key] = result.by_tag.get(key, 0) + 1

            run_status = getattr(run, "status", None)
            run_failed = run_status == RunStatus.FAILED.value
            run_succeeded = run_status == RunStatus.COMPLETED.value
            user_flagged = bool(getattr(run, "user_refinement_count", 0))

            if verdict == "PASS":
                result.pass_count += 1
                if run_failed or user_flagged:
                    false_pass += 1
                    result.user_flag_count += int(user_flagged)
                actual_pass_sample += 1
            elif verdict in ("REVISE", "REJECT"):
                result.fail_count += 1
                if run_succeeded:
                    false_fail += 1
                actual_fail_sample += 1

        result.false_pass_rate = (
            false_pass / actual_pass_sample if actual_pass_sample else 0.0
        )
        result.false_fail_rate = (
            false_fail / actual_fail_sample if actual_fail_sample else 0.0
        )
        return result

    async def _persist_intel_rule(self, res: CalibrationResult) -> None:
        """Best-effort: write the calibration result as an Intelligence rule.

        Uses a duck-typed import so the calibrator does not hard-depend on
        a particular IntelligenceTree implementation. If the service does
        not exist yet (early rollout), we just log the payload.
        """
        try:
            from src.ai.memory.intelligence_tree_service import (
                IntelligenceTreeService,
            )
        except Exception:                                                   # pragma: no cover
            logger.info(
                "critic_calibration: IntelligenceTree unavailable; skipping "
                "persistence for entity=%s task_class=%s",
                res.entity_id, res.task_class,
            )
            return

        try:
            svc = IntelligenceTreeService(self.db, self.company_id)
            write = getattr(svc, "upsert_calibration_rule", None) or getattr(
                svc, "record_rule", None,
            )
            if write is None:
                logger.debug(
                    "IntelligenceTreeService has no calibration-write method "
                    "yet; payload=%s", res.to_intel_payload(),
                )
                return
            await write(
                entity_id=res.entity_id,
                task_class=res.task_class,
                payload=res.to_intel_payload(),
            )
        except Exception as exc:                                            # noqa: BLE001
            logger.warning("Failed to persist calibration rule: %s", exc)
