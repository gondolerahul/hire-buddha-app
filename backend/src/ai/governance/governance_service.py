"""
governance_service.py — Billing, credit gating, and HITL approval logic.

Extracted from ExecutionEngine during Phase 6 monolith decomposition
(Step 3.1). Encapsulates all financial guardrails and human-in-the-loop
checkpoints so the engine can delegate without knowing billing internals.
"""
import json
import logging
from decimal import Decimal
from typing import Any, Optional, cast
from uuid import UUID

from sqlalchemy import select

from src.billing.credit_service import CreditService, InsufficientCreditsError, SpendCapReached, minimum_threshold
from src.billing.billing_service import BillingService, calculate_tb, compute_billed_amount
from src.ai.orm import HumanApproval, ExecutionRun
from src.ai.schemas import HITLCheckpoint, HITLTriggerType, StepType, PlanStep
from src.ai.schemas.governance import checkpoint_problem
from src.ai.schemas.hitl_expression import evaluate as evaluate_expression
from src.ai.governance.hitl_snapshot import build_hitl_snapshot
from src.ai.core.exceptions import HITLRejected, HITLTimeout
from src.ai.governance import hitl_gate

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
        them — and had no callers at all). A company at its monthly spend cap
        is refused first (``SpendCapReached``, GH-18).
        """
        await self.credit_service.check_spend_cap(run.company_id)
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
            # The company's monthly cap, counting this run's bill so far (GH-18).
            capped = await self.credit_service.spend_cap_refusal(run.company_id, pending=billed)
        except Exception as e:
            from src.common.gates import gate_failed
            gate_failed("credit_breaker", e, run_id=str(run.id), company_id=str(run.company_id))
            return
        if capped:
            logger.warning(f"Spend cap reached mid-execution for run {run.id}. Stopping.")
            raise SpendCapReached(f"Execution stopped: {capped} Partial results saved.")
        try:
            balance = await self.credit_service.get_balance(run.company_id)
            others = await self.credit_service.held_by_others(run.company_id, run.id)
            spendable = Decimal(str(balance["total_available"])) - others
        except Exception as e:
            from src.common.gates import gate_failed
            gate_failed("credit_breaker", e, run_id=str(run.id), company_id=str(run.company_id))
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

        A matching checkpoint never holds the worker (GH-07): it opens a
        PENDING ``HumanApproval``, publishes a notice, and raises
        ``HITLPending`` — the loop parks the run PAUSED. When the step is
        dispatched again the checkpoint finds that approval
        (``hitl_gate.open_approval``): APPROVED lets the step run, REJECTED
        raises ``HITLRejected`` and TIMEOUT ``HITLTimeout`` — the loop ends the
        run on either (GH-25) — and still PENDING parks the run again.
        """
        # Use pre-fetched governance dict to avoid MissingGreenlet after timeout
        governance = governance_dict if governance_dict is not None else (entity.governance or {})
        checkpoints_raw = governance.get("hitl_checkpoints", [])
        if not checkpoints_raw:
            return

        for index, cp_data in enumerate(checkpoints_raw, start=1):
            problem = checkpoint_problem(cp_data)
            cp = HITLCheckpoint.model_validate(cp_data) if not problem else self._stand_in(cp_data, problem)

            should_fire = False
            trigger_desc = ""
            run_cost: Any = run.total_cost_usd
            step_estimate: Optional[float] = None

            if problem:
                # A checkpoint that cannot be evaluated asks a person before
                # each step instead of letting the steps through (GH-09).
                # The entity API refuses one now; this is one stored before.
                if phase == "BEFORE":
                    should_fire = True
                    trigger_desc = f"UNUSABLE CHECKPOINT {index} before {step_obj.name}"[:255]
                    await self._report_unusable(run, index, problem)
            elif cp.trigger_type is HITLTriggerType.BEFORE_STEP and phase == "BEFORE":
                if cp.step_ref and (cp.step_ref == step_obj.name or cp.step_ref == step_obj.step_id):
                    should_fire = True
                    trigger_desc = f"BEFORE_STEP: {step_obj.name}"

            elif cp.trigger_type is HITLTriggerType.AFTER_STEP and phase == "AFTER":
                if cp.step_ref and (cp.step_ref == step_obj.name or cp.step_ref == step_obj.step_id):
                    should_fire = True
                    trigger_desc = f"AFTER_STEP: {step_obj.name}"

            elif cp.trigger_type is HITLTriggerType.COST_THRESHOLD and phase == "BEFORE":
                # Ask before the step that would cross the line, not after it
                # (GH-08): the run's spend so far plus this step's estimate.
                # Once over, every later step asks. The trigger names the
                # threshold and the step, not the spend, so a parked run's
                # step finds its approval again when it is dispatched.
                if cp.threshold:
                    from src.ai.planning.cost_estimator import estimate_step_cost
                    run_cost = await self._run_spend(run)
                    step_estimate = float(estimate_step_cost(step_obj, entity))
                    if run_cost + step_estimate >= cp.threshold:
                        should_fire = True
                        trigger_desc = f"COST_THRESHOLD: ${cp.threshold:.2f} before {step_obj.name}"

            elif cp.trigger_type is HITLTriggerType.TOOL_CALL and phase == "BEFORE":
                if step_obj.type is StepType.TOOL_CALL and step_obj.target:
                    if cp.tool_ref and step_obj.target.tool_id == cp.tool_ref:
                        should_fire = True
                        trigger_desc = f"TOOL_CALL: {cp.tool_ref}"

            elif cp.trigger_type is HITLTriggerType.CUSTOM and phase == "BEFORE":
                # The grammar is schemas/hitl_expression.py (GH-10); it parsed
                # above, so this cannot raise.
                cost = await self._run_spend(run) if "cost" in (cp.expression or "") else 0.0
                if evaluate_expression(
                    cp.expression or "", cost=cost, keys=context_state.keys(),
                    step_count=len([k for k in context_state if not k.startswith("__")]),
                ):
                    should_fire = True
                    trigger_desc = f"CUSTOM: {cp.expression}"[:255]

            if not should_fire:
                continue

            # ── The checkpoint's approval: a decision is used once ────────
            existing = await hitl_gate.open_approval(self.db, run.id, trigger_desc)
            if existing is not None and existing.status != "PENDING":
                await hitl_gate.consume(self.db, existing.id)
                if existing.status == "APPROVED":
                    logger.info(f"HITL approved: {trigger_desc}")
                    continue
                # A decision ends the run (GH-25, HD7).
                logger.info(f"HITL {existing.status.lower()}: {trigger_desc}")
                raise hitl_gate.decision_error(existing.status, trigger_desc, notes=existing.notes,
                                               timeout_ms=existing.timeout_ms or cp.timeout_ms,
                                               approval_id=existing.id)
            if existing is None:
                existing = await self._open_approval(
                    run, trigger_desc, cp.message or f"Human approval required: {trigger_desc}",
                    context_snapshot=build_hitl_snapshot(
                        checkpoint=cp, trigger_desc=trigger_desc, phase=phase,
                        entity=entity, step=step_obj, context_state=context_state,
                        run_cost_usd=run_cost, step_result=step_result,
                        step_cost_estimate_usd=step_estimate,
                    ),
                    timeout_ms=cp.timeout_ms, notification_channels=cp.notification_channels,
                )
            # Park: the run waits PAUSED, holding no worker (GH-07).
            raise hitl_gate.pending(existing, trigger=trigger_desc, phase=phase,
                                    step_id=str(step_obj.step_id or step_obj.name),
                                    auto_approve=cp.auto_approve_on_timeout)

    @staticmethod
    def _stand_in(raw: Any, problem: str) -> HITLCheckpoint:
        """The checkpoint a person is asked through when the configured one
        cannot be evaluated: its own timeout when it has a usable one."""
        timeout = raw.get("timeout_ms") if isinstance(raw, dict) else None
        return HITLCheckpoint(
            trigger_type=HITLTriggerType.CUSTOM,
            timeout_ms=timeout if isinstance(timeout, int) and timeout > 0 else 300000,
            message=(f"A HITL checkpoint of this entity cannot be evaluated ({problem}). "
                     "Approve to let the step run; fix the checkpoint in the entity's Safeguards."),
        )

    @staticmethod
    async def _report_unusable(run: 'ExecutionRun', index: int, problem: str) -> None:
        """On the run's trace and its event stream: which checkpoint, and why."""
        from src.ai.core.agent_loop_sse import event_async
        from src.ai.core.trace import span

        from src.common.gates import gate_failed

        gate_failed("hitl_checkpoint", problem, run_id=str(run.id), checkpoint=index)
        async with span("hitl", f"unusable checkpoint {index}", problem=problem) as handle:
            handle.set_error(problem)
        await event_async("agent.hitl.checkpoint_unusable", run_id=str(run.id),
                          checkpoint=index, problem=problem)

    async def _run_spend(self, run: 'ExecutionRun') -> float:
        """The run's spend now: its usage rows and its children's totals
        (AK-02). The run's own column moves only between iterations."""
        try:
            from src.ai.governance.run_cost import run_spend
            return float((await run_spend(self.db, run.id)).cost_usd)
        except Exception:
            logger.warning("Run spend unreadable for run %s; using the run's recorded cost", run.id)
            return float(run.total_cost_usd or 0)

    async def _open_approval(self, run: 'ExecutionRun', trigger: str, message: str, *,
                             context_snapshot: dict[str, Any], timeout_ms: int,
                             notification_channels: Any = None) -> 'hitl_gate.OpenApproval':
        """A PENDING approval for the inbox, and a notice on the run's live view."""
        logger.info(f"HITL checkpoint fired: {trigger} (run={run.id})")
        approval = HumanApproval(
            run_id=run.id, checkpoint_trigger=trigger, status="PENDING",
            context_snapshot=context_snapshot, notification_channels=notification_channels,
            timeout_ms=timeout_ms,
        )
        self.db.add(approval)
        await self.db.commit()
        await self.db.refresh(approval)
        # Best-effort: the approval row is the record, and the approvals page reads it.
        try:
            await self.redis.publish(f"execution:{run.id}", json.dumps({
                "status": "HITL_PENDING", "approval_id": str(approval.id),
                "trigger": trigger, "message": message,
            }))
        except Exception as pub_err:
            logger.warning(f"HITL pending notice not published: {pub_err}")
        return hitl_gate.OpenApproval(approval.id, "PENDING", "", timeout_ms, approval.requested_at)

    async def ask_user(self, run: 'ExecutionRun', step_obj: PlanStep, question: str,
                       *, timeout_ms: int = 300000) -> str:
        """Ask a person before a step runs again, and return the answer (PC-06).

        The critic chose ``ASK_USER``: the step needs something only a person
        can give. The question is a HITL request on the run (trigger
        ``ASK_USER``) and parks the run like a checkpoint (GH-07); the reviewer
        answers by approving it with notes. When the step is dispatched again
        the answer is returned. A refusal or an approval with no answer raises
        ``HITLRejected``, no answer in time ``HITLTimeout``: the step does not
        run again on a guess, and the run ends (GH-25).
        """
        trigger = f"ASK_USER: {step_obj.name}"[:255]
        existing = await hitl_gate.open_approval(self.db, run.id, trigger)
        if existing is not None and existing.status != "PENDING":
            await hitl_gate.consume(self.db, existing.id)
            if existing.status == "TIMEOUT":
                raise HITLTimeout(f"Nobody answered the question for step '{step_obj.name}' "
                                  f"within {timeout_ms // 1000}s: {question}", approval_id=str(existing.id))
            if existing.status != "APPROVED":
                raise HITLRejected(f"The reviewer declined to answer for step '{step_obj.name}'",
                                   approval_id=str(existing.id))
            if not existing.notes:
                raise HITLRejected(f"The reviewer approved step '{step_obj.name}' without an answer",
                                   approval_id=str(existing.id))
            return existing.notes
        if existing is None:
            existing = await self._open_approval(
                run, trigger, question,
                context_snapshot={"trigger": trigger, "phase": "BEFORE", "question": question,
                                  "step": {"name": step_obj.name, "step_id": step_obj.step_id,
                                           "description": step_obj.description}},
                timeout_ms=timeout_ms,
            )
        raise hitl_gate.pending(existing, trigger=trigger, phase="BEFORE",
                                step_id=str(step_obj.step_id or step_obj.name), auto_approve=False)
