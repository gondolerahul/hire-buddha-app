"""
governance_service.py — Billing, credit gating, and HITL approval logic.

Extracted from ExecutionEngine during Phase 6 monolith decomposition
(Step 3.1). Encapsulates all financial guardrails and human-in-the-loop
checkpoints so the engine can delegate without knowing billing internals.
"""
import logging
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

from src.billing.credit_service import CreditService, InsufficientCreditsError, SpendCapReached
from src.billing.billing_service import BillingService
from src.billing.formulas import formula_for_run
from src.ai.orm import HumanApproval, ExecutionRun
from src.ai.schemas import HITLCheckpoint, HITLTriggerType, StepType, PlanStep
from src.ai.schemas.governance import checkpoint_problem
from src.ai.schemas.hitl_expression import evaluate as evaluate_expression
from src.ai.governance.hitl_snapshot import build_hitl_snapshot
from src.ai.core.exceptions import HITLRejected, HITLTimeout
from src.ai.core.run_stream import publish_run_event
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
        """Admit a top-level run and hold its estimated bill (``estimate`` USD, §6.4).

        Refused — ``SpendCapReached`` (GH-18), ``WalletBlocked`` (the wallet is
        in debt or worse, §6.3) or InsufficientCreditsError (less than the
        level's ``admission.min_balance`` free) — before anything runs. Returns
        the amount held, in the wallet's currency. Errors reading the wallet
        propagate: a run whose credit cannot be checked does not start (BC-05).
        """
        from src.billing.settings_catalogue import min_balance

        await self.credit_service.check_spend_cap(run.company_id)
        floor = await min_balance(self.db, run.company_id, entity_type)
        held = await self.credit_service.place_hold(run.company_id, run.id, estimate, floor)
        logger.info(
            f"Credit gate passed for run {run.id}: holding {held:.4f} "
            f"(estimate ${estimate:.4f}, entity_type={entity_type})"
        )
        return held

    async def check_credit_circuit_breaker(
        self, run: 'ExecutionRun', accumulated_cost: Decimal,
    ) -> None:
        """Stop a run once its bill so far uses up what it may spend (§6.3).

        The bill is ``accumulated_cost`` (raw provider cost) through the
        formula — what settlement will charge. What the run may spend is the
        free credit (the wallet minus other work's holds) plus the wallet's
        negative tolerance, less any debt; a wallet over its tolerance or
        suspended stops every running run. Raises InsufficientCreditsError to
        stop; a failure to read the wallet is logged and the run continues
        (settlement still charges it).
        """
        from src.billing.wallet import money

        try:
            formula = await formula_for_run(self.db, run.company_id, run.id)
            billed = formula.rate(accumulated_cost)
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
            headroom, balance = await self.credit_service.headroom(run.company_id, run.id, billed)
        except Exception as e:
            from src.common.gates import gate_failed
            gate_failed("credit_breaker", e, run_id=str(run.id), company_id=str(run.company_id))
            return
        if headroom <= 0:
            currency = balance["currency"]
            logger.warning(
                f"Credit exhausted mid-execution for run {run.id}: billed so far ${billed:.4f}, "
                f"headroom {headroom:.4f} {currency}, wallet {balance['state']}. Stopping."
            )
            if balance["state"] in ("over_tolerance", "suspended") and balance.get("enforced", True):
                reason = f"the wallet owes {money(balance['debt'], currency)}, over its limit"
            else:
                reason = (f"credit balance exhausted (free {money(max(balance['free'], Decimal(0)), currency)}, "
                          f"billed so far ${billed:.4f})")
            raise InsufficientCreditsError(
                f"Execution stopped: {reason}. Partial results saved. Please top up credits and retry."
            )

    async def check_child_credit_gate(
        self, company_id: UUID, parent_accumulated_cost: 'Decimal', child_entity_id: str = "",
        *, run_id: Optional[UUID] = None,
    ) -> None:
        """Pre-spawn credit gate for child entities.

        A child does not start when the wallet is in debt or worse (§6.3), nor
        when the parent's bill so far (``parent_accumulated_cost`` through the
        formula) leaves the parent no headroom. Raises
        InsufficientCreditsError; an unreadable wallet is logged and the spawn
        goes ahead (the parent's breaker still watches it).
        """
        from src.billing.credit_service import state_refusal
        from src.billing.formulas import formula_for

        try:
            billed = (await formula_for(self.db, company_id)).rate(parent_accumulated_cost)
            headroom, balance = await self.credit_service.headroom(company_id, run_id, billed)
            refusal = state_refusal(balance)
            if refusal:
                raise InsufficientCreditsError(f"Cannot spawn child entity {child_entity_id}: {refusal}")
            if headroom <= 0:
                raise InsufficientCreditsError(
                    f"Cannot spawn child entity {child_entity_id}: the parent run has been billed "
                    f"${billed:.4f} with no credit left. Please top up credits and retry."
                )
            logger.info(f"Child run credit gate passed: {headroom:.4f} {balance['currency']} of headroom")
        except InsufficientCreditsError:
            raise
        except Exception as e:
            logger.warning(f"Child run credit gate check failed: {e}")

    # ------------------------------------------------------------------
    # Settlement (Phase 15 T3-5: src.billing.settlement)
    # ------------------------------------------------------------------

    async def settle_billing(
        self, run: 'ExecutionRun', entity_name: str
    ) -> Decimal:
        """Settle a finished top-level run: its usage rows and its descendants',
        charged once to the wallet (into debt if need be). Returns the billed
        amount (USD)."""
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
        """The control side of a settlement, in one control transaction (WS2
        2.6): claim the run's settlement, charge its rows, record the billing
        event — or nothing at all when the run was settled before. A failure
        leaves the rows unsettled for the hourly job (T3-6)."""
        from src.billing.enforcement import wallet_changed
        from src.billing.settlement import settle_run
        from src.common.tenancy.session import control_db_for

        try:
            async with control_db_for(self.db) as control:
                settled = await settle_run(self.db, control, run, grouping_type="entity",
                                           grouping_id=run.entity_id)
                if not settled.claimed:
                    # Nothing changed; with one database ``control`` is the
                    # run's own session, which a rollback would expire.
                    logger.warning(f"Run {run.id} is already settled; not charged again")
                    return Decimal("0")
                if settled.cost_usd > 0:
                    # Billing events stay for the reports until billing lines replace them (T3-8).
                    await BillingService(control).record_billing_event(
                        company_id=run.company_id, base_cost=settled.cost_usd, grouping_type="process",
                        grouping_value=entity_name, other_ai_cost=settled.cost_usd, commit=False)
                await control.commit()
                change = settled.change
            run.billed_amount = settled.billed_usd
            await self.db.commit()
        except Exception as billing_err:
            logger.warning(f"Settlement of run {run.id} failed (the hourly job retries it): {billing_err}")
            return Decimal("0")
        logger.info(f"Run {run.id} settled: {len(settled.rows)} rows, billed ${settled.billed_usd} "
                    f"= {settled.billed_ccy} {settled.currency}")
        await wallet_changed(self.db, run.company_id, change)
        return settled.billed_usd

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
        from src.automation.run_events import emit_approval

        await emit_approval(self.db, approval)  # approval.requested (W3-1)
        # Best-effort: the approval row is the record, and the approvals page reads it.
        try:
            await publish_run_event(self.redis, run.id, {
                "status": "HITL_PENDING", "approval_id": str(approval.id),
                "trigger": trigger, "message": message,
            })
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
