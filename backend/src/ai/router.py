from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List, Optional
from src.common.database import get_db
from src.auth.dependencies import get_current_user, get_current_user_from_query, RoleChecker
from src.auth.models import User
from src.ai.schemas import (
    HierarchicalEntityCreate, HierarchicalEntityUpdate, HierarchicalEntityResponse, 
    ExecutionRunCreate, ExecutionRunResponse, ExecutionRunSummary, EntityType,
    DocumentResponse, DocumentSearchResult, ExecutionRefineRequest, CSATRequest
)
from src.ai.service import AIService

router = APIRouter(prefix="/ai", tags=["AI Hierarchical Agent Platform"])

# --- Entities ---
@router.post("/entities", response_model=HierarchicalEntityResponse)
async def create_entity(
    entity_in: HierarchicalEntityCreate,
    target_company_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Determine the effective company for this entity
    effective_company_id = current_user.company_id
    if target_company_id:
        if current_user.role == "app_admin":
            effective_company_id = target_company_id
        elif current_user.role in ("partner_admin", "partner_user"):
            # Partners can create entities for their managed tenants
            from src.auth.models import Company
            result = await db.execute(
                select(Company).where(
                    Company.id == target_company_id,
                    Company.parent_id == current_user.company_id,
                )
            )
            if result.scalar_one_or_none():
                effective_company_id = target_company_id
            else:
                raise HTTPException(status_code=403, detail="Not authorized to create entities for this company")
        else:
            raise HTTPException(status_code=403, detail="Cannot create entities for another company")

    service = AIService(db)
    return await service.create_entity(entity_in, effective_company_id, current_user.id)

@router.get("/entities", response_model=List[HierarchicalEntityResponse])
async def list_entities(
    type: Optional[EntityType] = None,
    company_id: Optional[UUID] = None,
    voice_enabled: Optional[bool] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Allow app_admin to filter by specific company
    effective_company_id = current_user.company_id
    if company_id and current_user.role == "app_admin":
        effective_company_id = company_id

    service = AIService(db)
    entities = list(await service.get_entities(
        effective_company_id, type, current_user.role,
        is_template=False, status_filter=status,
    ))

    # For partner_admin/partner_user, also include entities from child tenants
    if current_user.role in ("partner_admin", "partner_user"):
        from src.auth.models import Company
        child_result = await db.execute(
            select(Company.id).where(Company.parent_id == current_user.company_id)
        )
        seen_ids = {e.id for e in entities}
        for (child_id,) in child_result.fetchall():
            child_entities = await service.get_entities(
                child_id, type, "app_admin",
                is_template=False, status_filter=status,
            )
            for ce in child_entities:
                if ce.id not in seen_ids:
                    entities.append(ce)
                    seen_ids.add(ce.id)

    # Client-requested voice filter: only return agents with voice config
    if voice_enabled:
        entities = [
            e for e in entities
            if (getattr(e.type, 'value', e.type) == "AGENT")
            and _has_voice_config(e.identity)
        ]

    return entities


def _has_voice_config(identity) -> bool:
    """Check if an entity's identity JSON contains voice configuration.
    Handles both direct format {"voice": {...}} and
    wrapped format {"persona": {"voice": {...}}}."""
    if not identity or not isinstance(identity, dict):
        return False
    if identity.get("voice"):
        return True
    persona = identity.get("persona")
    if isinstance(persona, dict) and persona.get("voice"):
        return True
    return False

@router.get("/entities/{entity_id}", response_model=HierarchicalEntityResponse)
async def get_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_entity(entity_id, current_user.company_id, current_user.role)

@router.put("/entities/{entity_id}", response_model=HierarchicalEntityResponse)
async def update_entity(
    entity_id: UUID,
    entity_in: HierarchicalEntityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.update_entity(entity_id, entity_in, current_user.company_id, user_role=current_user.role)

@router.delete("/entities/{entity_id}")
async def delete_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    await service.delete_entity(entity_id, current_user.company_id)
    return {"status": "success"}

@router.post("/entities/{entity_id}/convert-to-template", response_model=HierarchicalEntityResponse)
async def convert_entity_to_template(
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["app_admin"]))
):
    """
    Deep-clone an existing entity (and all its children) into a parallel
    template hierarchy.  The original entities are left untouched.
    Requires app_admin role.
    """
    service = AIService(db)
    return await service.convert_to_template(entity_id, current_user.company_id, current_user.id)

# --- Dashboard ---
@router.get("/stats", response_model=dict)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_dashboard_stats(current_user.company_id, current_user.role)

# --- Executions ---
@router.post("/execute", response_model=ExecutionRunResponse)
async def trigger_execution(
    execution_in: ExecutionRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.trigger_execution(execution_in, current_user.company_id, current_user.id, user_role=current_user.role)

@router.get("/executions", response_model=List[ExecutionRunSummary])
async def list_executions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_executions(current_user.company_id, current_user.role)

@router.get("/executions/{execution_id}", response_model=ExecutionRunResponse)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    execution = await service.get_execution(execution_id, current_user.company_id, current_user.role)
    return execution

@router.post("/executions/{execution_id}/csat", response_model=ExecutionRunResponse)
async def record_execution_csat(
    execution_id: UUID,
    payload: CSATRequest,
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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


@router.get("/executions/{execution_id}/stream")
async def stream_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_query)
):
    # Verify access
    service = AIService(db)
    await service.get_execution(execution_id, current_user.company_id, current_user.role)
    
    from fastapi.responses import StreamingResponse
    import redis.asyncio as redis
    from src.common.config import settings
    import asyncio

    async def event_generator():
        r = redis.from_url(settings.REDIS_URL or "redis://localhost:6379")
        pubsub = r.pubsub()
        channel = f"execution:{execution_id}"
        await pubsub.subscribe(channel)
        
        try:
            # Send initial connection message
            yield "data: {\"status\": \"connected\"}\n\n"
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"].decode("utf-8")
                    yield f"data: {data}\n\n"
                    if any(
                        f"\"status\": \"{terminal}\"" in data
                        for terminal in ("COMPLETED", "FAILED", "CANCELLED")
                    ):
                        break
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await r.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Cancel ---
@router.post("/executions/{execution_id}/cancel", response_model=ExecutionRunResponse)
async def cancel_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel an in-flight execution run.

    Sets the run to the terminal ``CANCELLED`` state and publishes on the
    ``execution:{id}`` Redis channel. A running AgentLoop re-reads the run
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
            "requested_at": a.requested_at
        }
        for a in approvals
    ]

@router.post("/approvals/{approval_id}/respond")
async def respond_to_approval(
    approval_id: UUID,
    status: str, # APPROVED | REJECTED
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    await service.respond_to_approval(approval_id, status, current_user.id, notes)

    # Publish approval response to Redis so the worker's HITL checkpoint loop unblocks
    try:
        import redis.asyncio as redis_lib
        import json
        from src.common.config import settings
        r = redis_lib.from_url(settings.REDIS_URL or "redis://localhost:6379")
        await r.publish(f"hitl:{approval_id}", json.dumps({
            "status": status,
            "responded_by": str(current_user.id),
            "notes": notes,
        }))
        await r.close()
    except Exception:
        pass  # Non-fatal: worker will timeout if pub/sub fails

    return {"status": "success"}

# --- Tools ---
@router.get("/tools", response_model=list[dict])
async def list_tools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all available tools with enriched metadata."""
    try:
        from src.ai.tool_management_service import ToolManagementService
        service = ToolManagementService(db)
        return await service.list_all_tools()
    except Exception:
        # Fallback to simple ToolRegistry list if DB is unavailable
        from src.ai.tools import ToolRegistry
        return ToolRegistry.list_tools()

# --- Context Source Upload ---
@router.post("/context-sources/upload", response_model=dict)
async def upload_context_source(
    file: UploadFile = File(...),
    entity_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
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
            from src.ai.models import HierarchicalEntity
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

# --- Documents ---
@router.post("/documents/upload", response_model=dict)
async def upload_document(
    file: UploadFile = File(...),
    entity_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Read file content
    file_content = await file.read()
    
    # Get file extension
    file_type = file.filename.split('.')[-1].lower() if '.' in file.filename else 'txt'
    
    service = AIService(db)
    document = await service.upload_document(
        file_content=file_content,
        filename=file.filename,
        file_type=file_type,
        company_id=current_user.company_id,
        entity_id=entity_id
    )
    return {"id": str(document.id), "status": document.upload_status}

@router.post("/avatar/upload", response_model=dict)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Upload an avatar image for an entity. Returns the public URL."""
    import uuid as _uuid
    from pathlib import Path

    allowed = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        raise HTTPException(400, f"File type '.{ext}' not allowed. Use: {', '.join(allowed)}")

    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(400, "Avatar must be under 5 MB")

    avatar_dir = Path(__file__).resolve().parents[2] / "artifact" / "user-uploads" / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{_uuid.uuid4().hex[:12]}.{ext}"
    filepath = avatar_dir / filename

    content = await file.read()
    filepath.write_bytes(content)

    url = f"/artifact/user-uploads/avatars/{filename}"
    return {"url": url, "filename": filename}

@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    entity_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_documents(current_user.company_id, entity_id)

@router.post("/documents/search", response_model=List[dict])
async def search_documents(
    query: str,
    entity_id: Optional[UUID] = None,
    top_k: int = 5,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    results = await service.search_documents(
        query=query,
        company_id=current_user.company_id,
        entity_id=entity_id,
        top_k=top_k
    )
    return [
        {
            "chunk_id": str(r.chunk_id),
            "document_id": str(r.document_id),
            "filename": r.filename,
            "content": r.content,
            "similarity": float(r.similarity)
        }
        for r in results
    ]

# --- Templates ---

app_admin_only = RoleChecker(["app_admin"])

@router.get("/templates", response_model=List[HierarchicalEntityResponse])
async def list_templates(
    type: Optional[EntityType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    # Templates are public — no company_id scoping
    return await service.get_entities(current_user.company_id, type, current_user.role, is_template=True)

@router.get("/templates/{template_id}", response_model=HierarchicalEntityResponse)
async def get_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.get_entity(template_id, current_user.company_id, current_user.role)

@router.post("/templates", response_model=HierarchicalEntityResponse)
async def create_template(
    entity_in: HierarchicalEntityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only)
):
    entity_in.is_template = True
    service = AIService(db)
    # Templates are public: company_id is set to None by create_entity when is_template=True
    return await service.create_entity(entity_in, current_user.company_id, current_user.id)

@router.put("/templates/{template_id}", response_model=HierarchicalEntityResponse)
async def update_template(
    template_id: UUID,
    entity_in: HierarchicalEntityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only)
):
    service = AIService(db)
    return await service.update_entity(template_id, entity_in, current_user.company_id, user_role=current_user.role)

@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(app_admin_only)
):
    service = AIService(db)
    await service.delete_entity(template_id, current_user.company_id)
    return {"status": "success"}

@router.post("/templates/{template_id}/clone", response_model=HierarchicalEntityResponse)
async def clone_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AIService(db)
    return await service.clone_template(template_id, current_user.company_id, current_user.id)

