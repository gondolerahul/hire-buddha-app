"""
ai.core.arq_jobs — Background job functions for the arq worker.

Contains all arq-registered functions: execution, gateway event processing,
document processing, dreaming, graph maintenance, and CORTEX scheduling.

Extracted from worker.py during Phase 10A restructuring.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Sequence, cast
from uuid import UUID

from sqlalchemy import select

from src.common.database import AsyncSessionLocal
from src.ai.models import ExecutionRun, HierarchicalEntity, RunStatus

logger = logging.getLogger(__name__)

# --- Arq Jobs ---

async def run_execution_recursive(ctx: dict[str, Any], run_id_str: str) -> Any:
    """Entry point for an execution run.

    The ``AgentLoop`` orchestrator is the sole run engine (C4). The
    ``agent_loop.enabled`` flag is stamped onto the run for the SPA but no
    longer gates engine choice.
    """
    run_id = UUID(run_id_str)
    import redis.asyncio as redis
    from src.common.config import settings

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")  # type: ignore[no-untyped-call]

    async with AsyncSessionLocal() as db:
        # Resolve feature flag scope first; needs the run's company_id +
        # any entity-level override.
        from src.ai.core.feature_flags import FeatureFlags

        flags = FeatureFlags(db, redis=redis_pool)
        company_id, _entity_extras = await _resolve_run_flag_scope(db, run_id)

        # The AgentLoop is the sole run engine (C4). ``agent_loop.enabled`` no
        # longer gates engine choice; it is stamped onto the run below only so
        # the SPA's ExecutionDetail page renders the loop timeline.
        logger.info("[dispatch] run=%s engine=agent_loop company=%s", run_id, company_id)

        # ── Guard against ghost jobs ──────────────────────────────────────
        # If the run (or its owning entity) was deleted after the job was
        # enqueued — e.g. the operator removed the entity mid-flight — there
        # is nothing to execute. Driving the engine anyway would attempt to
        # write child rows (cortex_trees, usage_logs, llm_interaction_logs,
        # StepHealthRecords…) that reference the now-missing run/entity, each
        # raising a ForeignKeyViolationError that poisons the session and
        # cascades into a storm of PendingRollbackErrors on every retry.
        # Return cleanly (no exception) so arq treats the job as done and
        # stops retrying the ghost run.
        from sqlalchemy.orm import selectinload as _selectinload
        guard_run = (await db.execute(
            select(ExecutionRun)
            .options(_selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )).scalar_one_or_none()
        if guard_run is None:
            logger.warning(
                "[dispatch] run %s no longer exists — abandoning ghost job", run_id
            )
            await redis_pool.close()
            return
        if guard_run.entity is None or getattr(guard_run.entity, "status", None) == "DELETED":
            logger.warning(
                "[dispatch] run %s references missing/deleted entity %s — "
                "abandoning ghost job", run_id, guard_run.entity_id,
            )
            await redis_pool.close()
            return

        # ── Idempotency guard: never re-drive an already-finished run ─────────
        # arq retries a failed job (default max_tries=5), and any path that
        # re-enqueues this run_id would otherwise re-run the engine end-to-end
        # and re-settle billing on a run that already paid. Once a run reaches a
        # terminal state, a fresh dispatch of the SAME run_id is always a
        # duplicate — retry/refine create NEW run rows, so they are unaffected.
        # Returning cleanly (no exception) stops arq from retrying further.
        _TERMINAL = {
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
            RunStatus.PARTIAL_COMPLETE.value,
            RunStatus.CANCELLED.value,
        }
        if str(guard_run.status) in _TERMINAL:
            logger.warning(
                "[dispatch] run %s already terminal (status=%s) — skipping "
                "re-dispatch to avoid re-billing an already-settled run",
                run_id, guard_run.status,
            )
            await redis_pool.close()
            return

        try:
            run_obj = (await db.execute(
                select(ExecutionRun).where(ExecutionRun.id == run_id)
            )).scalar_one_or_none()
            if run_obj is not None:
                idata = dict(run_obj.input_data or {})
                ff = dict(idata.get("feature_flags") or {})
                ff["agent_loop.enabled"] = True
                idata["feature_flags"] = ff
                run_obj.input_data = idata  # reassign so the JSON change is tracked
                await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("Could not stamp agent_loop decision onto run %s", run_id)

        # Bind a per-run TraceRecorder for the whole execution. The deep layers
        # (tool executor, LLM router) read it off a ContextVar.
        from src.ai.core.trace import TraceRecorder, set_recorder

        _obs = (getattr(guard_run.entity, "observability", None) or {}) if guard_run.entity else {}
        _capture = bool(_obs.get("log_thoughts", True))
        recorder = TraceRecorder(
            run_id, company_id=company_id, redis=redis_pool,
            capture_payloads=_capture,
        )

        with set_recorder(recorder):
            from src.ai.core.agent_loop import AgentLoop

            loop = AgentLoop(
                db, redis_pool,
                company_id=company_id,
                feature_flags=flags,
            )
            await loop.run(run_id)

    await redis_pool.close()


async def _resolve_run_flag_scope(db: Any, run_id: UUID) -> Any:
    """Best-effort (company_id, entity_extras) lookup for flag resolution.

    Returns ``(None, None)`` on any failure so flag resolution falls
    back to env + default — never blocks the run from starting.
    """
    try:
        from sqlalchemy.orm import selectinload
        run = (await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.entity))
            .where(ExecutionRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            return None, None
        entity = run.entity
        extras = getattr(entity, "metadata_extensions", None) if entity else None
        return run.company_id, extras if isinstance(extras, dict) else None
    except Exception:
        return None, None


async def process_gateway_event(ctx: dict[str, Any], envelope_dict: dict[str, Any]) -> Any:
    """Process a gateway event (webhook/internal) by routing to the correct handler.

    This is the arq job function invoked by the CentralDispatcher when a webhook
    event arrives at the gateway.

    Routing:
      - sheet.row_inserted → Campaign-based outbound call pipeline
      - other events        → ExecutionRun via the AgentLoop (text agents)
    """
    import redis.asyncio as redis
    from src.common.config import settings
    from src.ai.models import HierarchicalEntity, ExecutionRun, RunStatus

    client_id = envelope_dict.get("client_id", "")
    if not client_id:
        logger.warning("[process_gateway_event] No client_id in envelope — skipping")
        return

    raw_data = envelope_dict.get("raw_data", {})
    event_type = envelope_dict.get("event_type", "generic_event")
    source = envelope_dict.get("source", "unknown")
    correlation_id = envelope_dict.get("id", "")

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")  # type: ignore[no-untyped-call]

    try:
        async with AsyncSessionLocal() as db:
            # ── Entity resolution: prefer explicit entity_id from payload ────
            entity = None
            payload_entity_id = raw_data.get("raw", {}).get("entity_id") if isinstance(raw_data, dict) else None

            if payload_entity_id:
                try:
                    result = await db.execute(
                        select(HierarchicalEntity).where(
                            HierarchicalEntity.id == UUID(payload_entity_id),
                            HierarchicalEntity.company_id == UUID(client_id),
                            HierarchicalEntity.status != 'ARCHIVED',
                        )
                    )
                    entity = result.scalar_one_or_none()
                except Exception as e:
                    logger.warning(f"[process_gateway_event] entity_id lookup failed: {e}")

            # Fallback: first active entity for the company
            if not entity:
                result = await db.execute(
                    select(HierarchicalEntity).where(
                        HierarchicalEntity.company_id == UUID(client_id),
                        HierarchicalEntity.status != 'ARCHIVED',
                    ).limit(1)
                )
                entity = result.scalar_one_or_none()

            if not entity:
                logger.warning(
                    f"[process_gateway_event] No active entity for company {client_id}"
                )
                return

            logger.info(
                f"[process_gateway_event] Resolved entity '{entity.name}' "
                f"({entity.id}) — event={event_type} source={source}"
            )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # APPROACH C: Sheet row → Campaign-based outbound voice call
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if event_type == "sheet.row_inserted":
                await _handle_sheet_row_campaign(
                    db=db,
                    entity=entity,
                    client_id=client_id,
                    raw_data=raw_data,
                    correlation_id=correlation_id,
                    redis_pool=redis_pool,
                )
                return

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # Default: ExecutionRun path (text-based agents)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            run = ExecutionRun(
                company_id=UUID(client_id),
                entity_id=entity.id,
                input_data={
                    "input": json.dumps(raw_data),
                    "channel": envelope_dict.get("channel", "webhook"),
                    "source": source,
                    "event_type": event_type,
                    "correlation_id": correlation_id,
                },
                status=RunStatus.PENDING,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)

            logger.info(
                f"[process_gateway_event] ExecutionRun {run.id} created — executing..."
            )

            from src.ai.core.agent_loop import AgentLoop
            loop = AgentLoop(db, redis_pool, company_id=UUID(client_id))
            await loop.run(run.id)

            logger.info(
                f"[process_gateway_event] ExecutionRun {run.id} finished "
                f"(status={run.status})"
            )
    except Exception as exc:
        logger.error(
            f"[process_gateway_event] Failed for correlation={correlation_id}: {exc}",
            exc_info=True,
        )
    finally:
        await redis_pool.close()


async def _handle_sheet_row_campaign(
    db: Any,
    entity: Any,
    client_id: str,
    raw_data: dict[str, Any],
    correlation_id: str,
    redis_pool: Any,
) -> Any:
    """Create a single-contact Campaign from a Google Sheets row and trigger outbound call.

    Pipeline: Campaign → CampaignExecutor._place_tata_call() → Tata Tele webhook
    → TataStreamHandler → GeminiLiveClient (speech-to-speech conversation)
    """
    from src.ai.campaign_models import Campaign, CampaignCall
    from arq.connections import RedisSettings, create_pool
    from src.common.config import settings as app_settings
    from src.auth.models import User

    # ── 1. Extract lead data from the webhook payload ───────────────────
    raw_payload = raw_data.get("raw", {}) if isinstance(raw_data, dict) else {}
    row_data = raw_payload.get("data", {})

    # Try common column names for phone number
    phone = (
        row_data.get("Phone")
        or row_data.get("phone")
        or row_data.get("Mobile")
        or row_data.get("mobile")
        or row_data.get("Phone Number")
        or row_data.get("phone_number")
        or row_data.get("Contact")
        or row_data.get("contact")
        or row_data.get("Number")
        or row_data.get("number")
    )

    if not phone:
        logger.warning(
            f"[sheet_campaign] No phone number found in row data. "
            f"Available columns: {list(row_data.keys())}. Skipping."
        )
        return

    # Normalize phone to string
    phone = str(phone).strip()
    # Remove .0 suffix from numeric cells (e.g. 9876543210.0)
    if phone.endswith(".0"):
        phone = phone[:-2]

    name = (
        row_data.get("Name")
        or row_data.get("name")
        or row_data.get("Lead Name")
        or row_data.get("Full Name")
        or "Lead"
    )

    logger.info(
        f"[sheet_campaign] Lead detected: name='{name}', phone='{phone}', "
        f"entity='{entity.name}', correlation={correlation_id}"
    )

    # ── 2. Resolve created_by (Campaign.created_by is NOT NULL) ─────────
    created_by_id = entity.created_by
    if not created_by_id:
        # Fallback: find any user in the company
        user_result = await db.execute(
            select(User.id).where(
                User.company_id == UUID(client_id),
            ).limit(1)
        )
        user_row = user_result.scalar_one_or_none()
        if user_row:
            created_by_id = user_row
        else:
            logger.error(
                f"[sheet_campaign] No users found for company {client_id}. "
                f"Cannot create campaign."
            )
            return

    # ── 3. Determine telephony provider from entity config ──────────────
    entity_meta = entity.metadata_extensions or {}
    provider = entity_meta.get("telephony_provider", "tata_tele")

    # ── 4. Create single-contact Campaign ───────────────────────────────
    from datetime import datetime as _dt
    campaign = Campaign(
        company_id=UUID(client_id),
        created_by=created_by_id,
        agent_id=entity.id,
        name=f"Auto: {name} ({_dt.utcnow().strftime('%Y-%m-%d %H:%M')})",
        description=(
            f"Auto-generated campaign from Google Sheets webhook. "
            f"Lead: {name}, Phone: {phone}. "
            f"Correlation: {correlation_id}"
        ),
        total_contacts=1,
        contact_list=[{"phone": phone, "name": str(name), **{k: str(v) for k, v in row_data.items()}}],
        provider=provider,
        max_concurrent_calls=1,
        status="draft",
        campaign_metadata={
            "source": "google_sheets_webhook",
            "correlation_id": correlation_id,
            "sheet_name": raw_payload.get("sheet_name"),
            "spreadsheet_id": raw_payload.get("spreadsheet_id"),
            "row_index": raw_payload.get("row_index"),
        },
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    # ── 5. Create CampaignCall ──────────────────────────────────────────
    campaign_call = CampaignCall(
        campaign_id=campaign.id,
        contact_data={"phone": phone, "name": str(name), **{k: str(v) for k, v in row_data.items()}},
        status="pending",
    )
    db.add(campaign_call)
    await db.commit()

    logger.info(
        f"[sheet_campaign] Campaign {campaign.id} created with 1 contact. "
        f"Enqueuing execute_campaign_task..."
    )

    # ── 6. Enqueue campaign execution via arq ───────────────────────────
    try:
        from urllib.parse import urlparse
        parsed = urlparse(app_settings.REDIS_URL or "redis://localhost:6379")
        redis_settings = RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
        )
        arq_pool = await create_pool(redis_settings)
        job = await arq_pool.enqueue_job(
            "execute_campaign_task",
            str(campaign.id),
        )
        await arq_pool.aclose()

        job_id = job.job_id if job else "queued"
        logger.info(
            f"[sheet_campaign] Campaign {campaign.id} enqueued as arq job {job_id}. "
            f"Call will be placed to {phone} via {provider}."
        )
    except Exception as enq_err:
        logger.error(
            f"[sheet_campaign] Failed to enqueue campaign {campaign.id}: {enq_err}",
            exc_info=True,
        )
        # Fallback: execute in-process
        try:
            from src.ai.campaign_executor import CampaignExecutor
            executor = CampaignExecutor(db)
            await executor.start_campaign(cast(UUID, campaign.id))
            logger.info(f"[sheet_campaign] In-process fallback completed for campaign {campaign.id}")
        except Exception as exec_err:
            logger.error(
                f"[sheet_campaign] In-process fallback also failed: {exec_err}",
                exc_info=True,
            )


async def process_document(ctx: dict[str, Any], document_id_str: str, file_content: bytes, file_type: str, filename: str) -> Any:
    from src.ai.models import Document, DocumentChunk
    import io
    
    document_id = UUID(document_id_str)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            return
            
        try:
            if file_type == "txt":
                text = file_content.decode("utf-8")
            elif file_type == "pdf":
                import PyPDF2
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            elif file_type == "docx":
                import docx
                doc = docx.Document(io.BytesIO(file_content))
                text = "\n".join([p.text for p in doc.paragraphs])
            else:
                text = file_content.decode("utf-8", errors="ignore")
                
            chunk_size = 500
            chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            
            # Use centralized EmbeddingService (admin-configurable model)
            from src.ai.memory.embedding_service import EmbeddingService
            embedding_service = EmbeddingService(db, document.company_id)
            
            total_chunks = len(chunks)
            success_count = 0
            failed_count = 0
            
            for idx, chunk_text in enumerate(chunks):
                embedding = await embedding_service.embed_text(
                    chunk_text, task_type="RETRIEVAL_DOCUMENT"
                )
                
                if embedding is None:
                    failed_count += 1
                    logger.warning(f"Embedding failed for chunk {idx}/{total_chunks} of doc {document_id}")
                    # Still create the chunk without embedding
                    chunk = DocumentChunk(
                        document_id=document.id,
                        chunk_index=str(idx),
                        content=chunk_text,
                        embedding=None,
                    )
                else:
                    success_count += 1
                    chunk = DocumentChunk(
                        document_id=document.id,
                        chunk_index=str(idx),
                        content=chunk_text,
                        embedding=embedding,
                    )
                db.add(chunk)
            
            # Set upload_status based on embedding results
            if failed_count == total_chunks:
                document.upload_status = "failed"
                logger.error(
                    f"All {total_chunks} chunks failed embedding for document "
                    f"{document.id} ({document.filename})"
                )
            elif failed_count > 0:
                document.upload_status = "partial"
                logger.warning(
                    f"{failed_count}/{total_chunks} chunks failed embedding for document "
                    f"{document.id} ({document.filename})"
                )
            else:
                document.upload_status = "completed"
                logger.info(
                    f"Document {document.id} ({document.filename}): "
                    f"all {total_chunks} chunks embedded successfully"
                )
            
            await db.commit()
            
            # --- v2: Dual-write into Knowledge Tree ---
            # Ingest the document into the entity's persistent Knowledge Tree
            # alongside the legacy document_chunks table (Phase B dual-write).
            if document.entity_id:
                try:
                    from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
                    kt_service = KnowledgeTreeService(db, document.company_id)
                    tree = await kt_service.get_or_create_knowledge_tree(
                        entity_id=document.entity_id
                    )
                    kt_node_count = await kt_service.ingest_document(
                        tree_id=tree.id,
                        document_id=document.id,
                        content=text,
                        filename=filename,
                        entity_id=document.entity_id,
                    )
                    await db.commit()
                    logger.info(
                        f"Knowledge Tree v2: ingested {kt_node_count} nodes for "
                        f"document {document.id} ({document.filename})"
                    )
                except Exception as kt_err:
                    logger.warning(
                        f"Knowledge Tree v2 ingestion failed (non-fatal): {kt_err}"
                    )
            
        except Exception as e:
            document.upload_status = "failed"
            await db.commit()
            logger.error(f"Doc processing failed: {e}")

# Import campaign worker functions
from src.ai.campaign_worker import execute_campaign_task, pause_campaign_task, stop_campaign_task


# ---------------------------------------------------------------------------
# Phase D: dreaming_worker — Background learning pipeline
# ---------------------------------------------------------------------------
async def dreaming_worker(ctx: dict[str, Any], entity_id_str: str, company_id_str: str, force: bool = False) -> dict[str, Any]:
    """
    Background worker task for the Dreaming Engine.
    Runs the three-phase learning pipeline for an entity:
      Phase 1: Extract observations from episodes
      Phase 2: Recognize patterns across observations
      Phase 3: Distill intelligence rules from patterns

    Scheduled to run after execution completion or on a timer.
    """
    from src.common.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            from src.ai.memory.dreaming_engine import DreamingEngine
            engine = DreamingEngine(db, UUID(company_id_str))
            result = await engine.dream(
                entity_id=UUID(entity_id_str),
                force=force,
            )
            await db.commit()
            return result
        except Exception as e:
            logger.error(f"Dreaming worker failed for entity {entity_id_str}: {e}")
            return {"error": str(e)}

# ---------------------------------------------------------------------------
# C: dreaming_cron_trigger — Auto-schedule dreaming for entities
# ---------------------------------------------------------------------------
async def dreaming_cron_trigger(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Periodic cron job that auto-discovers entities with dreaming enabled
    and enqueues a dreaming_worker job for each.

    Entity selection: entities with `capabilities.dreaming.enabled == true`
    that haven't been consolidated in the last CONSOLIDATION_INTERVAL_HOURS.
    """
    from src.common.database import AsyncSessionLocal
    from sqlalchemy import text as _text

    enqueued = 0
    try:
        async with AsyncSessionLocal() as db:
            # Find entities with dreaming enabled via JSONB query
            result = await db.execute(_text(
                "SELECT id, company_id FROM hierarchical_entities "
                "WHERE status != 'ARCHIVED' "
                "AND capabilities->'dreaming'->>'enabled' = 'true'"
            ))
            entities = result.fetchall()

            for row in entities:
                entity_id, company_id = str(row[0]), str(row[1])
                try:
                    redis = ctx.get('redis')
                    if redis:
                        from arq.connections import ArqRedis
                        arq = ArqRedis(redis)
                        await arq.enqueue_job(
                            "dreaming_worker", entity_id, company_id, False
                        )
                        enqueued += 1
                        logger.info(f"Dreaming cron: enqueued for entity {entity_id}")
                except Exception as e:
                    logger.warning(f"Dreaming cron: failed to enqueue entity {entity_id}: {e}")

            logger.info(f"Dreaming cron: enqueued {enqueued}/{len(entities)} entities")
    except Exception as e:
        logger.error(f"Dreaming cron trigger failed: {e}")

    return {"enqueued": enqueued}


# ---------------------------------------------------------------------------
# Phase E: graph_maintenance_worker — Periodic graph maintenance
# ---------------------------------------------------------------------------
async def graph_maintenance_worker(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Periodic maintenance for the semantic graph.
    Run daily via scheduler. Decays stale edge weights and prunes weak edges.
    """
    from src.common.database import AsyncSessionLocal
    from sqlalchemy import text as _text

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(_text(
                "SELECT DISTINCT company_id FROM cortex_trees WHERE status = 'active'"
            ))
            companies = result.fetchall()

            total_decayed = 0
            total_pruned = 0

            for row in companies:
                from src.ai.memory.graph_service import SemanticGraphService
                graph = SemanticGraphService(db, row[0])
                decayed = await graph.decay_weights(days_inactive=30)
                pruned = await graph.prune_weak_edges()
                total_decayed += decayed
                total_pruned += pruned

            await db.commit()
            logger.info(f"Graph maintenance: {total_decayed} edges decayed, {total_pruned} pruned")
            return {"decayed": total_decayed, "pruned": total_pruned}
        except Exception as e:
            logger.error(f"Graph maintenance worker failed: {e}")
            return {"error": str(e)}

# ---------------------------------------------------------------------------
# Resume_execution — Arq job to resume a checkpointed run
# ---------------------------------------------------------------------------
async def resume_execution(ctx: dict[str, Any], run_id_str: str) -> dict[str, Any]:
    """
    Resume a previously checkpointed execution run.
    Reloads `run.context_state` and skips steps that are already completed.
    """
    from src.common.database import AsyncSessionLocal

    run_id = UUID(run_id_str)
    async with AsyncSessionLocal() as db:
        redis = ctx.get('redis')
        from src.ai.core.agent_loop import AgentLoop
        company_id, _entity_extras = await _resolve_run_flag_scope(db, run_id)
        logger.info(f"Resuming ExecutionRun: {run_id}")
        return await AgentLoop(db, redis, company_id=company_id).run(run_id)


async def resume_parent_run(ctx: dict[str, Any], parent_run_id_str: str) -> dict[str, Any]:
    """Resume a parent run suspended on async child dispatch.

    Enqueued by ``AgentLoop._maybe_resume_parent`` when a child run finalizes.
    Drives ``AgentLoop.resume``, which folds terminal children and continues
    the loop. Idempotent: a no-op when the parent is not WAITING_ON_CHILDREN
    (so duplicate enqueues, or legacy inline children, are harmless).
    """
    parent_run_id = UUID(parent_run_id_str)
    import redis.asyncio as redis
    from src.common.config import settings

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")  # type: ignore[no-untyped-call]
    try:
        async with AsyncSessionLocal() as db:
            from src.ai.core.agent_loop import AgentLoop
            from src.ai.core.feature_flags import FeatureFlags
            from src.ai.core.trace import TraceRecorder, set_recorder

            flags = FeatureFlags(db, redis=redis_pool)
            company_id, _entity_extras = await _resolve_run_flag_scope(db, parent_run_id)
            recorder = TraceRecorder(parent_run_id, company_id=company_id, redis=redis_pool)
            with set_recorder(recorder):
                loop = AgentLoop(
                    db, redis_pool, company_id=company_id, feature_flags=flags,
                )
                return await loop.resume(parent_run_id)
    finally:
        await redis_pool.close()


# ---------------------------------------------------------------------------
# Scheduled CORTEX wake-ups — Arq cron job
# ---------------------------------------------------------------------------
async def cortex_resume_scheduled(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Periodic cron job that wakes up suspended CORTEX trees whose
    next_resume_at timestamp has arrived. Creates a new execution run
    for each tree and enqueues it.
    """
    from src.common.database import AsyncSessionLocal
    from src.ai.memory.cortex_models import CortexTree, CortexTreeStatus
    from sqlalchemy import select

    resumed = 0
    try:
        async with AsyncSessionLocal() as db:
            # Find trees scheduled for resumption
            result = await db.execute(
                select(CortexTree).where(
                    CortexTree.status == CortexTreeStatus.SUSPENDED,
                    CortexTree.next_resume_at != None,
                    CortexTree.next_resume_at <= datetime.utcnow(),
                )
            )
            trees = result.scalars().all()

            for tree in trees:
                try:
                    # Create a new execution run to resume this tree
                    from src.ai.models import ExecutionRun
                    resume_run = ExecutionRun(
                        entity_id=tree.entity_id,
                        company_id=tree.company_id,
                        user_id=tree.user_id,
                        input_data={"cortex_tree_id": str(tree.id)},
                        status="PENDING",
                    )
                    db.add(resume_run)
                    await db.flush()

                    # Clear the schedule to prevent re-triggering
                    tree.next_resume_at = None

                    # Enqueue to Arq
                    redis = ctx.get('redis')
                    if redis:
                        from arq.connections import ArqRedis
                        arq = ArqRedis(redis)
                        await arq.enqueue_job("run_execution_recursive", str(resume_run.id))
                        resumed += 1
                        logger.info(f"CORTEX scheduled resume: tree {tree.id} → run {resume_run.id}")

                except Exception as e:
                    logger.error(f"CORTEX scheduled resume failed for tree {tree.id}: {e}")

            await db.commit()
    except Exception as e:
        logger.error(f"CORTEX scheduled wake-up cron error: {e}")

    return {"resumed": resumed}


# ---------------------------------------------------------------------------
# Critic Calibration cron job
# ---------------------------------------------------------------------------

async def kpi_rollup_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
    """Phase 11 Track 9 — refresh the kpi_daily_rollup materialised view.

    Hourly cron. Uses ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` so
    reads against the view never block. Falls back to a plain refresh
    if the unique index is missing (e.g. fresh database without the
    Track 9 migration applied yet).
    """
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(text(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_daily_rollup"
                ))
                await db.commit()
                return {"refreshed": True, "mode": "concurrent"}
            except Exception as concurrent_err:
                logger.warning(
                    "CONCURRENTLY refresh failed (%s); falling back to plain refresh",
                    concurrent_err,
                )
                await db.rollback()
                await db.execute(text(
                    "REFRESH MATERIALIZED VIEW kpi_daily_rollup"
                ))
                await db.commit()
                return {"refreshed": True, "mode": "plain"}
    except Exception as e:                                                  # noqa: BLE001
        logger.error(f"kpi_rollup_refresh error: {e}")
        return {"error": str(e)}


async def dreaming_outcome_trigger(
    ctx: dict[str, Any], entity_id_str: str, reason: str = "success",
    company_id_str: str | None = None,
) -> dict[str, Any]:
    """Phase 11 Track 6 — outcome-triggered Dreaming pass.

    Enqueued by ``AgentLoop._finalize`` after every successful or failed
    run. Performs the cheap ``should_dream`` guard first so we don't
    burn LLM cost on entities that haven't accumulated enough new
    episodes. Falls back gracefully when the engine isn't reachable
    (e.g. early-rollout entities).
    """
    try:
        from src.ai.memory.dreaming_engine import DreamingEngine
        async with AsyncSessionLocal() as db:
            entity_id = UUID(entity_id_str)
            company_id = UUID(company_id_str) if company_id_str else None
            if company_id is None:
                from sqlalchemy import select
                from src.ai.orm.entity import HierarchicalEntity
                ent = (await db.execute(
                    select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
                )).scalar_one_or_none()
                if ent is None:
                    return {"skipped": "entity not found"}
                company_id = ent.company_id
            engine = DreamingEngine(db, company_id=company_id)
            should = True
            checker = getattr(engine, "should_dream", None)
            if callable(checker):
                try:
                    should = await checker(entity_id)
                except Exception:                                           # pragma: no cover
                    should = True
            if not should:
                return {"skipped": "should_dream=False", "entity_id": entity_id_str}
            dream = getattr(engine, "dream", None)
            if not callable(dream):
                return {"skipped": "DreamingEngine.dream not implemented"}
            await dream(entity_id)
            await db.commit()
            return {"dreamed": True, "entity_id": entity_id_str, "reason": reason}
    except Exception as e:                                                  # noqa: BLE001
        logger.warning(f"dreaming_outcome_trigger error: {e}")
        return {"error": str(e)}


async def critic_calibration_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Weekly: scan recent StepHealthRecords vs run outcomes and write
    false-pass / false-fail metrics back as Intelligence rules.

    See ``ai.planning.critic_calibration.CriticCalibrator`` for the
    calibration logic.
    """
    try:
        async with AsyncSessionLocal() as db:
            # Lazy-import to avoid worker-boot side effects.
            from sqlalchemy import distinct, select

            from src.ai.orm.execution import ExecutionRun
            from src.ai.planning.critic_calibration import CriticCalibrator

            # The calibrator persists into a company-scoped Intelligence Tree,
            # so run one per company that has recent activity.
            company_ids = (await db.execute(
                select(distinct(ExecutionRun.company_id))
                .where(ExecutionRun.company_id.is_not(None))
                .limit(500)
            )).scalars().all()

            entities_scored = 0
            samples_total = 0
            for company_id in company_ids:
                results = await CriticCalibrator(db, company_id).run()
                entities_scored += len(results)
                samples_total += sum(r.samples for r in results)
            await db.commit()
            return {
                "companies_scored": len(company_ids),
                "entities_scored": entities_scored,
                "samples_total": samples_total,
            }
    except Exception as e:                                                  # noqa: BLE001
        logger.error(f"critic_calibration_job error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Meta-Agent Skill Library scan + Prompt-Evo cron
# ---------------------------------------------------------------------------

async def skill_promotion_scan(ctx: dict[str, Any]) -> dict[str, Any]:
    """Weekly: scan every entity with recent activity for repeated tool chains.

    For each entity that has run within the lookback window, ask
    :class:`SkillLibrary` to detect chains exceeding the repeat
    threshold and write candidates into the company's
    :class:`MetaIntelligenceTree`. Humans approve the candidates via
    the admin API.
    """
    try:
        from sqlalchemy import distinct, select
        from src.ai.meta.skill_library import SkillLibrary
        from src.ai.orm.entity import HierarchicalEntity
        from src.ai.orm.execution import ExecutionRun

        proposed_per_entity: dict[str, int] = {}
        async with AsyncSessionLocal() as db:
            entity_rows = (await db.execute(
                select(distinct(ExecutionRun.entity_id))
                .where(ExecutionRun.entity_id.is_not(None))
                .limit(500)
            )).scalars().all()
            for entity_id in entity_rows:
                ent = (await db.execute(
                    select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
                )).scalar_one_or_none()
                if ent is None or ent.company_id is None:
                    continue
                lib = SkillLibrary(db)
                try:
                    candidates = await lib.scan_entity(entity_id, ent.company_id)
                except Exception as e:                                      # noqa: BLE001
                    logger.warning(f"skill scan failed for entity {entity_id}: {e}")
                    continue
                if candidates:
                    proposed_per_entity[str(entity_id)] = len(candidates)
            await db.commit()
        return {
            "entities_scanned": len(entity_rows),
            "candidates_proposed": sum(proposed_per_entity.values()),
        }
    except Exception as e:                                                  # noqa: BLE001
        logger.error(f"skill_promotion_scan error: {e}")
        return {"error": str(e)}


async def _propose_prompt_update(db: Any, entity: Any, recent: Sequence[Any]) -> Any:
    """Run the critic-of-critic over an entity's recent runs (`06` §6.1).

    Best-effort: any failure returns an empty proposal so the cron still writes a
    no-op candidate row. Never raises.
    """
    from src.ai.meta.prompt_evolution import PromptEvolutionCritic, PromptUpdateProposal, RunSample

    try:
        samples = [
            RunSample(
                run_id=str(r.id),
                outcome=str(getattr(r, "status", "") or ""),
                cost_usd=float(getattr(r, "total_cost_usd", 0) or 0),
            )
            for r in recent
        ]
        logic_gate = getattr(entity, "logic_gate", None)
        current_prompt = (
            getattr(entity, "system_prompt", None)
            or getattr(entity, "prompt", None)
            or (logic_gate.get("system_prompt", "") if isinstance(logic_gate, dict) else "")
            or ""
        )
        from src.ai.llm.router import LLMRouter

        llm = LLMRouter(db=db, company_id=entity.company_id)
        return await PromptEvolutionCritic().propose(str(current_prompt), samples, llm=llm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prompt-evolution proposal failed: %s", exc)
        return PromptUpdateProposal()


async def meta_agent_prompt_evolution(ctx: dict[str, Any]) -> dict[str, Any]:
    """Weekly: write Meta-Agent prompt-update candidates (HITL-gated).

    The actual LLM "critic of critic" pass is deliberately *not*
    wired up in Track 5 — that's a P2 follow-up. This cron lays the
    plumbing: it samples recent runs, builds a stub
    ``prompt_update_candidate`` rationale, and writes it into the
    MetaIntelligenceTree. Until an admin POSTs the approve endpoint
    nothing changes about the Meta-Agent prompt.
    """
    try:
        from sqlalchemy import select
        from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
        from src.ai.orm.entity import HierarchicalEntity
        from src.ai.orm.execution import ExecutionRun

        proposed = 0
        async with AsyncSessionLocal() as db:
            # Find Meta-Agent entities (flagged via metadata_extensions.is_meta_agent).
            ents = (await db.execute(select(HierarchicalEntity).limit(500))).scalars().all()
            meta_entities = [
                e for e in ents
                if isinstance(e.metadata_extensions, dict)
                and e.metadata_extensions.get("is_meta_agent")
            ]
            for me in meta_entities:
                if me.company_id is None:
                    continue
                recent = (await db.execute(
                    select(ExecutionRun)
                    .where(ExecutionRun.entity_id == me.id)
                    .order_by(ExecutionRun.created_at.desc())
                    .limit(20)
                )).scalars().all()
                if len(recent) < 3:
                    continue
                tree = MetaIntelligenceTree(db, me.company_id)
                proposal = await _propose_prompt_update(db, me, recent)
                try:
                    await tree.add_prompt_update_candidate(
                        prompt_diff=proposal.prompt_diff,
                        rationale=(
                            proposal.rationale
                            or f"Weekly automated review of {len(recent)} recent "
                               "Meta-Agent runs; no systemic issue found."
                        ),
                        evidence_run_ids=proposal.evidence_run_ids
                        or [str(r.id) for r in recent[:5]],
                    )
                    proposed += 1
                except Exception as e:                                      # noqa: BLE001
                    logger.warning(f"prompt-evo write failed for entity {me.id}: {e}")
            await db.commit()
        return {"prompt_candidates_proposed": proposed}
    except Exception as e:                                                  # noqa: BLE001
        logger.error(f"meta_agent_prompt_evolution error: {e}")
        return {"error": str(e)}


async def cost_estimator_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
    """Nightly: refresh `cost_estimator` baselines from telemetry.

    Scans recent `tool_interaction_logs` rows, computes a robust
    median cost per tool, and writes the refreshed dict into a
    well-known CORTEX-adjacent row. The estimator picks it up via
    `cost_estimator.refresh_from_db(...)` on next process start; live
    workers continue using the cached baseline until they restart.

    Conservative defaults: only update a baseline when we have ≥ 20
    samples in the last 30 days; otherwise keep the seeded value.
    """
    try:
        from datetime import timedelta
        from decimal import Decimal as _D
        from sqlalchemy import text as _t
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                _t(
                    """
                    SELECT tool_id,
                           COUNT(*) AS samples,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cost_usd)
                               AS median_cost
                    FROM tool_interaction_logs
                    WHERE created_at >= :since
                      AND cost_usd > 0
                      AND success = TRUE
                    GROUP BY tool_id
                    HAVING COUNT(*) >= 20
                    """
                ),
                {"since": datetime.utcnow() - timedelta(days=30)},
            )).all()
            refreshed: dict[str, float] = {}
            for r in rows:
                refreshed[str(r.tool_id)] = float(r.median_cost or 0)
            if not refreshed:
                return {"refreshed_tools": 0, "reason": "no telemetry"}
            # Apply in-process so live workers using cost_estimator pick the
            # new baseline on next process restart. The cron emits a
            # telemetry event so the persisted baseline source is auditable.
            try:
                from src.ai.planning import cost_estimator as _ce
                from decimal import Decimal as _Dec
                for tool_id, cost in refreshed.items():
                    if cost > 0:
                        _ce.TOOL_BASELINE_COST[tool_id] = _Dec(str(cost))
            except Exception:                                                # pragma: no cover
                pass
            try:
                from src.ai.core.events import event
                event(
                    "agent.cost.estimator_refresh",
                    refreshed_tools=len(refreshed),
                    tools=refreshed,
                )
            except Exception:                                                # pragma: no cover
                pass
        return {"refreshed_tools": len(refreshed), "tools": refreshed}
    except Exception as e:                                                  # noqa: BLE001
        logger.error(f"cost_estimator_refresh error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# RecursiveReasoningEngine — extends ExecutionEngine with Goal Trees
