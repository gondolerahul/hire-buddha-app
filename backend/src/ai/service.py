from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_
from fastapi import HTTPException
from uuid import UUID, uuid4
from arq import create_pool
import re
import logging
from arq.connections import RedisSettings
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

    async def get_entities(self, company_id: UUID, type: EntityType = None, user_role: str = None, is_template: bool = None, voice_enabled: bool = None, status_filter: str = None) -> list[HierarchicalEntity]:
        from sqlalchemy.orm import selectinload
        query = select(HierarchicalEntity)
        
        # ── Always exclude soft-deleted entities from listings ──
        query = query.where(HierarchicalEntity.status != "DELETED")
        
        # Templates are public (company_id=NULL) — visible to everyone
        if is_template is True:
            query = query.where(HierarchicalEntity.is_template == True)
        else:
            # For regular entities, scope by company (app_admin sees all)
            if user_role != "app_admin":
                query = query.where(HierarchicalEntity.company_id == company_id)
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
        
        # Access control:
        #   app_admin        → can access any entity
        #   partner_admin/user → own company + child tenant companies + templates
        #   tenant_admin/user  → own company + templates
        if user_role == "app_admin":
            pass  # No company filter
        elif user_role in ("partner_admin", "partner_user"):
            from sqlalchemy import or_
            from src.auth.models import Company
            # Fetch child tenant company IDs for this partner
            child_result = await self.db.execute(
                select(Company.id).where(Company.parent_id == company_id)
            )
            child_ids = [row[0] for row in child_result.fetchall()]
            allowed_ids = [company_id] + child_ids
            query = query.where(
                or_(
                    HierarchicalEntity.company_id.in_(allowed_ids),
                    HierarchicalEntity.is_template == True,
                )
            )
        else:
            from sqlalchemy import or_
            query = query.where(
                or_(
                    HierarchicalEntity.company_id == company_id,
                    HierarchicalEntity.is_template == True,
                )
            )
        
        result = await self.db.execute(query)
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
            
        # Ensure Actions/Skills have at least one step in their plan for the UI to correctly display inputs
        # This is a virtual fallback for UI purposes when no explicit steps are defined
        if entity.type in [EntityType.ACTION, EntityType.SKILL]:
            planning = entity.planning or {}
            static_plan = planning.get("static_plan", {})
            if not static_plan or not static_plan.get("steps"):
                # Construct a virtual plan with a default step
                virtual_planning = planning.copy()
                virtual_planning["static_plan"] = {
                    "enabled": True,
                    "steps": [{
                        "step_id": "default_execute",
                        "name": "Execute",
                        "type": "ACTION",
                        "target": {
                            "prompt_template": entity.description or "Process instruction: {{instruction}}"
                        },
                        "required": True
                    }]
                }
                entity.planning = virtual_planning
                
        return entity

    async def update_entity(self, entity_id: UUID, entity_in: HierarchicalEntityUpdate, company_id: UUID, user_role: str = None) -> HierarchicalEntity:
        entity = await self.get_entity(entity_id, company_id, user_role=user_role)
        
        update_data = entity_in.model_dump(mode='json', exclude_unset=True)
        for field, value in update_data.items():
            setattr(entity, field, value)
            
        self.db.add(entity)
        await self.db.commit()
        await self.db.refresh(entity)
        return entity

    async def delete_entity(self, entity_id: UUID, company_id: UUID):
        entity = await self.get_entity(entity_id, company_id)
        
        from sqlalchemy import update
        from src.ai.models import UsageLog, EpisodicMemory
        
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

        # Documents — unlink from entity
        from src.ai.models import Document
        await self.db.execute(
            update(Document).where(Document.entity_id.in_(all_entity_ids)).values(entity_id=None)
        )
        
        # Other entities referencing this as template_source_id — nullify
        await self.db.execute(
            update(HierarchicalEntity)
            .where(HierarchicalEntity.template_source_id.in_(all_entity_ids))
            .values(template_source_id=None)
        )
        
        # Artifacts — nullify agent/campaign references
        try:
            from src.ai.artifact_models import Artifact, CallLog
            await self.db.execute(
                update(Artifact)
                .where(Artifact.agent_id.in_(all_entity_ids))
                .values(agent_id=None)
            )
            await self.db.execute(
                update(Artifact)
                .where(Artifact.campaign_id.in_(all_entity_ids))
                .values(campaign_id=None)
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
        # episodic_memories, cortex_trees, voice_sessions, whatsapp_sessions,
        # conversation_history, campaigns, and lead_queue all retain valid FK
        # references to the soft-deleted entity rows.

        await self.db.commit()
        logger.info(f"delete_entity: successfully soft-deleted entity {entity_id} and {len(all_entity_ids)-1} children")

    # Execution
    async def trigger_execution(self, execution_in: ExecutionRunCreate, company_id: UUID, user_id: UUID = None, user_role: str = None) -> ExecutionRun:
        # Pre-flight: validate entity exists and belongs to this company
        entity = await self.get_entity(execution_in.entity_id, company_id, user_role=user_role)

        # For PROCESS entities, validate all child entity references exist
        # within the executing company before allowing execution.
        entity_type_str = entity.type.value if hasattr(entity.type, 'value') else str(entity.type)
        if entity_type_str == "PROCESS":
            await self._validate_process_children(entity, company_id, user_role=user_role)

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
        redis = await create_pool(RedisSettings())
        await redis.enqueue_job('run_execution_recursive', str(execution.id))
        await redis.close()

        return execution

    async def _validate_process_children(self, entity: HierarchicalEntity, company_id: UUID, user_role: str = None) -> None:
        """
        Pre-flight check: verify all CHILD_ENTITY_INVOCATION targets exist
        within the executing company.  Raises HTTP 400 if any are missing,
        blocking the entire execution with a descriptive error.
        """
        planning = entity.planning or {}
        static_steps = (planning.get("static_plan") or {}).get("steps", [])

        missing: list[str] = []
        for step in static_steps:
            if step.get("type") != "CHILD_ENTITY_INVOCATION":
                continue
            target_id = (step.get("target") or {}).get("entity_id")
            if not target_id:
                missing.append(f"Step '{step.get('name', '?')}' has no entity_id configured")
                continue
            try:
                child_uuid = UUID(str(target_id))
            except (ValueError, AttributeError):
                missing.append(f"Step '{step.get('name', '?')}' has invalid entity_id '{target_id}'")
                continue
            query = select(HierarchicalEntity.id).where(
                HierarchicalEntity.id == child_uuid,
            )
            # app_admin can reference entities from any company
            if user_role != "app_admin":
                query = query.where(HierarchicalEntity.company_id == company_id)
            result = await self.db.execute(query)
            if not result.scalar_one_or_none():
                missing.append(
                    f"Step '{step.get('name', '?')}' references entity {target_id} "
                    f"which does not exist in your company"
                )

        # Also check hierarchy.children for referenced entities
        hierarchy = entity.hierarchy
        if hierarchy and isinstance(hierarchy, dict):
            for child_ref in hierarchy.get("children", []):
                if isinstance(child_ref, dict):
                    child_id_str = child_ref.get("child_id")
                    if child_id_str:
                        try:
                            child_uuid = UUID(str(child_id_str))
                        except (ValueError, AttributeError):
                            continue
                        result = await self.db.execute(
                            select(HierarchicalEntity.id).where(
                                HierarchicalEntity.id == child_uuid,
                            ) if user_role == "app_admin" else
                            select(HierarchicalEntity.id).where(
                                HierarchicalEntity.id == child_uuid,
                                HierarchicalEntity.company_id == company_id,
                            )
                        )
                        if not result.scalar_one_or_none():
                            child_type = child_ref.get("child_type", "unknown")
                            missing.append(
                                f"Hierarchy child ({child_type}) references entity {child_id_str} "
                                f"which does not exist in your company"
                            )

        if missing:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot execute process '{entity.name}': {len(missing)} child "
                    f"entit{'y' if len(missing) == 1 else 'ies'} not found in your company. "
                    f"Please clone the complete template first.\n"
                    + "\n".join(f"  • {m}" for m in missing)
                ),
            )

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

        terminal = {"COMPLETED", "FAILED", "PARTIAL_COMPLETE", "CANCELLED"}
        if str(run.status) not in terminal:
            from datetime import datetime
            run.status = "CANCELLED"
            run.completed_at = datetime.utcnow()
            await self.db.commit()

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
        )
        return result.scalar_one()

    async def retry_execution(self, execution_id: UUID, company_id: UUID, user_id: UUID) -> ExecutionRun:
        """
        Create a new execution run that resumes from a FAILED run's state.
        
        The new run inherits:
          - entity_id and input_data from the failed run
          - context_state with completed step IDs (so they are skipped)
          - cortex_tree_id from context_state (so the CORTEX tree is resumed)
          - parent_run_id pointing to the failed run for traceability
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

        # 3. Create the retry run
        retry_run = ExecutionRun(
            company_id=company_id,
            user_id=user_id,
            entity_id=failed_run.entity_id,
            input_data=retry_input,
            context_state=ctx,  # Carry forward completed step markers
            parent_run_id=failed_run.id,  # Link for traceability
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
        redis = await create_pool(RedisSettings())
        await redis.enqueue_job("run_execution_recursive", str(retry_run.id))
        await redis.close()

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
        refine_input["__reuse_outputs__"] = reuse_outputs
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
            parent_run_id=original_run.id,
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
        redis = await create_pool(RedisSettings())
        await redis.enqueue_job("run_execution_recursive", str(refine_run.id))
        await redis.close()

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
            .join(ExecutionRun)
            .where(ExecutionRun.company_id == company_id, HumanApproval.status == "PENDING")
            .order_by(HumanApproval.requested_at.desc())
        )
        return result.scalars().all()

    async def respond_to_approval(self, approval_id: UUID, status: str, user_id: UUID, notes: str = None) -> HumanApproval:
        result = await self.db.execute(select(HumanApproval).where(HumanApproval.id == approval_id))
        approval = result.scalar_one_or_none()
        if not approval:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        approval.status = status
        approval.responded_by = user_id
        approval.responded_at = datetime.utcnow()
        approval.reviewer_notes = notes
        
        await self.db.commit()
        await self.db.refresh(approval)
        
        # P0.3 — Notify waiting worker via Redis pub/sub so it can unblock immediately.
        # The execution engine subscribes to "approval:{approval_id}" before gating
        # on the HumanApproval record and awaits this event with a configurable timeout.
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            _redis = await create_pool(RedisSettings())
            await _redis.publish(
                f"approval:{approval_id}",
                json.dumps({
                    "approval_id": str(approval_id),
                    "status": status,
                    "notes": notes or "",
                    "responded_at": approval.responded_at.isoformat(),
                })
            )
            await _redis.close()
        except Exception:
            # Non-fatal: worker will time out gracefully if Redis is unavailable
            pass
        
        return approval

    async def get_dashboard_stats(self, company_id: UUID, user_role: str = None) -> dict:
        # Platform administrators can view stats across all companies
        if user_role == "app_admin":
            # Active Entities count (all companies)
            entities_count = await self.db.execute(
                select(func.count(HierarchicalEntity.id))
            )
            
            # Executions count (today, all companies)
            today = datetime.now().date()
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
            today = datetime.now().date()
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

    # Document & RAG Methods
    async def upload_document(self, file_content: bytes, filename: str, file_type: str, company_id: UUID, entity_id: UUID = None):
        # Create document record
        document = Document(
            company_id=company_id,
            entity_id=entity_id,
            filename=filename,
            file_type=file_type,
            file_size=str(len(file_content)),
            upload_status="processing"
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)
        
        # Enqueue Job to Arq
        redis = await create_pool(RedisSettings())
        await redis.enqueue_job(
            'process_document', 
            str(document.id),
            file_content,
            file_type,
            filename
        )
        await redis.close()
        
        return document
    
    async def search_documents(self, query: str, company_id: UUID, entity_id: UUID = None, top_k: int = 5):
        from src.ai.models import DocumentChunk
        from sqlalchemy import text
        
        # Get query embedding via centralized EmbeddingService
        from src.ai.memory.embedding_service import EmbeddingService
        embedding_service = EmbeddingService(self.db, company_id)

        query_embedding = await embedding_service.embed_query(query)
        if not query_embedding:
            raise HTTPException(
                status_code=500,
                detail="Embedding generation failed. Please check your AI integration configuration."
            )
        
        # Search using cosine similarity
        sql = text("""
            SELECT 
                dc.id as chunk_id,
                dc.document_id,
                d.filename,
                dc.content,
                1 - (dc.embedding <=> :query_embedding::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.company_id = :company_id
            AND (:entity_id::uuid IS NULL OR d.entity_id = :entity_id)
            ORDER BY dc.embedding <=> :query_embedding::vector
            LIMIT :top_k
        """)
        
        result = await self.db.execute(
            sql,
            {
                "query_embedding": str(query_embedding),
                "company_id": str(company_id),
                "entity_id": str(entity_id) if entity_id else None,
                "top_k": top_k
            }
        )
        
        return result.fetchall()
    
    async def get_documents(self, company_id: UUID, entity_id: UUID = None):
        query = select(Document).where(Document.company_id == company_id)
        if entity_id:
            query = query.where(Document.entity_id == entity_id)
        
        result = await self.db.execute(query)
        return result.scalars().all()

    # ── Template Management ────────────────────────────────────────────────

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

        # 2. Collect all children recursively (follows BOTH parent_id FK and hierarchy.children JSON)
        async def _collect_children(entity: HierarchicalEntity, visited: set[UUID] | None = None) -> list[HierarchicalEntity]:
            if visited is None:
                visited = set()
            visited.add(entity.id)
            children: list[HierarchicalEntity] = []

            # Path A: entities whose parent_id points to this entity
            res = await self.db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.parent_id == entity.id,
                    HierarchicalEntity.company_id == company_id,
                )
            )
            for child in res.scalars().all():
                if child.id not in visited:
                    children.append(child)

            # Path B: entity IDs referenced in hierarchy.children JSON
            hierarchy = entity.hierarchy
            if hierarchy and isinstance(hierarchy, dict):
                for child_ref in hierarchy.get("children", []):
                    if isinstance(child_ref, dict):
                        child_id_str = child_ref.get("child_id")
                        if child_id_str:
                            try:
                                child_uuid = UUID(str(child_id_str))
                            except (ValueError, AttributeError):
                                continue
                            if child_uuid not in visited:
                                cres = await self.db.execute(
                                    select(HierarchicalEntity).where(
                                        HierarchicalEntity.id == child_uuid,
                                    )
                                )
                                child_entity = cres.scalar_one_or_none()
                                if child_entity:
                                    children.append(child_entity)

            # Recurse into each child
            grandchildren = []
            for child in children:
                grandchildren.extend(await _collect_children(child, visited))
            return children + grandchildren

        all_children = await _collect_children(source)

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

        # 2. Collect all child entities via THREE discovery paths:
        #    A) parent_id FK pointing to this entity (+ is_template filter)
        #    B) hierarchy.children JSON (load by ID directly — trusted reference)
        #    C) planning.static_plan.steps[].target.entity_id for CHILD_ENTITY_INVOCATION
        async def _collect_children(entity: HierarchicalEntity, visited: set[UUID] | None = None) -> list[HierarchicalEntity]:
            if visited is None:
                visited = set()
            visited.add(entity.id)
            children: list[HierarchicalEntity] = []
            seen_ids: set[UUID] = set()

            async def _try_add(child_uuid: UUID):
                """Load an entity by ID and add it if not already visited."""
                if child_uuid in visited or child_uuid in seen_ids:
                    return
                cres = await self.db.execute(
                    select(HierarchicalEntity).where(
                        HierarchicalEntity.id == child_uuid,
                        HierarchicalEntity.is_template == True,
                    )
                )
                child_entity = cres.scalar_one_or_none()
                if child_entity:
                    children.append(child_entity)
                    seen_ids.add(child_uuid)

            # Path A: entities whose parent_id points to this entity
            res = await self.db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.parent_id == entity.id,
                    HierarchicalEntity.is_template == True,
                )
            )
            for child in res.scalars().all():
                if child.id not in visited:
                    children.append(child)
                    seen_ids.add(child.id)

            # Path B: entity IDs referenced in hierarchy.children JSON
            hierarchy = entity.hierarchy
            if hierarchy and isinstance(hierarchy, dict):
                for child_ref in hierarchy.get("children", []):
                    if isinstance(child_ref, dict):
                        child_id_str = child_ref.get("child_id")
                        if child_id_str:
                            try:
                                await _try_add(UUID(str(child_id_str)))
                            except (ValueError, AttributeError):
                                continue

            # Path C: entity IDs in CHILD_ENTITY_INVOCATION steps
            planning = entity.planning
            if planning and isinstance(planning, dict):
                for step in (planning.get("static_plan") or {}).get("steps", []):
                    if step.get("type") == "CHILD_ENTITY_INVOCATION":
                        eid = (step.get("target") or {}).get("entity_id")
                        if eid:
                            try:
                                await _try_add(UUID(str(eid)))
                            except (ValueError, AttributeError):
                                continue

            # Recurse into each child
            grandchildren = []
            for child in children:
                grandchildren.extend(await _collect_children(child, visited))
            return children + grandchildren

        all_children = await _collect_children(template)
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
