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

from src.billing.credit_service import CreditService, InsufficientCreditsError
from src.billing.billing_service import BillingService, calculate_tb
from src.ai.models import HumanApproval, ExecutionRun
from src.ai.schemas import HITLCheckpoint, HITLTriggerType, StepType, PlanStep

logger = logging.getLogger(__name__)


class GovernanceService:
    """Handles credit gates, HITL approvals, and billing settlement."""

    def __init__(self, db: Any, redis: Any) -> None:
        self.db = db
        self.redis = redis
        self.credit_service = CreditService(db)
        self.billing_service = BillingService(db)

    # ------------------------------------------------------------------
    # Credit Gate
    # ------------------------------------------------------------------

    async def check_credit_gate(
        self, company_id: UUID, entity_type: str, is_child: bool = False
    ) -> dict[str, Any]:
        """
        Pre-execution credit balance check.

        Returns the balance dict on success. Raises InsufficientCreditsError
        if the company cannot afford execution. Non-fatal DB errors are
        logged and swallowed so they don't block execution.
        """
        try:
            balance = await self.credit_service.check_sufficient_for_execution(
                company_id, entity_type
            )
            logger.info(
                f"Pre-execution credit check passed: ${balance['total_available']:.4f} available "
                f"(entity_type={entity_type}, is_child={is_child})"
            )
            return balance
        except InsufficientCreditsError:
            raise  # Re-raise to be caught by the outer handler
        except Exception as e:
            # Non-fatal: log and continue if balance check fails (e.g. DB issue)
            logger.warning(f"Pre-execution credit check failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # Incremental Billing
    # ------------------------------------------------------------------

    async def consume_step_cost(
        self, run: 'ExecutionRun', step_name: str, step_cost: Decimal
    ) -> dict[str, Any]:
        """
        Deduct a single step's cost from the company wallet immediately.

        Returns the consume result dict. Non-fatal errors are logged.
        """
        if step_cost <= 0:
            return {"deducted": Decimal("0"), "shortfall": Decimal("0"), "exhausted": False}

        try:
            result = await self.credit_service.consume_incremental(
                run.company_id, step_cost
            )
            logger.debug(
                f"Step '{step_name}' cost ${step_cost:.4f} deducted "
                f"(shortfall: ${result['shortfall']:.4f})"
            )
            return result
        except Exception as e:
            logger.warning(f"Incremental deduction failed for step '{step_name}': {e}")
            return {"deducted": Decimal("0"), "shortfall": step_cost, "exhausted": False}

    async def check_credit_circuit_breaker(
        self, run: 'ExecutionRun', step_name: str
    ) -> None:
        """
        Mid-execution credit circuit-breaker.

        Compares effective balance against accumulated costs. Raises
        InsufficientCreditsError if the wallet is drained.
        """
        try:
            accumulated = Decimal(str(run.total_cost_usd or 0))
            effective = await self.credit_service.get_effective_balance(
                run.company_id, accumulated
            )
            if effective <= 0:
                logger.warning(
                    f"Credit exhausted mid-execution after step '{step_name}'. "
                    f"Effective balance: ${effective:.4f} "
                    f"(accumulated cost: ${accumulated:.4f}). Stopping."
                )
                raise InsufficientCreditsError(
                    f"Execution stopped: credit balance exhausted after step '{step_name}'. "
                    f"Accumulated cost: ${accumulated:.4f}. "
                    f"Partial results saved. Please top up credits and retry."
                )
        except InsufficientCreditsError:
            raise
        except Exception:
            pass  # Non-fatal: continue if balance check fails

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
                context_snapshot={
                    "step_name": step_obj.name,
                    # SEC-3 fix: removed step_id to avoid exposing internal topology
                    "message": cp.message or f"Approval required: {trigger_desc}",
                },
                notification_channels=cp.notification_channels,
                timeout_ms=cp.timeout_ms,
            )
            self.db.add(approval)
            await self.db.commit()
            await self.db.refresh(approval)

            # Publish HITL event for real-time dashboard notification
            channel = f"execution:{run.id}"
            await self.redis.publish(channel, json.dumps({
                "status": "HITL_PENDING",
                "approval_id": str(approval.id),
                "trigger": trigger_desc,
                "message": cp.message or f"Human approval required: {trigger_desc}",
            }))

            # ── Wait for approval via Redis pub/sub ───────────────────────
            approval_channel = f"hitl:{approval.id}"
            timeout_sec = cp.timeout_ms / 1000.0

            try:
                pubsub = self.redis.client.pubsub()
                try:
                    await pubsub.subscribe(approval_channel)

                    deadline = asyncio.get_running_loop().time() + timeout_sec
                    resolved = False

                    while asyncio.get_running_loop().time() < deadline:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                        if message and message.get("type") == "message":
                            data = json.loads(message["data"])
                            status = data.get("status", "").upper()
                            if status == "APPROVED":
                                logger.info(f"HITL approved: {trigger_desc}")
                                resolved = True
                                break
                            elif status == "REJECTED":
                                logger.info(f"HITL rejected: {trigger_desc}")
                                approval.status = "REJECTED"
                                await self.db.commit()
                                raise Exception(
                                    f"Execution blocked by human reviewer: {trigger_desc}"
                                )
                        await asyncio.sleep(0.5)
                finally:
                    await pubsub.unsubscribe(approval_channel)

                if not resolved:
                    if cp.auto_approve_on_timeout:
                        logger.info(f"HITL auto-approved on timeout: {trigger_desc}")
                        approval.status = "APPROVED"
                        approval.reviewer_notes = "Auto-approved on timeout"
                    else:
                        logger.info(f"HITL timed out: {trigger_desc}")
                        approval.status = "TIMEOUT"
                        await self.db.commit()
                        raise Exception(
                            f"HITL checkpoint timed out after {cp.timeout_ms}ms: {trigger_desc}"
                        )
                    await self.db.commit()

            except Exception as hitl_err:
                if "Execution blocked" in str(hitl_err) or "timed out" in str(hitl_err):
                    raise
                logger.warning(f"HITL pub/sub error: {hitl_err}")
                # Non-fatal: continue execution if pub/sub fails

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
