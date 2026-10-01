from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_
from fastapi import HTTPException
from typing import Collection, Optional
from uuid import UUID, uuid4
import re
import logging
from src.common.job_queue import enqueue_job
from src.ai.models import (
    HierarchicalEntity, ExecutionRun, LLMInteractionLog, 
    ToolInteractionLog, HumanApproval, Document, EntityType
)
from src.ai.schemas import (
    HierarchicalEntityCreate, HierarchicalEntityUpdate, ExecutionRunCreate,
    ExecutionRefineRequest,
)
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Entity CRUD
    async def create_entity(self, entity_in: HierarchicalEntityCreate, company_id: UUID, user_id: UUID = None) -> HierarchicalEntity:
        # Prepare data, handling nested Pydantic models and ensuring JSON serializability (e.g. UUID -> str)
        entity_data = entity_in.model_dump(mode='json')
        
        # Templates are public — no company association
        effective_company_id = None if entity_data.get("is_template") else company_id

        from src.ai.governance.composition import EntityShape
        await self._require_composition(EntityShape(
            id=None, type=str(entity_data.get("type") or ""), company_id=effective_company_id,
            parent_id=entity_data.get("parent_id") and UUID(str(entity_data["parent_id"])),
            hierarchy=entity_data.get("hierarchy"), planning=entity_data.get("planning"),
            name=str(entity_data.get("name") or ""),
        ))

        # Flatten identity if provided as nested model to JSONB column
        entity = HierarchicalEntity(**entity_data, company_id=effective_company_id, created_by=user_id)
        self.db.add(entity)
        await self.db.commit()
        
        # Reload with relationships for schema
        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(HierarchicalEntity)
            .options(
                selectinload(HierarchicalEntity.execution_runs)
            )
            .where(HierarchicalEntity.id == entity.id)
        )
        return result.scalar_one()

    async def get_entities(self, company_ids: Optional[Collection[UUID]], type: EntityType = None, is_template: bool = None, voice_enabled: bool = None, status_filter: str = None) -> list[HierarchicalEntity]:
        """Entities of ``company_ids`` (``None``: every company) — see ``auth.visibility``."""
        from sqlalchemy.orm import selectinload
        query = select(HierarchicalEntity)

        # ── Always exclude soft-deleted entities from listings ──
        query = query.where(HierarchicalEntity.status != "DELETED")

        # Templates are public (company_id=NULL) — visible to everyone
        if is_template is True:
            query = query.where(HierarchicalEntity.is_template == True)
        else:
            if company_ids is not None:
                query = query.where(HierarchicalEntity.company_id.in_(company_ids))
            # Filter by template flag (None = show all, False = entities only)
            if is_template is not None:
                query = query.where(HierarchicalEntity.is_template == is_template)
        
        if type:
            query = query.where(HierarchicalEntity.type == type)
        
        if status_filter:
            query = query.where(HierarchicalEntity.status == status_filter)
        
        query = query.options(selectinload(HierarchicalEntity.execution_runs))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_entity(self, entity_id: UUID, company_id: UUID, user_role: str = None) -> HierarchicalEntity:
        from sqlalchemy.orm import selectinload
        query = select(HierarchicalEntity).options(selectinload(HierarchicalEntity.execution_runs))
        query = query.where(
            HierarchicalEntity.id == entity_id,
            HierarchicalEntity.status != "DELETED",  # Hide soft-deleted entities
        )
        
        # Access control: the companies the caller can see (auth.visibility —
        # app_admin all, partners own + tenants, others own), plus templates.
        from src.auth.visibility import company_scope
        scope = await company_scope(self.db, company_id, user_role)
        if scope is not None:
            from sqlalchemy import or_
            query = query.where(
                or_(
                    HierarchicalEntity.company_id.in_(scope),
                    HierarchicalEntity.is_template == True,
                )
            )
        
        result = await self.db.execute(query)
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
            
        return entity

    async def update_entity(self, entity_id: UUID, entity_in: HierarchicalEntityUpdate, company_id: UUID, user_role: str = None) -> HierarchicalEntity:
        entity = await self.get_entity(entity_id, company_id, user_role=user_role)
        
        update_data = entity_in.model_dump(mode='json', exclude_unset=True)

        # The edit is checked before it touches the row, so a refused one
        # leaves nothing to undo.
        from src.ai.governance.composition import EntityShape, status_transition_problem
        if "status" in update_data:
            refused = status_transition_problem(entity.status, update_data["status"])
            if refused:
                raise HTTPException(status_code=422, detail=f"Status: {refused}.")
        await self._require_composition(EntityShape.of(entity).with_changes(update_data))

        for field, value in update_data.items():
            setattr(entity, field, value)

        self.db.add(entity)
        await self.db.commit()
        await self.db.refresh(entity)
        return entity

    async def _require_composition(self, shape) -> None:
        """422 when the entity, as about to be written, breaks the composition
        rule (``ai.governance.composition``): a parent or child in another
        company, a child above its parent's level, or a cycle."""
        from src.ai.governance.composition import authoring_violations
        problems = await authoring_violations(self.db, shape)
        if problems:
            raise HTTPException(
                status_code=422,
                detail="Composition rule: " + "; ".join(problems) + ". A child sits at "
                       "its parent's level or below (ACTION < SKILL < AGENT < PROCESS "
                       "< LOOP < GRAPH), in the same company, with no cycle.",
            )

    async def delete_entity(self, entity_id: UUID, company_id: UUID):
        entity = await self.get_entity(entity_id, company_id)
        
        from sqlalchemy import update
        from src.ai.models import UsageLog
        
        # ── Collect the full entity tree (this entity + all descendants) ──
        # A PROCESS entity may have child entities (agents, skills) that
        # must also be soft-deleted to avoid orphans.
        async def _collect_entity_tree(eid: UUID, visited: set[UUID]) -> list[UUID]:
            if eid in visited:
                return []
            visited.add(eid)
            child_result = await self.db.execute(
                select(HierarchicalEntity.id).where(
                    HierarchicalEntity.parent_id == eid,
                    HierarchicalEntity.status != "DELETED",  # Skip already-deleted children
                )
            )
            child_ids = [r[0] for r in child_result.fetchall()]
            
            # Also check hierarchy.children JSON for referenced entities
            entity_result = await self.db.execute(
                select(HierarchicalEntity).where(HierarchicalEntity.id == eid)
            )
            entity_obj = entity_result.scalar_one_or_none()
            if entity_obj and entity_obj.hierarchy and isinstance(entity_obj.hierarchy, dict):
                for child_ref in entity_obj.hierarchy.get("children", []):
                    if isinstance(child_ref, dict):
                        child_id_str = child_ref.get("child_id")
                        if child_id_str:
                            try:
                                child_uuid = UUID(str(child_id_str))
                                if child_uuid not in visited:
                                    child_ids.append(child_uuid)
                            except (ValueError, AttributeError):
                                continue
            
            descendants = []
            for cid in child_ids:
                descendants.extend(await _collect_entity_tree(cid, visited))
            return [eid] + descendants

        all_entity_ids = await _collect_entity_tree(entity_id, set())
        logger.info(f"delete_entity: soft-deleting {len(all_entity_ids)} entities (root + descendants)")

        # ── SOFT-DELETE: Mark all entities as DELETED ──
        # The entity rows stay in the database so that execution_runs,
        # usage_logs, llm_interaction_logs, and all billing-critical data
        # retain valid FK references.
        now = datetime.utcnow()
        await self.db.execute(
            update(HierarchicalEntity)
            .where(HierarchicalEntity.id.in_(all_entity_ids))
            .values(
                status="DELETED",
                deleted_at=now,
                updated_at=now,
            )
        )

        # ── Sever live operational links (nullable FKs only) ──
        # These are references from operational tables that should no longer
        # point to a deleted entity, but where the FK is nullable.

        # Documents — unlink from entity. They become company-wide, so their
        # Knowledge Tree nodes move to the company tree with them; otherwise
        # they would stay in the deleted entity's tree, unreadable by any agent.
        from src.ai.models import Document
        from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
        doc_rows = (await self.db.execute(
            select(Document.id, Document.company_id).where(Document.entity_id.in_(all_entity_ids))
        )).all()
        for doc_id, doc_company_id in doc_rows:
            trees = KnowledgeTreeService(self.db, doc_company_id)
            await trees.move_document(doc_id, await trees.get_or_create_company_knowledge_tree())
        await self.db.execute(
            update(Document).where(Document.entity_id.in_(all_entity_ids)).values(entity_id=None)
        )
        
        # Other entities referencing this as template_source_id — nullify
        await self.db.execute(
            update(HierarchicalEntity)
            .where(HierarchicalEntity.template_source_id.in_(all_entity_ids))
            .values(template_source_id=None)
        )
        
        # Artifacts — nullify agent references (campaign_id points at campaigns, DM-18)
        try:
            from src.ai.artifact_models import Artifact, CallLog
            await self.db.execute(
                update(Artifact)
                .where(Artifact.agent_id.in_(all_entity_ids))
                .values(agent_id=None)
            )
            # Call logs — nullify agent reference
            await self.db.execute(
                update(CallLog)
                .where(CallLog.agent_id.in_(all_entity_ids))
                .values(agent_id=None)
            )
        except Exception as e:
            logger.debug(f"Artifact/CallLog cleanup skipped: {e}")
        
        # Phone numbers — unassign from deleted agent, revert to 'claimed'
        try:
            from src.voice.phone_pool_models import PhoneNumber
            await self.db.execute(
                update(PhoneNumber)
                .where(PhoneNumber.agent_id.in_(all_entity_ids))
                .values(agent_id=None, status="claimed", assigned_at=None)
            )
        except Exception as e:
            logger.debug(f"PhoneNumber cleanup skipped: {e}")

        # ── Billing-critical data is INTENTIONALLY preserved ──
        # execution_runs, usage_logs, llm_interaction_logs, tool_interaction_logs,
        # cortex_trees, voice_sessions, whatsapp_sessions,
        # conversation_history, campaigns, and lead_queue all retain valid FK
        # references to the soft-deleted entity rows.

        await self.db.commit()
        logger.info(f"delete_entity: successfully soft-deleted entity {entity_id} and {len(all_entity_ids)-1} children")

    # Execution
    async def trigger_execution(self, execution_in: ExecutionRunCreate, company_id: UUID, user_id: UUID = None, user_role: str = None) -> ExecutionRun:
        # Pre-flight: validate entity exists and belongs to this company
        entity = await self.get_entity(execution_in.entity_id, company_id, user_role=user_role)

        # Status (EP-09): an ARCHIVED entity does not run; a DEPRECATED one
        # runs and says so; a DRAFT runs on its own (a test run).
        status = str(getattr(entity.status, "value", entity.status) or "").upper()
        if status == "ARCHIVED":
            raise HTTPException(status_code=400, detail=f"Cannot execute '{entity.name}': it is ARCHIVED.")
        if status == "DEPRECATED":
            from src.ai.core.events import event
            event("agent.entity.deprecated_run", entity_id=str(entity.id), entity_name=entity.name)

        # Every level: the whole tree must satisfy the composition rule before
        # anything is spent — each invocation step resolves, every child is in
        # the entity's company, at its parent's level or below, with no cycle.
        entity_type_str = entity.type.value if hasattr(entity.type, 'value') else str(entity.type)
        from src.ai.governance.composition import dispatch_violations
        problems = await dispatch_violations(self.db, entity)
        if problems:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot execute '{entity.name}': {len(problems)} problem"
                    f"{'' if len(problems) == 1 else 's'} in its tree. If it came from a "
                    f"template, clone the complete template first.\n"
                    + "\n".join(f"  • {m}" for m in problems)
                ),
            )

        # 402 now rather than a run that fails in the worker: the run's own
        # credit gate (AgentLoop, BC-05) still decides, with its hold.
        from src.billing.credit_service import CreditService, minimum_threshold
        await CreditService(self.db).require_credits(company_id, minimum_threshold(entity_type_str))

        # Create Execution Record
        execution = ExecutionRun(
            company_id=company_id,
            user_id=user_id,
            entity_id=execution_in.entity_id,
            input_data=execution_in.input_data,
            status="PENDING",
            trace_id=uuid4() # Initialize root trace
        )
        self.db.add(execution)
        await self.db.commit()
        
        # Load relationships for response schema
        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.entity),
                selectinload(ExecutionRun.child_runs),
                selectinload(ExecutionRun.llm_logs),
                selectinload(ExecutionRun.tool_logs),
                selectinload(ExecutionRun.human_approvals)
            )
            .where(ExecutionRun.id == execution.id)
        )
        execution = result.scalar_one()

        # Enqueue Job to Arq
        await enqueue_job("run_execution_recursive", str(execution.id))

        return execution

    async def get_execution(self, execution_id: UUID, company_id: UUID, user_role: str = None) -> ExecutionRun:
        from sqlalchemy.orm import selectinload, joinedload
        
        # Load detailed trace with logs and approvals (up to 5 levels deep for deep research trees)
        query = select(ExecutionRun).options(
            joinedload(ExecutionRun.entity),
            selectinload(ExecutionRun.llm_logs),
            selectinload(ExecutionRun.tool_logs),
            selectinload(ExecutionRun.human_approvals),
            
            # Level 1 Child Runs
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.entity),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.llm_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.tool_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.human_approvals),
            
            # Level 2 Child Runs (Grandchildren)
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.entity),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.llm_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.tool_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.human_approvals),
            
            # Level 3 Child Runs (Great-grandchildren)
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.entity),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.llm_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.tool_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.human_approvals),

            # Level 4 Child Runs 
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.entity),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.llm_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.tool_logs),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.human_approvals),

            # Level 5 Child Runs (Final fallback)
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.entity),
            selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.child_runs).selectinload(ExecutionRun.llm_logs)
        )
        
        query = query.where(ExecutionRun.id == execution_id)
        
        # Platform administrators can view any execution across all companies
        if user_role != "app_admin":
            query = query.where(ExecutionRun.company_id == company_id)
        
        result = await self.db.execute(query)
        execution = result.scalar_one_or_none()
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
        return execution

    async def get_executions(self, company_id: UUID, user_role: str = None) -> list[ExecutionRun]:
        from sqlalchemy.orm import joinedload
        query = select(ExecutionRun).options(joinedload(ExecutionRun.entity))
        
        # Platform administrators can view all executions across all companies
        if user_role != "app_admin":
            query = query.where(ExecutionRun.company_id == company_id)
        
        query = query.where(ExecutionRun.parent_run_id.is_(None))  # Only show root executions in list
        query = query.order_by(ExecutionRun.created_at.desc())

        result = await self.db.execute(query)
        return result.scalars().all()

    async def record_csat(
        self,
        execution_id: UUID,
        company_id: UUID,
        score: int,
        comment: str = None,
        user_role: str = None,
    ) -> ExecutionRun:
        """Capture a +1/-1 CSAT rating on a completed run (Phase 12 `07` §6).

        Only finished runs can be rated. Access piggybacks on the same company
        scoping as ``get_execution``.
        """
        if score not in (1, -1):
            raise HTTPException(status_code=422, detail="csat score must be +1 or -1")

        query = select(ExecutionRun).where(ExecutionRun.id == execution_id)
        if user_role != "app_admin":
            query = query.where(ExecutionRun.company_id == company_id)
        result = await self.db.execute(query)
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Execution not found")
        if (run.status or "").upper() not in {"COMPLETED", "FAILED", "SUCCESS"}:
            raise HTTPException(status_code=409, detail="Run is not finished; cannot rate yet")

        run.csat_score = score
        run.csat_comment = (comment or None)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def cancel_execution(
        self, execution_id: UUID, company_id: UUID, user_role: str = None
    ) -> ExecutionRun:
        """Cooperatively cancel an in-flight run.

        Flips ``ExecutionRun.status`` to ``CANCELLED`` (a terminal state) and
        publishes a ``cancelled`` event on the ``execution:{id}`` Redis channel.
        The running AgentLoop re-reads the status at the top of each iteration
        (see ``AgentLoop._check_cancelled``) and aborts; legacy-engine runs that
        outlive the cancel simply settle as-is. Cancelling an already-terminal
        run is a no-op (returns the run unchanged) so a double-click can't error.
        """
        from sqlalchemy.orm import selectinload

        query = select(ExecutionRun).where(ExecutionRun.id == execution_id)
        if user_role != "app_admin":
            query = query.where(ExecutionRun.company_id == company_id)
        run = (await self.db.execute(query)).scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Execution not found")

        # One conditional UPDATE, so a run that finished meanwhile stays
        # finished: the WHERE is re-checked after any lock the finishing loop
        # holds, and then matches nothing (DM-17).
        from sqlalchemy import update

        from src.ai.schemas.enums import TERMINAL_RUN_STATUSES
        cancelled = (await self.db.execute(
            update(ExecutionRun)
            .where(ExecutionRun.id == run.id, ExecutionRun.status.notin_(TERMINAL_RUN_STATUSES))
            .values(status="CANCELLED", completed_at=datetime.utcnow())
            .execution_options(synchronize_session=False)
        )).rowcount
        await self.db.commit()
        if cancelled:
            # Notify any live SSE subscriber so the stream closes promptly. The
            # ``status`` key drives the stream generator's break condition.
            try:
                import json
                import redis.asyncio as redis_lib
                from src.common.config import settings
                r = redis_lib.from_url(settings.REDIS_URL or "redis://localhost:6379")
                await r.publish(
                    f"execution:{execution_id}",
                    json.dumps({"type": "cancelled", "status": "CANCELLED"}),
                )
                await r.close()
            except Exception:
                pass  # Non-fatal: the loop's own status re-read still aborts it.

        # Reload with relationships for the response schema.
        result = await self.db.execute(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.entity),
                selectinload(ExecutionRun.child_runs),
                selectinload(ExecutionRun.llm_logs),
                selectinload(ExecutionRun.tool_logs),
                selectinload(ExecutionRun.human_approvals),
            )
            .where(ExecutionRun.id == execution_id)
            .execution_options(populate_existing=True)  # the UPDATE bypassed the loaded run
        )
        return result.scalar_one()

    async def retry_execution(self, execution_id: UUID, company_id: UUID, user_id: UUID) -> ExecutionRun:
        """
        Create a new execution run that resumes from a FAILED run's state.
        
        The new run inherits:
          - entity_id and input_data from the failed run
          - the failed run's plan (``dynamic_plan``), and the outputs of the
            steps it finished, under ``__reuse_outputs__``: the loop marks
            those steps done and runs only the rest (EP-29)
          - cortex_tree_id from context_state (so the CORTEX tree is resumed)
          - retry_of_run_id pointing to the failed run (EP-03). It is a
            top-level run of its own — admitted, metered and settled — not a
            child of the run it repeats.
        """
        from sqlalchemy.orm import selectinload

        # 1. Load the failed run
        result = await self.db.execute(
            select(ExecutionRun).where(
                ExecutionRun.id == execution_id,
                ExecutionRun.company_id == company_id,
            )
        )
        failed_run = result.scalar_one_or_none()
        if not failed_run:
            raise HTTPException(status_code=404, detail="Execution not found")
        if failed_run.status not in ("FAILED", "COMPLETED"):
            raise HTTPException(status_code=400, detail=f"Only FAILED or COMPLETED runs can be retried (current: {failed_run.status})")

        # 2. Build input_data for the retry run.
        #    If the failed run had a CORTEX tree, pass its ID so the engine
        #    resumes the tree rather than creating a new one.
        retry_input = dict(failed_run.input_data or {})
        ctx = failed_run.context_state or {}
        if "__cortex_tree_id__" in ctx:
            retry_input["cortex_tree_id"] = ctx["__cortex_tree_id__"]
        from src.ai.core.step_results import REUSE_OUTPUTS_KEY
        finished = {
            str(s["step_id"]): s.get("output", "")
            for s in ((failed_run.result_data or {}).get("steps") or [])
            if isinstance(s, dict) and s.get("step_id") and not s.get("error")
        }
        if finished:
            retry_input[REUSE_OUTPUTS_KEY] = finished

        # 3. Create the retry run
        retry_run = ExecutionRun(
            company_id=company_id,
            user_id=user_id,
            entity_id=failed_run.entity_id,
            input_data=retry_input,
            context_state=ctx,
            # The same plan, so the finished steps' ids match (EP-29).
            dynamic_plan=failed_run.dynamic_plan,
            retry_of_run_id=failed_run.id,
            status="PENDING",
            trace_id=uuid4(),
        )
        self.db.add(retry_run)
        await self.db.commit()

        # 4. Reload with relationships for response
        result = await self.db.execute(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.entity),
                selectinload(ExecutionRun.child_runs),
                selectinload(ExecutionRun.llm_logs),
                selectinload(ExecutionRun.tool_logs),
                selectinload(ExecutionRun.human_approvals),
            )
            .where(ExecutionRun.id == retry_run.id)
        )
        retry_run = result.scalar_one()

        # 5. Enqueue to arq
        await enqueue_job("run_execution_recursive", str(retry_run.id))

        return retry_run

    async def refine_execution(
        self,
        execution_id: UUID,
        refine_in: 'ExecutionRefineRequest',
        company_id: UUID,
        user_id: UUID,
    ) -> ExecutionRun:
        """
        Refine a COMPLETED execution by analysing the user's feedback,
        determining which pipeline steps are affected, and creating a new
        run that reuses cached outputs for unchanged steps.
        """
        from sqlalchemy.orm import selectinload

        # 1. Load the original run
        result = await self.db.execute(
            select(ExecutionRun).where(
                ExecutionRun.id == execution_id,
                ExecutionRun.company_id == company_id,
            )
        )
        original_run = result.scalar_one_or_none()
        if not original_run:
            raise HTTPException(status_code=404, detail="Execution not found")
        if original_run.status != "COMPLETED":
            raise HTTPException(
                status_code=400,
                detail=f"Only COMPLETED runs can be refined (current: {original_run.status})",
            )

        # 2. Gather step information from the original run
        result_data = original_run.result_data or {}
        step_results = result_data.get("steps", [])
        ctx = original_run.context_state or {}

        # Resolve the entity to get the static plan
        entity_result = await self.db.execute(
            select(HierarchicalEntity).where(HierarchicalEntity.id == original_run.entity_id)
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found for this run")

        planning = entity.planning or {}
        static_steps = (planning.get("static_plan") or {}).get("steps", [])

        # 3. Use LLM to determine which steps need re-execution
        steps_to_rerun = await self._analyze_refinement_feedback(
            refine_in.feedback, static_steps, step_results, entity, company_id
        )

        # 4. Build reuse outputs and skip steps
        all_step_ids = [s.get("step_id", f"step_{i+1}") for i, s in enumerate(static_steps)]
        reuse_outputs: dict[str, str] = {}
        skip_steps: list[str] = []

        # Build a map of step_id -> output from the original run
        step_output_map: dict[str, str] = {}
        for sr in step_results:
            sid = sr.get("step_id") or sr.get("step", "")
            output = sr.get("output", "")
            step_output_map[sid] = output if isinstance(output, str) else json.dumps(output, default=str)

        # Also check context_state for step outputs (keyed by step name or step_id)
        for s in static_steps:
            sid = s.get("step_id", "")
            sname = s.get("name", "")
            if sid not in step_output_map:
                val = ctx.get(sname) or ctx.get(sid)
                if val:
                    step_output_map[sid] = val if isinstance(val, str) else json.dumps(val, default=str)

        # Determine which steps to skip vs re-run (including downstream cascade)
        rerun_set = set(steps_to_rerun)
        # Cascade: if a step is re-run, all downstream dependent steps must also re-run
        for i, s in enumerate(static_steps):
            sid = s.get("step_id", f"step_{i+1}")
            deps = (s.get("target") or {}).get("input_dependencies", [])
            if any(d in rerun_set for d in deps):
                rerun_set.add(sid)

        for sid in all_step_ids:
            if sid not in rerun_set and sid in step_output_map:
                skip_steps.append(sid)
                reuse_outputs[sid] = step_output_map[sid]

        logger.info(
            f"Refinement analysis: re-run={list(rerun_set)}, "
            f"skip={skip_steps}, feedback='{refine_in.feedback[:100]}'"
        )

        # 5. Build input_data for the refinement run
        refine_input = dict(original_run.input_data or {})
        refine_input["__refinement_feedback__"] = refine_in.feedback
        refine_input["__reuse_outputs__"] = reuse_outputs  # step_results.REUSE_OUTPUTS_KEY
        refine_input["__skip_steps__"] = skip_steps

        # Pass CORTEX tree ID for tree reuse
        if "__cortex_tree_id__" in ctx:
            refine_input["cortex_tree_id"] = ctx["__cortex_tree_id__"]

        # 6. Create the refinement run
        refine_run = ExecutionRun(
            company_id=company_id,
            user_id=user_id,
            entity_id=original_run.entity_id,
            input_data=refine_input,
            context_state={},  # Fresh context — reused outputs will be injected at execution time
            retry_of_run_id=original_run.id,
            status="PENDING",
            trace_id=uuid4(),
        )
        self.db.add(refine_run)
        await self.db.commit()

        # 7. Reload with relationships
        result = await self.db.execute(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.entity),
                selectinload(ExecutionRun.child_runs),
                selectinload(ExecutionRun.llm_logs),
                selectinload(ExecutionRun.tool_logs),
                selectinload(ExecutionRun.human_approvals),
            )
            .where(ExecutionRun.id == refine_run.id)
        )
        refine_run = result.scalar_one()

        # 8. Enqueue to arq
        await enqueue_job("run_execution_recursive", str(refine_run.id))

        return refine_run

    async def _analyze_refinement_feedback(
        self,
        feedback: str,
        static_steps: list[dict],
        step_results: list[dict],
        entity: HierarchicalEntity,
        company_id: UUID,
    ) -> list[str]:
        """
        Use a lightweight LLM call to determine which steps in the pipeline
        need re-execution based on the user's refinement feedback.
        
        Returns a list of step_ids that must be re-run.
        """
        # Build step summary for the LLM
        step_summaries = []
        for i, s in enumerate(static_steps):
            sid = s.get("step_id", f"step_{i+1}")
            name = s.get("name", f"Step {i+1}")
            desc = s.get("description", "")
            stype = s.get("type", "")
            deps = (s.get("target") or {}).get("input_dependencies", [])
            step_summaries.append(
                f"  {sid}: \"{name}\" (type={stype}) — {desc}"
                + (f" [depends on: {', '.join(deps)}]" if deps else "")
            )

        analysis_prompt = (
            f"You are analyzing a user's refinement request for a document generation pipeline.\n\n"
            f"PIPELINE STEPS:\n" + "\n".join(step_summaries) + "\n\n"
            f"USER FEEDBACK:\n\"{feedback}\"\n\n"
            f"RULES:\n"
            f"1. Return ONLY a JSON array of step_ids that MUST be re-executed.\n"
            f"2. Content/structure changes → re-run from the content planning step onward.\n"
            f"3. Visual/image changes → re-run from the visual asset step onward.\n"
            f"4. Formatting/rendering changes (fonts, layout, colors) → re-run from the rendering step onward.\n"
            f"5. If a step is re-run, ALL downstream steps that depend on it must ALSO be re-run.\n"
            f"6. When in doubt, err on the side of re-running more steps rather than fewer.\n\n"
            f"Return ONLY a JSON array, e.g. [\"step_3\", \"step_4\", \"step_5\"]\n"
        )

        try:
            from src.ai.llm.router import LLMRouter
            router = LLMRouter(self.db, company_id)
            response = await router.call_llm(
                task_type="text_generation",
                system_prompt="You are a pipeline analysis assistant. Output only valid JSON arrays.",
                user_prompt=analysis_prompt,
                temperature=0.1,
                max_tokens=256,
            )

            # Parse the JSON array from the response
            import re as _re
            # Extract JSON array from response (LLMResponse has .text attribute)
            text = response.text if hasattr(response, "text") else str(response)
            match = _re.search(r'\[.*?\]', text, _re.DOTALL)
            if match:
                step_ids = json.loads(match.group())
                if isinstance(step_ids, list):
                    # Validate step_ids against actual steps
                    valid_ids = {s.get("step_id", f"step_{i+1}") for i, s in enumerate(static_steps)}
                    return [sid for sid in step_ids if sid in valid_ids]
        except Exception as e:
            logger.warning(f"Refinement LLM analysis failed, falling back to full re-run: {e}")

        # Fallback: re-run all steps
        return [s.get("step_id", f"step_{i+1}") for i, s in enumerate(static_steps)]

    # HITL Management
    async def get_pending_approvals(self, company_id: UUID) -> list[HumanApproval]:
        result = await self.db.execute(
            select(HumanApproval)
            .where(HumanApproval.company_id == company_id, HumanApproval.status == "PENDING")
            .order_by(HumanApproval.requested_at.desc())
        )
        return result.scalars().all()

    async def respond_to_approval(
        self, approval_id: UUID, status: str, user_id: UUID, notes: str = None, *, company_id: UUID,
    ) -> HumanApproval:
        """Record a reviewer's decision on one of the company's pending approvals.

        Scoped like ``get_pending_approvals``: by the approval's company. Only a
        PENDING approval can be answered, once — the conditional UPDATE makes a
        second answer, or an answer after the worker timed out, a 409.
        """
        from sqlalchemy import update

        approval = (await self.db.execute(
            select(HumanApproval).where(HumanApproval.id == approval_id, HumanApproval.company_id == company_id)
        )).scalar_one_or_none()
        if not approval:
            raise HTTPException(status_code=404, detail="Approval request not found")

        answered = await self.db.execute(
            update(HumanApproval)
            .where(HumanApproval.id == approval_id, HumanApproval.status == "PENDING")
            .values(status=status, responded_by=user_id,
                    responded_at=datetime.utcnow(), reviewer_notes=notes)
        )
        if not answered.rowcount:
            current = (await self.db.execute(
                select(HumanApproval.status).where(HumanApproval.id == approval_id)
            )).scalar_one_or_none()
            raise HTTPException(status_code=409, detail=f"This approval is already {current}")
        await self.db.commit()
        await self.db.refresh(approval)
        # The router publishes the decision on "hitl:{approval_id}", the channel
        # GovernanceService waits on (it also re-reads this row).
        return approval

    async def get_dashboard_stats(self, company_id: UUID, user_role: str = None) -> dict:
        # Platform administrators can view stats across all companies
        if user_role == "app_admin":
            # Active Entities count (all companies)
            entities_count = await self.db.execute(
                select(func.count(HierarchicalEntity.id))
            )
            
            # Executions count (today, all companies)
            today = datetime.utcnow().date()  # created_at is UTC (DM-12)
            executions_count = await self.db.execute(
                select(func.count(ExecutionRun.id))
                .where(func.date(ExecutionRun.created_at) == today)
            )
            
            # Documents count (all companies)
            documents_count = await self.db.execute(select(func.count(Document.id)))
        else:
            # Active Entities count
            entities_count = await self.db.execute(
                select(func.count(HierarchicalEntity.id))
                .where(HierarchicalEntity.company_id == company_id)
            )
            
            # Executions count (today)
            today = datetime.utcnow().date()  # created_at is UTC (DM-12)
            executions_count = await self.db.execute(
                select(func.count(ExecutionRun.id))
                .where(ExecutionRun.company_id == company_id)
                .where(func.date(ExecutionRun.created_at) == today)
            )
            
            # Documents count
            documents_count = await self.db.execute(select(func.count(Document.id)).where(Document.company_id == company_id))
        
        return {
            "entities_total": entities_count.scalar() or 0,
            "executions_today": executions_count.scalar() or 0,
            "documents_total": documents_count.scalar() or 0
        }

    # Document & RAG Methods — see ai/services/knowledge_base.py
    async def upload_document(self, file_content: bytes, filename: str, file_type: str, company_id: UUID, entity_id: UUID = None):
        from src.ai.services.knowledge_base import KnowledgeBaseService
        return await KnowledgeBaseService(self.db, company_id).upload(
            file_content, filename, file_type, entity_id=entity_id,
        )

    async def search_documents(self, query: str, company_id: UUID, entity_id: UUID = None, top_k: int = 5):
        """Semantic search over the company's documents (their Knowledge Tree chunks)."""
        from src.ai.services.knowledge_base import KnowledgeBaseService
        return await KnowledgeBaseService(self.db, company_id).search(query, entity_id=entity_id, top_k=top_k)

    async def get_documents(self, company_id: UUID, entity_id: UUID = None):
        from src.ai.services.knowledge_base import KnowledgeBaseService
        return await KnowledgeBaseService(self.db, company_id).list(entity_id)

    # ── Template Management ────────────────────────────────────────────────

    async def _collect_tree(self, root: HierarchicalEntity, scope) -> list[HierarchicalEntity]:
        """Every descendant of ``root`` within ``scope``, parents before children.

        A child is found the three ways an entity names one: a row whose
        ``parent_id`` is the entity, ``hierarchy.children``, and the target of a
        static-plan CHILD_ENTITY_INVOCATION (``composition.child_references``).
        Template conversion walked only the first two, so a child named only by
        a plan step was left out of every template made from it (EP-19).
        """
        from src.ai.governance.composition import child_references

        visited: set[UUID] = {root.id}
        ordered: list[HierarchicalEntity] = []
        queue = [root]
        while queue:
            entity = queue.pop(0)
            found = list((await self.db.execute(
                select(HierarchicalEntity).where(HierarchicalEntity.parent_id == entity.id, scope)
            )).scalars().all())
            for ref in child_references(entity.hierarchy, entity.planning):
                if ref.entity_id is None or ref.entity_id in visited:
                    continue
                child = (await self.db.execute(
                    select(HierarchicalEntity).where(HierarchicalEntity.id == ref.entity_id, scope)
                )).scalar_one_or_none()
                if child is not None:
                    found.append(child)
            for child in found:
                if child.id not in visited:
                    visited.add(child.id)
                    ordered.append(child)
                    queue.append(child)
        return ordered

    async def convert_to_template(self, entity_id: UUID, company_id: UUID, user_id: UUID) -> HierarchicalEntity:
        """
        Deep-clone an existing entity (and all its children) into a parallel
        template hierarchy (is_template=True).  The originals are left untouched.
        """
        from sqlalchemy.orm import selectinload

        # 1. Load the source entity
        result = await self.db.execute(
            select(HierarchicalEntity)
            .options(selectinload(HierarchicalEntity.execution_runs))
            .where(
                HierarchicalEntity.id == entity_id,
                HierarchicalEntity.company_id == company_id,
            )
        )
        source = result.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail="Entity not found")
        if source.is_template:
            raise HTTPException(status_code=400, detail="Entity is already a template")

        # 2. Every descendant, found the three ways an entity names a child (EP-19).
        all_children = await self._collect_tree(source, HierarchicalEntity.company_id == company_id)

        # 3. Clone fields helper
        old_to_new_id: dict[UUID, UUID] = {}

        from src.ai.entity_clone_helpers import clone_entity_fields, remap_entity_refs
        _clone_fields = clone_entity_fields

        # 4. Clone root as template
        root_template = HierarchicalEntity(
            **_clone_fields(source),
            company_id=source.company_id,
            created_by=user_id,
            is_template=True,
            template_source_id=source.id,
            parent_id=None,
        )
        self.db.add(root_template)
        await self.db.flush()
        old_to_new_id[source.id] = root_template.id

        # 5. Clone children in topological order
        for child in all_children:
            new_parent_id = old_to_new_id.get(child.parent_id)
            clone = HierarchicalEntity(
                **_clone_fields(child),
                company_id=source.company_id,
                created_by=user_id,
                is_template=True,
                template_source_id=child.id,
                parent_id=new_parent_id,
            )
            self.db.add(clone)
            await self.db.flush()
            old_to_new_id[child.id] = clone.id

        # 6. Remap internal entity_id references (same logic as clone_template)
        def _remap_entity_refs_wrapper(entity: HierarchicalEntity) -> bool:
            return remap_entity_refs(entity, old_to_new_id)

        all_cloned = [root_template] + [
            (await self.db.execute(
                select(HierarchicalEntity).where(HierarchicalEntity.id == new_id)
            )).scalar_one()
            for new_id in list(old_to_new_id.values())[1:]
        ]
        for cloned_entity in all_cloned:
            if _remap_entity_refs_wrapper(cloned_entity):
                self.db.add(cloned_entity)

        await self.db.commit()

        # 7. Reload with relationships
        result = await self.db.execute(
            select(HierarchicalEntity)
            .options(selectinload(HierarchicalEntity.execution_runs))
            .where(HierarchicalEntity.id == root_template.id)
        )
        return result.scalar_one()

    async def clone_template(self, template_id: UUID, company_id: UUID, user_id: UUID) -> HierarchicalEntity:
        """
        Deep-clone a template entity (and all its children) into executable
        entities owned by the requesting company/user.
        """
        from sqlalchemy.orm import selectinload

        # 1. Load the template
        result = await self.db.execute(
            select(HierarchicalEntity)
            .options(selectinload(HierarchicalEntity.execution_runs))
            .where(
                HierarchicalEntity.id == template_id,
                HierarchicalEntity.is_template == True,
            )
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # 2. Every descendant template, found the three ways an entity names a child.
        all_children = await self._collect_tree(template, HierarchicalEntity.is_template == True)
        logger.info(
            f"clone_template: discovered {len(all_children)} child entities "
            f"for template '{template.name}' (id={template.id})"
        )

        # 3. Clone root template
        old_to_new_id: dict[UUID, UUID] = {}

        from src.ai.entity_clone_helpers import clone_entity_fields, remap_entity_refs
        _clone_fields = clone_entity_fields

        root_clone = HierarchicalEntity(
            **_clone_fields(template),
            company_id=company_id,
            created_by=user_id,
            is_template=False,
            template_source_id=template.id,
            parent_id=None,
        )
        self.db.add(root_clone)
        await self.db.flush()  # get root_clone.id assigned
        old_to_new_id[template.id] = root_clone.id

        # Auto-populate io_contract.input_schema from prompt template variables
        self._auto_generate_input_schema(root_clone)

        # 4. Clone children in topological order (parent before child)
        for child in all_children:
            new_parent_id = old_to_new_id.get(child.parent_id)
            clone = HierarchicalEntity(
                **_clone_fields(child),
                company_id=company_id,
                created_by=user_id,
                is_template=False,
                template_source_id=child.id,
                parent_id=new_parent_id,
            )
            self.db.add(clone)
            await self.db.flush()
            old_to_new_id[child.id] = clone.id

        # 5. Post-clone: remap internal entity_id references using old_to_new_id
        from sqlalchemy.orm.attributes import flag_modified

        logger.info(
            f"clone_template: old_to_new_id mapping ({len(old_to_new_id)} entries): "
            + ", ".join(f"{str(k)[:8]}→{str(v)[:8]}" for k, v in old_to_new_id.items())
        )

        # Apply remapping to every cloned entity
        # We must reload each clone from DB to get the flushed state,
        # then apply remap on independent copies of the JSON data.
        all_cloned = [root_clone]
        for new_id in list(old_to_new_id.values())[1:]:  # skip root_clone
            result = await self.db.execute(
                select(HierarchicalEntity).where(HierarchicalEntity.id == new_id)
            )
            all_cloned.append(result.scalar_one())

        for cloned_entity in all_cloned:
            was_modified = remap_entity_refs(cloned_entity, old_to_new_id)
            logger.info(
                f"clone_template: remap '{cloned_entity.name}' (id={str(cloned_entity.id)[:8]}..): "
                f"modified={was_modified}"
            )
            if was_modified:
                flag_modified(cloned_entity, "planning")
                flag_modified(cloned_entity, "hierarchy")
                self.db.add(cloned_entity)

        await self.db.commit()

        # 6. Reload with relationships
        result = await self.db.execute(
            select(HierarchicalEntity)
            .options(selectinload(HierarchicalEntity.execution_runs))
            .where(HierarchicalEntity.id == root_clone.id)
        )

        logger.info(
            f"clone_template: successfully cloned template '{template.name}' → "
            f"'{root_clone.name}' (root={root_clone.id}, children={len(all_children)})"
        )
        return result.scalar_one()

    @staticmethod
    def _auto_generate_input_schema(entity: HierarchicalEntity) -> None:
        """
        Scan prompt templates in the entity's static plan for {{variable}}
        placeholders and auto-populate io_contract.input_schema if it is
        empty.  Skips internal step references (step_1, step_2, etc.) and
        system variables (__cortex_tree_id__, etc.).

        Also scans the entity's goal field for {{variable}} patterns.
        """
        io_contract = entity.io_contract or {}
        input_schema = io_contract.get("input_schema") or {}
        existing_props = input_schema.get("properties") or {}

        # If io_contract already has properties defined, don't override
        if existing_props:
            return

        # Scan all prompt templates in the static plan
        planning = entity.planning or {}
        static_steps = (planning.get("static_plan") or {}).get("steps", [])

        discovered_vars: set[str] = set()
        step_ref_pattern = re.compile(r'^step_\d+')

        for step in static_steps:
            prompt = (step.get("target") or {}).get("prompt_template", "")
            if isinstance(prompt, dict):
                prompt = json.dumps(prompt, default=str)
            if not isinstance(prompt, str):
                continue

            for match in re.finditer(r'\{\{(\w+)\}\}', prompt):
                var_name = match.group(1)
                # Skip internal step references and system variables
                if not step_ref_pattern.match(var_name) and not var_name.startswith("__"):
                    discovered_vars.add(var_name)

        # Also scan the entity's goal for variables
        if entity.goal:
            for match in re.finditer(r'\{\{(\w+)\}\}', entity.goal):
                var_name = match.group(1)
                if not step_ref_pattern.match(var_name) and not var_name.startswith("__"):
                    discovered_vars.add(var_name)

        if discovered_vars:
            properties = {
                var: {"type": "string", "description": var.replace("_", " ").title()}
                for var in sorted(discovered_vars)
            }
            entity.io_contract = {
                **io_contract,
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(sorted(discovered_vars)),
                },
            }
            logger.info(
                f"Auto-generated input_schema for entity '{entity.name}' "
                f"with variables: {sorted(discovered_vars)}"
            )
