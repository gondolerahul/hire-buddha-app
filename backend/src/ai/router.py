from contextlib import asynccontextmanager, nullcontext
from fastapi import APIRouter, Depends, HTTPException, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import Any, AsyncIterator, List, Optional
from src.auth.dependencies import get_current_user, get_current_user_from_query, RoleChecker
from src.common.tenancy.session import (
    get_acting_tenant_db, get_acting_tenant_db_from_query, get_control_db, get_tenant_db,
    is_split, tenant_db_for, tenant_session,
)
from src.auth.visibility import in_scope, visible_company_ids
from src.auth.models import User
from src.auth.roles import ADMIN_ROLES
from src.ai.schemas import (
    HierarchicalEntityCreateRequest, HierarchicalEntityUpdateRequest, HierarchicalEntityResponse,
    ExecutionRunCreate, ExecutionRunResponse, ExecutionRunSummary, EntityType,
    DocumentResponse, DocumentSearchResult, ExecutionRefineRequest, CSATRequest,
    DocumentDetail, DocumentUpdate, ApprovalDecision, EntityDeleted,
)
from src.ai.service import AIService
from src.common.pagination import CursorParam, LimitParam, Page, keyset, page_of
from src.ai.services.knowledge_base import KnowledgeBaseService, file_type_of
from src.ai.artifact_router import public_file_url
from src.billing.features import require_feature

router = APIRouter(prefix="/ai", tags=["AI Hierarchical Agent Platform"])

# Which database each route works in (Phase 14 WS2 2.4): the caller's own
# company's (``get_tenant_db``); for the routes that read or change another
# company's agents or runs, the acting company's (``get_acting_tenant_db``,
# the ``X-Company-Id`` header); a company the route names, or the template
# library, through ``tenant_db_for``. With TENANCY_MODE=single every one of
# them is the request's one session, as ``get_db`` was.


@asynccontextmanager
async def _template_library(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """The session holding the template library: the platform (APP) company's (PO-23)."""
    owner = None
    if is_split():
        from src.auth.platform import platform_company_id

        owner = await platform_company_id(db)
        if owner is None:
            raise HTTPException(status_code=409, detail="There is no platform (APP) company to own templates")
    async with tenant_db_for(db, owner) as library:
        yield library


def _shown(entity) -> HierarchicalEntityResponse:
    """One entity as the read and update routes show it.

    An entity with no static steps shows the default step it would run
    (``planning.default_step``), so the builder and the execute form have the
    inputs to ask for — at every level. Computed for the response only; the
    stored row is never changed (EP-27).
    """
    from src.ai.planning.default_step import display_planning
    from src.ai.schemas.planning import Planning

    response = HierarchicalEntityResponse.model_validate(entity)
    planning = display_planning(entity)
    if planning is not entity.planning:
        response.planning = Planning.model_validate(planning)
    return response


# --- Entities ---
@router.post("/entities", response_model=HierarchicalEntityResponse)
async def create_entity(
    entity_in: HierarchicalEntityCreateRequest,
    target_company_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    # Determine the effective company for this entity: any company the caller
    # can see (partners: their tenants too; app_admin: any).
    effective_company_id = current_user.company_id
    if target_company_id:
        if not in_scope(await visible_company_ids(db, current_user), target_company_id):
            raise HTTPException(status_code=403, detail="Not authorized to create entities for this company")
        from src.partners.access import check_target   # a partner: under an access grant (T8-4)
        await check_target(db, user=current_user, company_id=target_company_id, method="POST",
                           path="/api/v1/ai/entities")
        effective_company_id = target_company_id

    # The entity lives in its company's database; a template in the library's.
    target = _template_library(db) if entity_in.is_template else tenant_db_for(db, effective_company_id)
    async with target as entity_db:
        service = AIService(entity_db)
        return await service.create_entity(entity_in, effective_company_id, current_user.id,
                                           user_role=current_user.role)

@router.get("/entities", response_model=Page[HierarchicalEntityResponse])
async def list_entities(
    type: Optional[EntityType] = None,
    company_id: Optional[UUID] = None,
    voice_enabled: Optional[bool] = None,
    status: Optional[str] = None,
    include_deleted: bool = Query(False, description=(
        "Admins only: include soft-deleted entities (status DELETED, deleted_at set) — API-18")),
    limit: int = LimitParam(),
    cursor: Optional[str] = CursorParam(),
    db: AsyncSession = Depends(get_acting_tenant_db),
    control_db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    """One page of the entities the caller may see, newest first (API-16:
    ``items``, ``next_cursor``, ``limit``)."""
    # Every company the caller can see — partners include their tenants, in one
    # query (it was one query per tenant). app_admin sees all, or one company
    # with ?company_id=.
    if include_deleted and current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="include_deleted is for admins")
    scope = await visible_company_ids(control_db, current_user)
    named = company_id and current_user.role == "app_admin"
    if named:
        scope = frozenset({company_id})

    from src.ai.orm import HierarchicalEntity

    async with (tenant_db_for(control_db, company_id) if named else nullcontext(db)) as list_db:
        query = AIService(list_db).entities_query(
            scope, type, is_template=False, voice_enabled=voice_enabled, status_filter=status,
            include_deleted=include_deleted,
        )
        query = keyset(query, HierarchicalEntity.created_at, HierarchicalEntity.id, cursor, limit)
        return page_of((await list_db.execute(query)).scalars().all(), limit)

@router.get("/entities/{entity_id}", response_model=HierarchicalEntityResponse)
async def get_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    entity = await service.get_entity(entity_id, current_user.company_id, current_user.role)
    response = _shown(entity)
    gov = entity.governance if isinstance(entity.governance, dict) else {}
    if response.governance is not None and gov.get("max_cost_usd") and not gov.get("max_bill"):
        # An agent saved before budgets were billed: its cap as the amount it bills (Phase 15 T5-7).
        from src.ai.schemas.governance import MaxBill
        from src.billing.agent_budget import max_bill_of
        bill = await max_bill_of(db, entity.company_id, gov)
        if bill:
            response.governance.max_bill = MaxBill(amount=bill["amount"], currency=bill["currency"])
    return response

@router.put("/entities/{entity_id}", response_model=HierarchicalEntityResponse)
async def update_entity(
    entity_id: UUID,
    entity_in: HierarchicalEntityUpdateRequest,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return _shown(await service.update_entity(entity_id, entity_in, current_user.company_id, user_role=current_user.role, user_id=current_user.id))

_SOFT_DELETE = (
    "A **soft delete**: the entity and every descendant keep their rows — their runs, usage "
    "and billing still point at them — with `status` `DELETED` and `deleted_at` set. "
    "Documents, artifacts, call logs and phone numbers are unlinked from them. They are left "
    "out of every list unless an admin passes `include_deleted=true`. Returns the ids deleted "
    "(API-18)."
)


@router.delete("/entities/{entity_id}", response_model=EntityDeleted,
               summary="Soft-delete an entity and its descendants", description=_SOFT_DELETE)
async def delete_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.delete_entity(entity_id, current_user.company_id, user_role=current_user.role)

@router.post("/entities/{entity_id}/convert-to-template", response_model=HierarchicalEntityResponse)
async def convert_entity_to_template(
    entity_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    control_db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(RoleChecker(["app_admin"]))
):
    """
    Deep-clone an existing entity (and all its children) into a parallel
    template hierarchy.  The original entities are left untouched.
    Requires app_admin role.
    """
    async with _template_library(control_db) as library:
        service = AIService(db)
        return await service.convert_to_template(entity_id, current_user.company_id, current_user.id,
                                                 library_db=library)

# --- Dashboard ---
@router.get("/stats", response_model=dict)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_dashboard_stats(current_user.company_id, current_user.role)

# --- Executions ---
@router.post("/execute", response_model=ExecutionRunResponse)
async def trigger_execution(
    execution_in: ExecutionRunCreate,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Start a run. A partner or staff member working in a tenant (``X-Company-Id``)
    starts the tenant's run, paid by the tenant's credits (D54)."""
    service = AIService(db)
    return await service.trigger_execution(execution_in, current_user.company_id, current_user.id, user_role=current_user.role)

@router.get("/executions", response_model=Page[ExecutionRunSummary])
async def list_executions(
    limit: int = LimitParam(),
    cursor: Optional[str] = CursorParam(),
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """One page of the caller's top-level runs, newest first (API-16)."""
    from src.ai.orm import ExecutionRun

    query = AIService(db).executions_query(current_user.company_id, current_user.role)
    query = keyset(query, ExecutionRun.created_at, ExecutionRun.id, cursor, limit)
    return page_of((await db.execute(query)).unique().scalars().all(), limit)

@router.get("/executions/{execution_id}", response_model=ExecutionRunResponse)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    execution = await service.get_execution(execution_id, current_user.company_id, current_user.role)
    return execution

@router.post("/executions/{execution_id}/csat", response_model=ExecutionRunResponse)
async def record_execution_csat(
    execution_id: UUID,
    payload: CSATRequest,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user),
):
    """Capture a +1/-1 CSAT rating on a completed run (Phase 12 `07` §6)."""
    service = AIService(db)
    return await service.record_csat(
        execution_id, current_user.company_id,
        payload.score, payload.comment, current_user.role,
    )

@router.get("/executions/{execution_id}/agent_state")
async def get_agent_state(
    execution_id: UUID,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 11 Track 2 — read the latest AgentState snapshot for a run.

    Debug endpoint only. Returns the most recent CORTEX ``snapshot``
    node payload (or 404 if none exists). Visible to superadmins and
    to anyone with execution-read access in the same company; access
    enforcement piggybacks on AIService.get_execution.
    """
    from fastapi import HTTPException

    from src.ai.service import AIService

    # Reuse existing access check.
    service = AIService(db)
    await service.get_execution(execution_id, current_user.company_id, current_user.role)

    # Walk the run's CORTEX tree (if any) for the newest snapshot node.
    try:
        from sqlalchemy import text
        row = (await db.execute(
            text(
                """
                SELECT n.content, n.created_at
                FROM cortex_nodes n
                JOIN cortex_trees t ON t.id = n.tree_id
                JOIN execution_runs r ON r.id = :rid
                WHERE t.entity_id = r.entity_id
                  AND n.node_type = 'snapshot'
                  AND n.created_at >= COALESCE(r.started_at, r.created_at)
                  AND (r.completed_at IS NULL
                       OR n.created_at <= r.completed_at + interval '120 seconds')
                ORDER BY n.created_at DESC
                LIMIT 1
                """
            ),
            {"rid": str(execution_id)},
        )).first()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"snapshot lookup failed: {exc}")

    if row is None:
        raise HTTPException(status_code=404, detail="no AgentState snapshot")

    import json as _json
    try:
        payload = _json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception:
        payload = {"raw": str(row[0])}
    return {
        "run_id": str(execution_id),
        "snapshot_at": row[1].isoformat() if row[1] else None,
        "snapshot": payload,
    }


@router.get("/executions/{execution_id}/trace")
async def get_execution_trace(
    execution_id: UUID,
    iteration: Optional[int] = None,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user),
):
    """Per-iteration transparency trace for a run.

    Returns every ``execution_trace_events`` span (steps → child invocations →
    tool calls → LLM calls), ordered by ``seq``. The frontend assembles the tree
    from ``span_id`` / ``parent_span_id``. Optionally filter to one ``iteration``.

    Access is enforced via the same ``AIService.get_execution`` check used by the
    SSE stream and the agent-state snapshot endpoint.
    """
    from sqlalchemy import select as _select

    from src.ai.orm.trace import ExecutionTraceEvent

    service = AIService(db)
    await service.get_execution(execution_id, current_user.company_id, current_user.role)

    stmt = (
        _select(ExecutionTraceEvent)
        .where(ExecutionTraceEvent.run_id == execution_id)
        .order_by(ExecutionTraceEvent.seq.asc())
    )
    if iteration is not None:
        stmt = stmt.where(ExecutionTraceEvent.iteration == iteration)

    rows = (await db.execute(stmt)).scalars().all()
    return {
        "run_id": str(execution_id),
        "count": len(rows),
        "spans": [
            {
                "span_id": str(r.span_id),
                "parent_span_id": str(r.parent_span_id) if r.parent_span_id else None,
                "iteration": r.iteration,
                "kind": r.kind,
                "name": r.name,
                "status": r.status,
                "seq": r.seq,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "duration_ms": r.duration_ms,
                "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "child_run_id": str(r.child_run_id) if r.child_run_id else None,
                "payload": r.payload,
                "error": r.error_message,
            }
            for r in rows
        ],
    }


# Never cache the stream, and tell every intermediary not to transform it:
# Apache's mod_deflate (enabled by setup_apache.sh) honours ``no-transform``, so
# frames are neither compressed nor held back. ``X-Accel-Buffering`` was an
# nginx-only header and did nothing behind Apache (GW-09).
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform"}


# With nothing to send for this long, the stream sends a keep-alive comment and
# checks that the run is still going.
SSE_IDLE_SECONDS = 15


async def _stored_run_status(run_id: UUID, company_id: Any = None) -> Optional[str]:
    """The run's status as stored now, read on a session of its own (the
    request's session is not the stream's to use), in the run's tenant database."""
    from src.ai.orm import ExecutionRun

    async with tenant_session(company_id) as session:
        status = (await session.execute(
            select(ExecutionRun.status).where(ExecutionRun.id == run_id)
        )).scalar_one_or_none()
    return None if status is None else str(status)


@router.get("/executions/{execution_id}/stream")
async def stream_execution(
    execution_id: UUID,
    request: Request,
    last_event_id: Optional[str] = None,
    db: AsyncSession = Depends(get_acting_tenant_db_from_query),
    current_user: User = Depends(get_current_user_from_query)
):
    """The run's live frames as server-sent events (GW-18, GW-19).

    Reads the run's Redis stream (``ai/core/run_stream.py``) from the start, or
    from after the client's last frame — the ``Last-Event-ID`` header the
    browser sends when it reconnects by itself, or ``?last_event_id=`` from a
    client that opens a new stream — so a reconnect misses nothing. Every frame
    carries its stream id as the SSE ``id:``. The stream ends after the frame
    marked ``terminal``. With nothing to send for ``SSE_IDLE_SECONDS`` it sends
    a keep-alive comment; and when the run has finished with no terminal frame
    left to send (its frames expired, or it ended outside the loop), it ends
    with a terminal ``run_end`` of the stored status.
    """
    service = AIService(db)
    run = await service.get_execution(execution_id, current_user.company_id, current_user.role)
    run_company_id = run.company_id

    import json
    import logging
    from fastapi.responses import StreamingResponse
    import redis.asyncio as redis
    from src.ai.core.run_stream import is_terminal, is_terminal_status, read_run_events, start_id
    from src.common.config import settings
    import asyncio

    resume_after = start_id(request.headers.get("last-event-id") or last_event_id)
    # Tenants and partners see billed amounts only (Phase 15 T9-3).
    from src.billing.money_view import is_staff, sse_data
    viewer = None if is_staff(current_user.role) else (str(current_user.role), current_user.company_id)

    async def event_generator():
        r = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")
        after = resume_after
        wait = None  # the first read does not wait: a finished run ends at once
        try:
            yield "data: {\"status\": \"connected\"}\n\n"
            while True:
                frames = await read_run_events(r, execution_id, after, block_ms=wait)
                for entry_id, data in frames:
                    after = entry_id
                    yield f"id: {entry_id}\ndata: {await sse_data(viewer, data)}\n\n"
                    if is_terminal(data):
                        return
                if not frames:
                    status = await _stored_run_status(execution_id, run_company_id)
                    if status is None or is_terminal_status(status):
                        last = {"type": "run_end", "outcome": status, "terminal": True}
                        yield f"data: {json.dumps(last)}\n\n"
                        return
                    if wait is not None:
                        yield ": keep-alive\n\n"
                wait = SSE_IDLE_SECONDS * 1000
        except asyncio.CancelledError:
            pass
        except redis.RedisError as exc:
            # The page falls back to polling when its stream drops.
            logging.getLogger(__name__).warning("run stream %s: %s", execution_id, exc)
        finally:
            await r.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

# --- Cancel ---
@router.post("/executions/{execution_id}/cancel", response_model=ExecutionRunResponse)
async def cancel_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_acting_tenant_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel an in-flight execution run.

    Sets the run to the terminal ``CANCELLED`` state and publishes on the
    run's stream (``run_events:{id}``). A running AgentLoop re-reads the run
    status at the top of every iteration and aborts, so an operator can stop
    a spinning run without killing the arq worker.
    """
    service = AIService(db)
    return await service.cancel_execution(
        execution_id, current_user.company_id, current_user.role
    )

# --- Retry / Resume ---
@router.post("/executions/{execution_id}/retry", response_model=ExecutionRunResponse)
async def retry_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retry a FAILED execution by creating a new run that resumes from the
    failed run's context_state. The CORTEX tree (if any) is resumed rather
    than re-created, and already-completed steps are skipped.
    """
    service = AIService(db)
    return await service.retry_execution(execution_id, current_user.company_id, current_user.id)

# --- Refine (Iterative Refinement) ---
@router.post("/executions/{execution_id}/refine", response_model=ExecutionRunResponse)
async def refine_execution(
    execution_id: UUID,
    refine_in: ExecutionRefineRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    """
    Refine a COMPLETED execution by providing feedback.

    Creates a new run that selectively re-executes only the steps
    affected by the user's feedback, reusing cached outputs for unchanged steps.
    The system uses an LLM to auto-detect which steps need re-running.
    """
    service = AIService(db)
    return await service.refine_execution(
        execution_id, refine_in, current_user.company_id, current_user.id
    )

# --- HITL (Human-In-The-Loop) ---
@router.get("/approvals/pending", response_model=List[dict])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    approvals = await service.get_pending_approvals(current_user.company_id)
    return [
        {
            "id": str(a.id),
            "run_id": str(a.run_id),
            "checkpoint_trigger": a.checkpoint_trigger,
            "status": a.status,
            "requested_at": a.requested_at,
            "timeout_ms": a.timeout_ms,
            # What the reviewer is approving — see governance/hitl_snapshot.py.
            "context_snapshot": a.context_snapshot or {},
        }
        for a in approvals
    ]

@router.post("/approvals/{approval_id}/respond")
async def respond_to_approval(
    approval_id: UUID,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Answer one of your company's pending approvals: ``{"status": "APPROVED" | "REJECTED", "notes"?}``.

    A schema change an agent proposed (Phase 14 WS4, D20) is decided by owners
    and admins; the answer applies or rejects it.
    """
    from src.ai.orm import HumanApproval
    from src.schema_engine import approvals as schema_approvals

    pending = (await db.execute(select(HumanApproval).where(
        HumanApproval.id == approval_id, HumanApproval.company_id == current_user.company_id))).scalar_one_or_none()
    change_id = schema_approvals.change_of(pending) if pending is not None else None
    if change_id and current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Owners and admins decide changes to the business's data")
    service = AIService(db)
    approval = await service.respond_to_approval(
        approval_id, decision.status, current_user.id, decision.notes,
        company_id=current_user.company_id,
    )
    if change_id:
        change = await schema_approvals.decided_in_inbox(current_user.company_id, change_id,
                                                         approved=decision.status == "APPROVED",
                                                         user_id=current_user.id)
        return {"status": "success", "decision": decision.status, "schema_change": change}

    # The run is parked PAUSED on this approval, holding no worker (GH-07):
    # resume it now. Best-effort — the stuck-run sweep resumes a run whose
    # approval was decided and nobody picked it up.
    from src.ai.core.approval_pause import enqueue_resume
    await enqueue_resume(approval.run_id, job_id=f"hitl-decided:{approval_id}",
                         company_id=current_user.company_id)

    return {"status": "success", "decision": decision.status}

# --- Tools ---
# --- Context Source Upload ---
@router.post("/context-sources/upload", dependencies=[Depends(require_feature("feature.knowledge.base"))], response_model=dict)
async def upload_context_source(
    file: UploadFile = File(...),
    entity_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a file as a context source for an entity.
    
    Saves as an Artifact, extracts text content for text-based files,
    and ingests into a CORTEX tree. Returns artifact metadata for
    the frontend to store as a context source reference.
    
    Max file size: 500 MB.
    Supported: PDF, DOCX, TXT, CSV, XLSX, PPTX, images, audio, video.
    """
    from src.ai.artifact_service import ArtifactService
    import mimetypes

    # Validate file size (500 MB max)
    MAX_SIZE = 500 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, f"File too large. Maximum size is 500 MB.")

    # Determine file category from MIME type
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if mime.startswith("image/"):
        file_category = "images"
    elif mime.startswith("video/"):
        file_category = "videos"
    elif mime.startswith("audio/"):
        file_category = "recordings"
    else:
        file_category = "documents"

    # Save as artifact
    art_svc = ArtifactService(db)
    artifact = await art_svc.save_artifact(
        file_bytes=content,
        file_name=file.filename or "upload",
        mime_type=mime,
        file_category=file_category,
        origin="user-uploads",
        company_id=current_user.company_id,
        agent_id=entity_id,
        purpose=f"Context source document for entity",
        generated_by="context-source-upload",
    )

    # For text-based documents, also create a Document record for RAG
    text_extensions = {"pdf", "txt", "csv", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "md", "json", "xml", "html"}
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    
    doc_id = None
    if ext in text_extensions:
        try:
            service = AIService(db)
            document = await service.upload_document(
                file_content=content,
                filename=file.filename or "upload",
                file_type=ext,
                company_id=current_user.company_id,
                entity_id=entity_id,
            )
            doc_id = str(document.id)
        except Exception as doc_err:
            # Non-fatal: artifact is already saved
            import logging
            logging.getLogger(__name__).warning(f"Document creation failed for context source: {doc_err}")

    # Auto-add to entity's context_sources if entity_id is provided
    if entity_id:
        try:
            from src.ai.orm import HierarchicalEntity
            from sqlalchemy import select
            import copy
            
            result = await db.execute(
                select(HierarchicalEntity).where(HierarchicalEntity.id == entity_id)
            )
            entity = result.scalar_one_or_none()
            if entity:
                caps = copy.deepcopy(entity.capabilities or {})
                ctx_eng = caps.setdefault("context_engineering", {})
                sources = ctx_eng.setdefault("context_sources", [])
                
                # Add new context source entry
                sources.append({
                    "source_type": "DOCUMENT",
                    "reference_id": str(artifact.id),
                    "description": file.filename or "Uploaded document",
                    "file_name": file.filename or "upload",
                    "file_type": mime,
                    "file_size": artifact.file_size,
                })
                
                entity.capabilities = caps
                await db.commit()
                
                import logging
                logging.getLogger(__name__).info(
                    f"Auto-added context source {artifact.id} to entity {entity_id} "
                    f"(now has {len(sources)} source(s))"
                )
        except Exception as ctx_err:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to auto-add context source to entity {entity_id}: {ctx_err}"
            )

    return {
        "artifact_id": str(artifact.id),
        "document_id": doc_id,
        "file_name": artifact.file_name,
        "file_size": artifact.file_size,
        "mime_type": artifact.mime_type,
        "file_category": artifact.file_category,
    }

# --- Documents (the Knowledge Base, stored in CORTEX Knowledge Trees) ---
@router.post("/documents/upload", dependencies=[Depends(require_feature("feature.knowledge.base"))], response_model=dict)
async def upload_document(
    file: UploadFile = File(...),
    entity_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Upload a document; omit ``entity_id`` to share it with every agent in the company."""
    file_content = await file.read()
    document = await KnowledgeBaseService(db, current_user.company_id).upload(
        file_content, file.filename, file_type_of(file.filename), entity_id=entity_id,
    )
    return {"id": str(document.id), "status": document.upload_status}

@router.post("/avatar/upload", response_model=dict)
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Upload an avatar image for an entity. Returns the public URL.

    Kept as a public artifact of the company and served by
    ``GET /api/v1/files/{id}/public`` — a signed storage link on Azure — instead
    of a file under the static ``/artifact`` mount (Phase 14 WS1 1.3).
    """
    import mimetypes
    import uuid as _uuid

    from src.ai.artifact_service import ArtifactService, ORIGIN_USER

    allowed = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        raise HTTPException(400, f"File type '.{ext}' not allowed. Use: {', '.join(allowed)}")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Avatar must be under 5 MB")

    filename = f"{_uuid.uuid4().hex[:12]}.{ext}"
    artifact = await ArtifactService(db).save_artifact(
        file_bytes=content, file_name=filename,
        mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        file_category="images", origin=ORIGIN_USER, company_id=current_user.company_id,
        purpose="Agent avatar", generated_by="user-upload:entity-avatar",
        extra_metadata={"public": True},
    )
    return {"url": public_file_url(artifact.id, current_user.company_id), "filename": filename}

@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    entity_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    return await KnowledgeBaseService(db, current_user.company_id).list(entity_id)

@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """One document with its ingestion outline and a text preview."""
    return await KnowledgeBaseService(db, current_user.company_id).get(document_id)

@router.patch("/documents/{document_id}", response_model=DocumentDetail)
async def update_document(
    document_id: UUID,
    body: DocumentUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Rename and/or re-scope a document (``entity_id: null`` = company-wide)."""
    return await KnowledgeBaseService(db, current_user.company_id).update(
        document_id, filename=body.filename,
        move="entity_id" in body.model_fields_set, entity_id=body.entity_id,
    )

@router.post("/documents/{document_id}/file", dependencies=[Depends(require_feature("feature.knowledge.base"))], response_model=dict)
async def replace_document_file(
    document_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Replace a document's content; it is re-ingested under the same id."""
    file_content = await file.read()
    document = await KnowledgeBaseService(db, current_user.company_id).replace_file(
        document_id, file_content, file.filename, file_type_of(file.filename),
    )
    return {"id": str(document.id), "status": document.upload_status}

@router.delete("/documents/{document_id}", response_model=dict)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a document and every Knowledge Tree node ingested from it."""
    removed = await KnowledgeBaseService(db, current_user.company_id).delete(document_id)
    return {"id": str(document_id), "deleted": True, "nodes_removed": removed}

@router.post("/documents/search", response_model=List[dict])
async def search_documents(
    query: str,
    entity_id: Optional[UUID] = None,
    top_k: int = 5,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.search_documents(
        query=query,
        company_id=current_user.company_id,
        entity_id=entity_id,
        top_k=top_k
    )

# --- Templates ---

app_admin_only = RoleChecker(["app_admin"])

@router.get("/templates", response_model=List[HierarchicalEntityResponse])
async def list_templates(
    type: Optional[EntityType] = None,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    async with _template_library(db) as library:
        service = AIService(library)
        # Templates are public — no company_id scoping
        return await service.get_entities(None, type, is_template=True)

@router.get("/templates/{template_id}", response_model=HierarchicalEntityResponse)
async def get_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    async with _template_library(db) as library:
        service = AIService(library)
        return _shown(await service.get_entity(template_id, current_user.company_id, current_user.role))

@router.post("/templates", dependencies=[Depends(require_feature("feature.agents.templates"))], response_model=HierarchicalEntityResponse)
async def create_template(
    entity_in: HierarchicalEntityCreateRequest,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only)
):
    entity_in.is_template = True
    async with _template_library(db) as library:
        service = AIService(library)
        # A template belongs to the platform (APP) company; create_entity sets it (PO-23)
        return await service.create_entity(entity_in, current_user.company_id, current_user.id,
                                           user_role=current_user.role)

@router.put("/templates/{template_id}", response_model=HierarchicalEntityResponse)
async def update_template(
    template_id: UUID,
    entity_in: HierarchicalEntityUpdateRequest,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only)
):
    async with _template_library(db) as library:
        service = AIService(library)
        return _shown(await service.update_entity(template_id, entity_in, current_user.company_id, user_role=current_user.role, user_id=current_user.id))

@router.delete("/templates/{template_id}", response_model=EntityDeleted,
               summary="Soft-delete a template and its descendants", description=_SOFT_DELETE)
async def delete_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(app_admin_only)
):
    async with _template_library(db) as library:
        service = AIService(library)
        return await service.delete_entity(template_id, current_user.company_id, user_role=current_user.role)

@router.post("/templates/{template_id}/clone", dependencies=[Depends(require_feature("feature.agents.templates"))], response_model=HierarchicalEntityResponse)
async def clone_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    control_db: AsyncSession = Depends(get_control_db),
    current_user: User = Depends(get_current_user)
):
    async with _template_library(control_db) as library:
        service = AIService(db)
        return await service.clone_template(template_id, current_user.company_id, current_user.id,
                                            library_db=library)

