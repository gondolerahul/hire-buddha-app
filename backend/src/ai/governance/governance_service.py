"""
governance_service.py — Billing, credit gating, and HITL approval logic.

Extracted from ExecutionEngine during Phase 6 monolith decomposition
(Step 3.1). Encapsulates all financial guardrails and human-in-the-loop
checkpoints so the engine can delegate without knowing billing internals.
"""
import json
import asyncio
import logging
from decimal import Decimal
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import select, update

from src.billing.credit_service import CreditService, InsufficientCreditsError, minimum_threshold
from src.billing.billing_service import BillingService, calculate_tb, compute_billed_amount
from src.ai.models import HumanApproval, ExecutionRun
from src.ai.schemas import HITLCheckpoint, HITLTriggerType, StepType, PlanStep
from src.ai.governance.hitl_snapshot import build_hitl_snapshot

logger = logging.getLogger(__name__)


class GovernanceService:
    """Handles credit gates, HITL approvals, and billing settlement."""

    def __init__(self, db: Any, redis: Any) -> None:
        self.db = db
        self.redis = redis
        self.credit_service = CreditService(db)
        self.billing_service = BillingService(db)

    # ------------------------------------------------------------------
    # Credit gate, hold and circuit breaker (BC-05, BC-06)
    # ------------------------------------------------------------------

    async def check_credit_gate(
        self, run: 'ExecutionRun', entity_type: str, estimate: Decimal,
    ) -> Decimal:
        """Admit a top-level run and hold its estimated bill.

        Raises InsufficientCreditsError when less than the entity type's
        minimum is free (the wallet minus other runs' holds). Returns the
        amount held. Errors reading the wallet propagate: a run whose credit
        cannot be checked does not start (before BC-05 this gate swallowed
        them — and had no callers at all).
        """
        held = await self.credit_service.place_hold(
            run.company_id, run.id, estimate, minimum_threshold(entity_type)
        )
        logger.info(
            f"Credit gate passed for run {run.id}: holding ${held:.4f} "
            f"(estimate ${estimate:.4f}, entity_type={entity_type})"
        )
        return held

    async def check_credit_circuit_breaker(
        self, run: 'ExecutionRun', accumulated_cost: Decimal,
    ) -> None:
        """Stop a run once its bill so far reaches the credit it may spend.

        The bill is ``accumulated_cost`` (raw provider cost) through the TB
        formula — what settlement will charge. The credit it may spend is the
        wallet minus other runs' holds. Raises InsufficientCreditsError to
        stop; a failure to read the wallet is logged and the run continues
        (settlement still charges it).
        """
        try:
            config = await self.billing_service.get_billing_config(run.company_id)
            billed = compute_billed_amount(accumulated_cost, config)
            balance = await self.credit_service.get_balance(run.company_id)
            others = await self.credit_service.held_by_others(run.company_id, run.id)
            spendable = Decimal(str(balance["total_available"])) - others
        except Exception as e:
            logger.warning(f"Credit circuit breaker could not read the wallet for run {run.id}: {e}")
            return
        if spendable - billed <= 0:
            logger.warning(
                f"Credit exhausted mid-execution for run {run.id}: billed so far "
                f"${billed:.4f}, spendable ${spendable:.4f}. Stopping."
            )
            raise InsufficientCreditsError(
                f"Execution stopped: credit balance exhausted. Billed so far: ${billed:.4f}; "
                f"credit available to this run: ${max(spendable, Decimal('0')):.4f}. "
                f"Partial results saved. Please top up credits and retry."
            )

    async def check_child_credit_gate(
        self, company_id: UUID, parent_accumulated_cost: 'Decimal', child_entity_id: str = ""
    ) -> None:
        """Pre-spawn credit gate for child entities.

        Checks that the parent wallet still has credits remaining before
        launching a potentially expensive child entity. Raises
        InsufficientCreditsError if the wallet is drained.

        Phase 10E: Extracted from step_executor.py to route all billing
        through GovernanceService.
        """
        try:
            effective = await self.credit_service.get_effective_balance(
                company_id, parent_accumulated_cost
            )
            if effective <= 0:
                raise InsufficientCreditsError(
                    f"Cannot spawn child entity {child_entity_id}: parent run has accumulated "
                    f"${parent_accumulated_cost:.4f} cost with no remaining credits. "
                    f"Please top up credits and retry."
                )
            logger.info(
                f"Child run credit gate passed: ${effective:.4f} remaining "
                f"(parent accumulated: ${parent_accumulated_cost:.4f})"
            )
        except InsufficientCreditsError:
            raise
        except Exception as e:
            logger.warning(f"Child run credit gate check failed: {e}")

    # ------------------------------------------------------------------
    # TB Billing Settlement
    # ------------------------------------------------------------------

    async def settle_billing(
        self, run: 'ExecutionRun', entity_name: str
    ) -> Decimal:
        """
        Final billing settlement for top-level runs using TB formula.

        Computes billed amount, deducts remaining credits, and records
        the billing event. Returns the billed amount.
        """
        if run.parent_run_id:
            return Decimal("0")  # Only top-level runs settle
        try:
            return await self._settle(run, entity_name)
        finally:
            # The run is finished: its hold stops reserving credit (BC-06).
            try:
                await self.credit_service.release_hold(run.id)
            except Exception as e:
                logger.warning(f"Could not release the credit hold of run {run.id}: {e}")

    async def _settle(self, run: 'ExecutionRun', entity_name: str) -> Decimal:
        raw_cost = run.total_cost_usd
        logger.info(
            f"Final billing settlement for top-level run {run.id}. Total cost: {raw_cost}"
        )

        total_cost: Decimal = (
            Decimal(str(raw_cost)) if raw_cost is not None else Decimal("0")
        )

        if total_cost <= Decimal("0"):
            run.billed_amount = Decimal("0")
            logger.info(f"Run {run.id} cost is 0, no credits deducted.")
            return Decimal("0")

        try:
            # Compute billed amount using the TB formula
            config = await self.billing_service.get_billing_config(
                run.company_id
            )
            if not config:
                mf, pf, spf, d = Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0")
            else:
                mf = Decimal(str(config.multiplier_factor))
                pf = Decimal(str(config.platform_fee_pct))
                spf = Decimal(str(config.sales_partner_fee_pct))
                d = Decimal(str(config.discount_pct))

            tb_result = calculate_tb(total_cost, mf, pf, spf, d)
            billed_amount = tb_result["total_billing"]

            # Store billed amount on the run record
            run.billed_amount = billed_amount
            await self.db.commit()

            logger.info(
                f"TB formula: raw=${total_cost} → billed=${billed_amount} "
                f"(mf={mf}, pf={pf}, spf={spf}, d={d})"
            )

            # Final settlement: deduct whatever remains
            settlement = await self.credit_service.consume_incremental(
                run.company_id, billed_amount
            )
            if settlement["exhausted"]:
                logger.warning(
                    f"BILLING SHORTFALL for run {run.id}: "
                    f"billed=${billed_amount}, shortfall=${settlement['shortfall']:.4f}. "
                    f"Wallet drained to $0. Deducted: {settlement}"
                )
            else:
                logger.info(
                    f"Credits deducted for run {run.id}: {settlement} "
                    f"(billed: ${billed_amount})"
                )

            # Record billing event
            await self.billing_service.record_billing_event(
                company_id=run.company_id,
                base_cost=total_cost,
                grouping_type="process",
                grouping_value=entity_name,
                other_ai_cost=total_cost,
            )
            logger.info(
                f"Billing event recorded for run {run.id}: "
                f"raw=${total_cost}, billed=${billed_amount}"
            )
            return cast(Decimal, billed_amount)

        except Exception as billing_err:
            logger.warning(
                f"Billing/credit deduction failed for run {run.id}: {billing_err}"
            )
            return Decimal("0")

    # ------------------------------------------------------------------
    # HITL Checkpoint Evaluation
    # ------------------------------------------------------------------

    async def evaluate_hitl(
        self,
        run: 'ExecutionRun',
        entity: Any,
        step_obj: PlanStep,
        context_state: dict[str, Any],
        phase: str,  # "BEFORE" or "AFTER"
        governance_dict: Optional[dict[str, Any]] = None,
        step_result: Any = None,  # AFTER only: what the step produced
    ) -> None:
        """
        Evaluate HITL checkpoints defined in entity.governance.hitl_checkpoints.

        For each matching checkpoint:
        1. Create a HumanApproval record with PENDING status
        2. Publish HITL event to Redis for real-time notification
        3. Wait for approval/rejection via Redis pub/sub (with timeout)
        4. If rejected or timed out (without auto-approve), raise Exception
        """
        # Use pre-fetched governance dict to avoid MissingGreenlet after timeout
        governance = governance_dict if governance_dict is not None else (entity.governance or {})
        checkpoints_raw = governance.get("hitl_checkpoints", [])
        if not checkpoints_raw:
            return

        for cp_data in checkpoints_raw:
            try:
                cp = HITLCheckpoint(**cp_data) if isinstance(cp_data, dict) else cp_data
            except Exception:
                continue

            should_fire = False
            trigger_desc = ""

            if cp.trigger_type is HITLTriggerType.BEFORE_STEP and phase == "BEFORE":
                if cp.step_ref and (cp.step_ref == step_obj.name or cp.step_ref == step_obj.step_id):
                    should_fire = True
                    trigger_desc = f"BEFORE_STEP: {step_obj.name}"

            elif cp.trigger_type is HITLTriggerType.AFTER_STEP and phase == "AFTER":
                if cp.step_ref and (cp.step_ref == step_obj.name or cp.step_ref == step_obj.step_id):
                    should_fire = True
                    trigger_desc = f"AFTER_STEP: {step_obj.name}"

            elif cp.trigger_type is HITLTriggerType.COST_THRESHOLD and phase == "BEFORE":
                current_cost = float(run.total_cost_usd or 0)
                if cp.threshold and current_cost >= cp.threshold:
                    should_fire = True
                    trigger_desc = f"COST_THRESHOLD: ${current_cost:.4f} >= ${cp.threshold:.2f}"

            elif cp.trigger_type is HITLTriggerType.TOOL_CALL and phase == "BEFORE":
                if step_obj.type is StepType.TOOL_CALL and step_obj.target:
                    if cp.tool_ref and step_obj.target.tool_id == cp.tool_ref:
                        should_fire = True
                        trigger_desc = f"TOOL_CALL: {cp.tool_ref}"

            elif cp.trigger_type is HITLTriggerType.CUSTOM and phase == "BEFORE":
                if cp.expression:
                    try:
                        eval_result = self._safe_eval_expression(
                            cp.expression, run, context_state
                        )
                        if eval_result:
                            should_fire = True
                            trigger_desc = f"CUSTOM: {cp.expression}"
                    except Exception as e:
                        logger.warning(f"HITL custom expression eval failed: {e}")

            if not should_fire:
                continue

            # ── Fire the checkpoint ───────────────────────────────────────
            logger.info(f"HITL checkpoint fired: {trigger_desc} (run={run.id})")

            approval = HumanApproval(
                run_id=run.id,
                checkpoint_trigger=trigger_desc,
                status="PENDING",
                context_snapshot=build_hitl_snapshot(
                    checkpoint=cp, trigger_desc=trigger_desc, phase=phase,
                    entity=entity, step=step_obj, context_state=context_state,
                    run_cost_usd=run.total_cost_usd, step_result=step_result,
                ),
                notification_channels=cp.notification_channels,
                timeout_ms=cp.timeout_ms,
            )
            self.db.add(approval)
            await self.db.commit()
            await self.db.refresh(approval)

            # Real-time notice for the run's live view. Best-effort: the approval
            # row is the record, and the approvals page reads it.
            try:
                await self.redis.publish(f"execution:{run.id}", json.dumps({
                    "status": "HITL_PENDING",
                    "approval_id": str(approval.id),
                    "trigger": trigger_desc,
                    "message": cp.message or f"Human approval required: {trigger_desc}",
                }))
            except Exception as pub_err:
                logger.warning(f"HITL pending notice not published: {pub_err}")

            # ── Wait for the decision. Fails closed: nothing here lets the
            # step proceed without an APPROVED decision or auto-approve. ───
            decision = await self._await_hitl_decision(approval.id, cp.timeout_ms / 1000.0)

            if decision is None:
                # Time is up. Record TIMEOUT only if nobody answered in the
                # meantime; a decision that landed at the deadline wins.
                final = "APPROVED" if cp.auto_approve_on_timeout else "TIMEOUT"
                notes = "Auto-approved on timeout" if cp.auto_approve_on_timeout else None
                updated = await self.db.execute(
                    update(HumanApproval)
                    .where(HumanApproval.id == approval.id, HumanApproval.status == "PENDING")
                    .values(status=final, reviewer_notes=notes)
                )
                await self.db.commit()
                if updated.rowcount:
                    decision = final
                else:
                    decision = await self._read_hitl_status(approval.id)

            if decision == "APPROVED":
                logger.info(f"HITL approved: {trigger_desc}")
                continue
            if decision == "REJECTED":
                logger.info(f"HITL rejected: {trigger_desc}")
                raise Exception(f"Execution blocked by human reviewer: {trigger_desc}")
            logger.info(f"HITL timed out: {trigger_desc}")
            raise Exception(
                f"HITL checkpoint timed out after {cp.timeout_ms}ms: {trigger_desc}"
            )

    # The decisions a reviewer can record on an approval row.
    _HITL_DECISIONS = ("APPROVED", "REJECTED")

    async def _read_hitl_status(self, approval_id: UUID) -> Optional[str]:
        """The approval row's current status — a fresh read, not the identity map."""
        status: Optional[str] = (await self.db.execute(
            select(HumanApproval.status).where(HumanApproval.id == approval_id)
        )).scalar_one_or_none()
        return status

    async def _await_hitl_decision(self, approval_id: UUID, timeout_sec: float) -> Optional[str]:
        """Block until the approval is APPROVED or REJECTED; ``None`` at the deadline.

        The reviewer's answer is written to the approval row, then published on
        ``hitl:{approval_id}``. Pub/sub makes the wake-up immediate; the row is
        re-read every couple of seconds as well, so a Redis failure slows the
        wait down but never skips it.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec
        pubsub: Any = None
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(f"hitl:{approval_id}")
        except Exception as sub_err:
            logger.warning(f"HITL pub/sub unavailable ({sub_err}); waiting on the approval row")
            pubsub = None

        next_row_check = loop.time()
        try:
            while loop.time() < deadline:
                if pubsub is not None:
                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                    except Exception as msg_err:
                        logger.warning(f"HITL pub/sub dropped ({msg_err}); waiting on the approval row")
                        pubsub, message = None, None
                    if message and message.get("type") == "message":
                        published = str(json.loads(message["data"]).get("status", "")).upper()
                        if published in self._HITL_DECISIONS:
                            return published
                if loop.time() >= next_row_check:
                    stored = await self._read_hitl_status(approval_id)
                    if stored in self._HITL_DECISIONS:
                        return stored
                    next_row_check = loop.time() + 2.0
                await asyncio.sleep(0.5)
            return None
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(f"hitl:{approval_id}")
                    await pubsub.aclose()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # HITL Expression Evaluator
    # ------------------------------------------------------------------

    def _safe_eval_expression(
        self, expression: str, run: 'ExecutionRun', context_state: dict[str, Any]
    ) -> bool:
        """Safely evaluate a simple HITL custom expression.

        Supports: step_count > N, cost > N, has_key('X')
        Does NOT use eval() — parses manually for safety.
        """
        expression = expression.strip()
        try:
            if expression.startswith("step_count"):
                op, val = expression.split("step_count")[1].strip().split(None, 1)
                threshold = float(val)
                step_count = len([k for k in context_state if not k.startswith("__")])
                if op == ">" and step_count > threshold:
                    return True
                if op == ">=" and step_count >= threshold:
                    return True

            elif expression.startswith("cost"):
                op, val = expression.split("cost")[1].strip().split(None, 1)
                threshold = float(val)
                current_cost = float(run.total_cost_usd or 0)
                if op == ">" and current_cost > threshold:
                    return True
                if op == ">=" and current_cost >= threshold:
                    return True

            elif expression.startswith("has_key"):
                key = expression.split("(")[1].split(")")[0].strip("'\"")
                return key in context_state

        except Exception:
            pass
        return False
