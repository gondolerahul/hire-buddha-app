"""
ai.core.arq_jobs — Background job functions for the arq worker.

Contains all arq-registered functions: execution, gateway event processing,
document processing, dreaming, graph maintenance, and CORTEX scheduling.

Extracted from worker.py during Phase 10A restructuring.

Each job opens the database of the tenant it works for (Phase 14 WS2 2.4):
a job about one company's data takes ``company_id`` (``job_queue.tenant_arg``;
``None`` for a job queued before jobs carried it, which only single mode can
serve), and a cron that sweeps every company runs once per tenant database
(``_each_tenant``) — once, over the shared database, while
``TENANCY_MODE=single``.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Sequence, cast
from uuid import UUID

from sqlalchemy import select

from src.common.tenancy.session import tenant_scopes, tenant_session
from src.ai.orm import ExecutionRun, HierarchicalEntity, RunStatus

logger = logging.getLogger(__name__)


async def _each_tenant(sweep: Callable[[Optional[UUID]], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Run a cron's ``sweep(scope)`` over each tenant database and add up its counts.

    Single mode has one scope (``None``: the shared database) and returns that
    pass's result as it is. In split mode a tenant whose pass fails does not
    stop the others; its error is listed under ``errors``.
    """
    results = [await sweep(scope) for scope in await tenant_scopes()]
    if len(results) == 1:
        return results[0]
    total: dict[str, Any] = {}
    for result in results:
        for key, value in result.items():
            if key == "error":
                total.setdefault("errors", []).append(value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + value
    return total


async def _company_flag_on(
    db: Any, flag_key: str, company_id: Any, cache: dict[Any, bool],
) -> bool:
    """Whether a per-company flag is on, resolved once per company per job.

    The weekly crons iterate companies; each company's flag decides whether
    the cron does anything for it (AK-10: a declared flag is read).
    """
    if company_id not in cache:
        from src.ai.core.feature_flags import FeatureFlags
        cache[company_id] = await FeatureFlags(db).is_on(flag_key, company_id=company_id)
    return cache[company_id]

# --- Arq Jobs ---

async def run_execution_recursive(ctx: dict[str, Any], run_id_str: str,
                                  company_id: Optional[str] = None) -> Any:
    """Entry point for an execution run.

    The ``AgentLoop`` orchestrator is the sole run engine (C4). The
    ``agent_loop.enabled`` flag is stamped onto the run for the SPA but no
    longer gates engine choice. ``company_id`` names the tenant database the
    run is in.
    """
    run_id = UUID(run_id_str)
    import redis.asyncio as redis
    from src.common.config import settings

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")  # type: ignore[no-untyped-call]

    async with tenant_session(company_id) as db:
        # Resolve feature flag scope first; needs the run's company_id +
        # any entity-level override.
        from src.ai.core.feature_flags import FeatureFlags

        flags = FeatureFlags(db, redis=redis_pool)
        run_company_id, _entity_extras = await _resolve_run_flag_scope(db, run_id)

        # The AgentLoop is the sole run engine (C4). ``agent_loop.enabled`` no
        # longer gates engine choice; it is stamped onto the run below only so
        # the SPA's ExecutionDetail page renders the loop timeline.
        logger.info("[dispatch] run=%s engine=agent_loop company=%s", run_id, run_company_id)

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
        if company_id is not None and str(guard_run.company_id) != str(company_id):
            # Defence in depth: the job named another tenant than the run's.
            logger.error(
                "[dispatch] run %s belongs to company %s, not the job's %s — not run",
                run_id, guard_run.company_id, company_id,
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

        from src.ai.governance.entity_versions import run_entity
        _pinned = await run_entity(db, guard_run)  # the run's version (EP-10)
        _obs = (getattr(_pinned, "observability", None) or {}) if _pinned else {}
        _capture = bool(_obs.get("log_thoughts", True))
        recorder = TraceRecorder(
            run_id, company_id=run_company_id, redis=redis_pool,
            capture_payloads=_capture,
        )

        with set_recorder(recorder):
            from src.ai.core.agent_loop import AgentLoop

            loop = AgentLoop(
                db, redis_pool,
                company_id=run_company_id,
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
        from src.ai.governance.entity_versions import run_entity
        entity = await run_entity(db, run)  # the run's version (EP-10)
        extras = getattr(entity, "metadata_extensions", None) if entity else None
        return run.company_id, extras if isinstance(extras, dict) else None
    except Exception:
        return None, None


# arq's default max_tries: the last try refuses instead of deferring again.
_GATEWAY_RUN_TRIES = 5


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
    from src.ai.orm import ExecutionRun, RunStatus
    from src.ai.governance.subjects import gateway_subjects

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
        async with tenant_session(client_id) as db:
            # ── Which agent runs it (GW-17): the webhook endpoint's binding,
            # then the event's own entity_id, else the company's only agent.
            from src.gateway.agent_choice import choose_agent

            metadata = envelope_dict.get("metadata") or {}
            raw_payload = raw_data.get("raw", {}) if isinstance(raw_data, dict) else {}
            named = [
                metadata.get("entity_id"),
                (raw_data.get("entity_id") if isinstance(raw_data, dict) else None)
                or (raw_payload.get("entity_id") if isinstance(raw_payload, dict) else None),
            ]
            choice = await choose_agent(db, UUID(client_id), named)
            if choice.entity is None:
                logger.error(
                    f"[process_gateway_event] Not run: {choice.error} — {choice.detail} "
                    f"(company={client_id}, event={event_type}, correlation={correlation_id})"
                )
                return
            entity = choice.entity

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
            # The company's runs a minute (GH-03): past it, the job tries
            # again a minute later — the event's run is postponed, not lost.
            from src.ai.governance.run_quota import WINDOW_SECONDS, RunQuotaExceeded, require_run_slot
            try:
                await require_run_slot(client_id)
            except RunQuotaExceeded as exc:
                from arq.worker import Retry
                from src.ai.core.events import event
                tries = int(ctx.get("job_try") or 1)
                event("gateway.run_deferred", company_id=client_id, correlation_id=correlation_id,
                      job_try=tries, reason=str(exc))
                if tries < _GATEWAY_RUN_TRIES:
                    raise Retry(defer=WINDOW_SECONDS) from exc
                logger.error("[process_gateway_event] %s: refused after %d tries: %s",
                             correlation_id, tries, exc)
                return
            run = ExecutionRun(
                company_id=UUID(client_id),
                entity_id=entity.id,
                input_data={
                    "input": json.dumps(raw_data),
                    "channel": envelope_dict.get("channel", "webhook"),
                    "source": source,
                    "event_type": event_type,
                    "correlation_id": correlation_id,
                    # The event's own lead or sender, never addresses in its
                    # text: those are the sender's, not the tenant's (TL-09).
                    "subjects": gateway_subjects(source, raw_data),
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
        from arq.worker import Retry
        if isinstance(exc, Retry):
            raise  # the run quota defers the job (GH-03)
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

    Returns the campaign's id, or None when the row could not become one (the
    automation router records which, Phase 14 WS3).
    """
    from src.ai.campaign_models import Campaign, CampaignCall
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
        # Fallback: the company's admin, else its earliest user — always the
        # same one (GW-17: this was LIMIT 1 with no order).
        from sqlalchemy import case
        user_result = await db.execute(
            select(User.id).where(
                User.company_id == UUID(client_id),
                User.is_active.is_(True),
            ).order_by(
                case((User.role.in_(("tenant_admin", "partner_admin")), 0), else_=1),
                User.created_at, User.id,
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
        from src.common.job_queue import enqueue_job, tenant_arg

        job = await enqueue_job("execute_campaign_task", str(campaign.id),
                                company_id=tenant_arg(campaign.company_id))

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
    return campaign.id


async def process_document(ctx: dict[str, Any], document_id_str: str, file_content: bytes, file_type: str,
                           filename: str, company_id: Optional[str] = None) -> Any:
    """Extract an uploaded document's text and ingest it into a Knowledge Tree.

    Documents attached to an entity go into that entity's Knowledge Tree; the
    rest go into the company-wide tree every entity of the company reads.
    ``upload_status`` reflects how many chunks were embedded (searchable).
    """
    from src.ai.orm import Document
    from src.ai.memory.knowledge_tree_service import KnowledgeTreeService
    import io

    document_id = UUID(document_id_str)
    async with tenant_session(company_id) as db:
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

            kt_service = KnowledgeTreeService(db, document.company_id)
            if document.entity_id:
                tree = await kt_service.get_or_create_knowledge_tree(entity_id=document.entity_id)
            else:
                tree = await kt_service.get_or_create_company_knowledge_tree()
            node_count = await kt_service.ingest_document(
                tree_id=tree.id,
                document_id=document.id,
                content=text,
                filename=filename,
                entity_id=document.entity_id,
            )
            total_chunks, embedded = await kt_service.chunk_embedding_counts(tree.id, document.id)

            if total_chunks == 0 or embedded == 0:
                document.upload_status = "failed"
                logger.error(
                    f"Document {document.id} ({document.filename}): no searchable chunks "
                    f"({embedded}/{total_chunks} embedded)"
                )
            elif embedded < total_chunks:
                document.upload_status = "partial"
                logger.warning(
                    f"Document {document.id} ({document.filename}): "
                    f"{embedded}/{total_chunks} chunks embedded"
                )
            else:
                document.upload_status = "completed"
                logger.info(
                    f"Document {document.id} ({document.filename}): ingested {node_count} "
                    f"Knowledge Tree nodes, all {total_chunks} chunks embedded"
                )
            await db.commit()

        except Exception as e:
            await db.rollback()
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
    async with tenant_session(company_id_str) as db:
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
    Periodic cron job that enqueues a dreaming_worker job for every entity
    with memory enabled — the entities that record episodes and read the
    rules Dreaming distils. ``DreamingEngine.dream`` applies the
    CONSOLIDATION_INTERVAL_HOURS gate per entity.
    """
    from sqlalchemy import text as _text

    redis = ctx.get('redis')  # the worker's ArqRedis pool
    if redis is None:
        logger.error("Dreaming cron: no redis in worker context; nothing enqueued")
        return {"enqueued": 0}

    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        enqueued = 0
        try:
            async with tenant_session(scope) as db:
                result = await db.execute(_text(
                    "SELECT id, company_id FROM hierarchical_entities "
                    "WHERE status NOT IN ('ARCHIVED', 'DELETED') "
                    "AND capabilities->'memory'->>'enabled' = 'true'"
                ))
                entities = result.fetchall()

                for row in entities:
                    entity_id, company_id = str(row[0]), str(row[1])
                    try:
                        await redis.enqueue_job(
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

    return await _each_tenant(sweep)


# ---------------------------------------------------------------------------
# Phase E: graph_maintenance_worker — Periodic graph maintenance
# ---------------------------------------------------------------------------
async def graph_maintenance_worker(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Daily maintenance for the semantic graph: decays the weight of edges not
    traversed in 30 days, then prunes edges that reached the floor.

    Runs as one pass over all edges — ``decay_weights`` / ``prune_weak_edges``
    are not company-scoped, so looping per company would decay every edge once
    per company.
    """
    from cortex_memory.graph import SemanticGraphService

    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        async with tenant_session(scope) as db:
            try:
                # decay/prune never read company_id — maintenance spans the database's tenants.
                graph = SemanticGraphService(db, company_id=cast(UUID, None))
                decayed = await graph.decay_weights(days_inactive=30)
                pruned = await graph.prune_weak_edges()
                await db.commit()
                logger.info(f"Graph maintenance: {decayed} edges decayed, {pruned} pruned")
                return {"decayed": decayed, "pruned": pruned}
            except Exception as e:
                logger.error(f"Graph maintenance worker failed: {e}")
                return {"error": str(e)}

    return await _each_tenant(sweep)

# ---------------------------------------------------------------------------
# Resume_execution — Arq job to resume a checkpointed run
# ---------------------------------------------------------------------------
async def resume_execution(ctx: dict[str, Any], run_id_str: str,
                           company_id: Optional[str] = None) -> dict[str, Any]:
    """
    Resume a previously checkpointed execution run.
    Reloads `run.context_state` and skips steps that are already completed.
    """
    run_id = UUID(run_id_str)
    async with tenant_session(company_id) as db:
        redis = ctx.get('redis')
        from src.ai.core.agent_loop import AgentLoop
        run_company_id, _entity_extras = await _resolve_run_flag_scope(db, run_id)
        logger.info(f"Resuming ExecutionRun: {run_id}")
        return await AgentLoop(db, redis, company_id=run_company_id).run(run_id)


async def resume_parent_run(ctx: dict[str, Any], parent_run_id_str: str,
                            company_id: Optional[str] = None) -> dict[str, Any]:
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
        async with tenant_session(company_id) as db:
            from src.ai.core.agent_loop import AgentLoop
            from src.ai.core.feature_flags import FeatureFlags
            from src.ai.core.trace import TraceRecorder, set_recorder

            flags = FeatureFlags(db, redis=redis_pool)
            run_company_id, _entity_extras = await _resolve_run_flag_scope(db, parent_run_id)
            recorder = TraceRecorder(parent_run_id, company_id=run_company_id, redis=redis_pool)
            with set_recorder(recorder):
                loop = AgentLoop(
                    db, redis_pool, company_id=run_company_id, feature_flags=flags,
                )
                return await loop.resume(parent_run_id)
    finally:
        await redis_pool.close()


async def resume_paused_run(ctx: dict[str, Any], run_id_str: str,
                            company_id: Optional[str] = None) -> dict[str, Any]:
    """Resume a run parked on a HITL approval (GH-07, ``core/approval_pause``).

    Enqueued when the reviewer answers, at the approval's deadline, and by the
    stuck-run sweep. Idempotent: ``AgentLoop.resume_after_approval`` does
    nothing while the approval is pending, and only one resume claims the run.
    """
    run_id = UUID(run_id_str)
    import redis.asyncio as redis
    from src.common.config import settings

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")  # type: ignore[no-untyped-call]
    try:
        async with tenant_session(company_id) as db:
            from src.ai.core.agent_loop import AgentLoop
            from src.ai.core.feature_flags import FeatureFlags
            from src.ai.core.trace import TraceRecorder, set_recorder

            run_company_id, _entity_extras = await _resolve_run_flag_scope(db, run_id)
            recorder = TraceRecorder(run_id, company_id=run_company_id, redis=redis_pool)
            with set_recorder(recorder):
                loop = AgentLoop(db, redis_pool, company_id=run_company_id,
                                 feature_flags=FeatureFlags(db, redis=redis_pool))
                return await loop.resume_after_approval(run_id)
    finally:
        await redis_pool.close()


async def resume_waiting_run(ctx: dict[str, Any], run_id_str: str,
                             company_id: Optional[str] = None) -> dict[str, Any]:
    """Resume a run parked on ``wait_for_event`` (Phase 14 WS3, ``automation.waits``).

    Enqueued by the router when an event answers the wait, by the scheduler at
    its deadline, when an operator cancels it, and by the event worker's sweep
    for a resume that was lost. Idempotent: ``AgentLoop.resume_after_wait``
    does nothing while the wait is open, and only one resume claims the run.
    """
    run_id = UUID(run_id_str)
    import redis.asyncio as redis
    from src.common.config import settings

    redis_pool = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")  # type: ignore[no-untyped-call]
    try:
        async with tenant_session(company_id) as db:
            from src.ai.core.agent_loop import AgentLoop
            from src.ai.core.feature_flags import FeatureFlags
            from src.ai.core.trace import TraceRecorder, set_recorder

            run_company_id, _entity_extras = await _resolve_run_flag_scope(db, run_id)
            recorder = TraceRecorder(run_id, company_id=run_company_id, redis=redis_pool)
            with set_recorder(recorder):
                loop = AgentLoop(db, redis_pool, company_id=run_company_id,
                                 feature_flags=FeatureFlags(db, redis=redis_pool))
                return await loop.resume_after_wait(run_id)
    finally:
        await redis_pool.close()


async def sweep_stuck_runs(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron: runs stuck in WAITING_ON_CHILDREN (AK-03, see ``core/stuck_runs``),
    and runs parked on an approval whose resume was lost (GH-07)."""
    from src.ai.core.approval_pause import sweep_paused_runs
    from src.ai.core.stuck_runs import sweep_waiting_runs
    from src.common.config import settings

    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        async with tenant_session(scope) as db:
            swept = await sweep_waiting_runs(
                db, ctx.get("redis"),
                grace_s=settings.WAITING_RESUME_GRACE_SECONDS,
                timeout_s=settings.WAITING_ON_CHILDREN_TIMEOUT_SECONDS,
            )
            swept["paused_resumed"] = await sweep_paused_runs(
                db, grace_s=settings.WAITING_RESUME_GRACE_SECONDS)
            return swept

    return await _each_tenant(sweep)


# ---------------------------------------------------------------------------
# Scheduled CORTEX wake-ups — Arq cron job
# ---------------------------------------------------------------------------
async def cortex_resume_scheduled(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron: wake the suspended CORTEX trees whose ``next_resume_at`` has passed.

    Each tree gets a new ``PENDING`` run carrying ``cortex_tree_id`` (the run
    reopens that tree, ``memory/run_memory``), queued on the worker's own pool.
    The run is committed before it is queued, so the worker always finds it,
    and the tree's schedule is cleared only once the job is queued (MC-24).
    Before, the job went through a re-wrapped pool that raised; the error was
    logged per tree, and the commit after the loop kept a run nobody would
    pick up and a tree with no schedule, never woken again.

    A tree whose job cannot be queued keeps its schedule, so the next tick
    tries again, and its run is marked ``FAILED`` with the reason.
    """
    from src.ai.memory.cortex_models import CortexTree, CortexTreeStatus

    redis = ctx.get("redis")  # the worker's ArqRedis pool
    if redis is None:
        logger.error("CORTEX scheduled resume: no redis in worker context; nothing woken")
        return {"resumed": 0, "failed": 0}

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # next_resume_at is naive UTC

    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        async with tenant_session(scope) as db:
            due = (await db.execute(
                select(CortexTree.id).where(
                    CortexTree.status == CortexTreeStatus.SUSPENDED,
                    CortexTree.next_resume_at.is_not(None),
                    CortexTree.next_resume_at <= now,
                )
            )).scalars().all()

        counts = {"resumed": 0, "failed": 0}
        for tree_id in due:
            try:
                outcome = await _wake_scheduled_tree(redis, tree_id, now, scope)
            except Exception:
                logger.exception("CORTEX scheduled resume failed for tree %s", tree_id)
                outcome = "failed"
            if outcome in counts:
                counts[outcome] += 1
        return counts

    return await _each_tenant(sweep)


async def _wake_scheduled_tree(redis: Any, tree_id: UUID, now: datetime,
                               scope: Optional[UUID] = None) -> str:
    """Wake one tree: ``resumed``, ``failed`` (it keeps its schedule) or ``skipped``.

    ``scope``: the tenant database the tree is in (``None``: the shared one).
    """
    from sqlalchemy import update

    from src.ai.memory.cortex_models import CortexTree, CortexTreeStatus
    from src.common.job_queue import enqueue_on, tenant_arg

    async with tenant_session(scope) as db:
        tree = await db.get(CortexTree, tree_id)
        # Resumed, rescheduled or deleted since the scan.
        if (tree is None or tree.status != CortexTreeStatus.SUSPENDED
                or tree.next_resume_at is None or tree.next_resume_at > now):
            return "skipped"
        scheduled_for = tree.next_resume_at
        run = ExecutionRun(
            entity_id=tree.entity_id,
            company_id=tree.company_id,
            user_id=tree.user_id,
            input_data={"cortex_tree_id": str(tree_id)},
            status=RunStatus.PENDING.value,
        )
        db.add(run)
        await db.flush()
        run_id, company_id = run.id, run.company_id
        await db.commit()

    try:
        await enqueue_on(redis, "run_execution_recursive", str(run_id), company_id=tenant_arg(company_id))
    except Exception as exc:
        logger.error("CORTEX scheduled resume: run %s for tree %s was not queued (%s); "
                     "the tree keeps its schedule", run_id, tree_id, exc)
        async with tenant_session(scope) as db:
            failed_run = await db.get(ExecutionRun, run_id)
            if failed_run is not None:
                failed_run.status = RunStatus.FAILED.value
                failed_run.error_message = f"Scheduled CORTEX resume could not be queued: {exc}"
                failed_run.completed_at = datetime.now(timezone.utc)
                await db.commit()
        return "failed"

    async with tenant_session(scope) as db:
        # Only the schedule this run answered: a tree rescheduled meanwhile keeps the new time.
        await db.execute(
            update(CortexTree)
            .where(CortexTree.id == tree_id, CortexTree.next_resume_at == scheduled_for)
            .values(next_resume_at=None)
        )
        await db.commit()
    logger.info("CORTEX scheduled resume: tree %s -> run %s", tree_id, run_id)
    return "resumed"


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
    from sqlalchemy import text

    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        try:
            async with tenant_session(scope) as db:
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
        except Exception as e:                                              # noqa: BLE001
            logger.error(f"kpi_rollup_refresh error: {e}")
            return {"error": str(e)}

    return await _each_tenant(sweep)


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
        async with tenant_session(company_id_str) as db:
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
    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        try:
            async with tenant_session(scope) as db:
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
                enabled: dict[Any, bool] = {}
                for company_id in company_ids:
                    if not await _company_flag_on(
                        db, "critic_pipeline.calibration_enabled", company_id, enabled,
                    ):
                        continue
                    results = await CriticCalibrator(db, company_id).run()
                    entities_scored += len(results)
                    samples_total += sum(r.samples for r in results)
                await db.commit()
                return {
                    "companies_scored": len(company_ids),
                    "entities_scored": entities_scored,
                    "samples_total": samples_total,
                }
        except Exception as e:                                              # noqa: BLE001
            logger.error(f"critic_calibration_job error: {e}")
            return {"error": str(e)}

    return await _each_tenant(sweep)


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
    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        return await _skill_promotion_scan_one(scope)

    return await _each_tenant(sweep)


async def _skill_promotion_scan_one(scope: Optional[UUID]) -> dict[str, Any]:
    """``skill_promotion_scan`` over one tenant database."""
    try:
        from sqlalchemy import distinct, select
        from src.ai.meta.skill_library import SkillLibrary
        from src.ai.orm.entity import HierarchicalEntity
        from src.ai.orm.execution import ExecutionRun

        proposed_per_entity: dict[str, int] = {}
        async with tenant_session(scope) as db:
            entity_rows = (await db.execute(
                select(distinct(ExecutionRun.entity_id))
                .where(ExecutionRun.entity_id.is_not(None))
                .limit(500)
            )).scalars().all()
            enabled: dict[Any, bool] = {}
            for entity_id in entity_rows:
                ent = (await db.execute(
                    select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
                )).scalar_one_or_none()
                if ent is None or ent.company_id is None:
                    continue
                if not await _company_flag_on(
                    db, "meta_agent.skill_promotion_cron", ent.company_id, enabled,
                ):
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
    async def sweep(scope: Optional[UUID]) -> dict[str, Any]:
        return await _meta_agent_prompt_evolution_one(scope)

    return await _each_tenant(sweep)


async def _meta_agent_prompt_evolution_one(scope: Optional[UUID]) -> dict[str, Any]:
    """``meta_agent_prompt_evolution`` over one tenant database."""
    try:
        from sqlalchemy import select
        from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
        from src.ai.orm.entity import HierarchicalEntity
        from src.ai.orm.execution import ExecutionRun

        proposed = 0
        async with tenant_session(scope) as db:
            # Find Meta-Agent entities (flagged via metadata_extensions.is_meta_agent).
            ents = (await db.execute(select(HierarchicalEntity).limit(500))).scalars().all()
            meta_entities = [
                e for e in ents
                if isinstance(e.metadata_extensions, dict)
                and e.metadata_extensions.get("is_meta_agent")
            ]
            enabled: dict[Any, bool] = {}
            for me in meta_entities:
                if me.company_id is None:
                    continue
                if not await _company_flag_on(
                    db, "meta_agent.prompt_evolution_cron", me.company_id, enabled,
                ):
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
