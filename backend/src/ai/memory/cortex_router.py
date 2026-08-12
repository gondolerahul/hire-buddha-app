"""
cortex_router.py — FastAPI REST Endpoints for CORTEX Memory System

Provides endpoints under /api/v1/cortex/ to manage cognitive trees,
navigate/read/write nodes, checkpoint, ingest documents, and assemble outputs.
"""
from uuid import UUID
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.database import get_db
from src.auth.dependencies import get_current_user
from src.ai.memory.cortex_service import CortexService
from src.ai.memory.cortex_ingestion import CortexIngestionPipeline
from src.ai.schemas import (
    CortexTreeCreate, CortexTreeResponse, CortexTreeListResponse,
    CortexNodeCreate, CortexNodeSummary, CortexViewportResponse,
    CortexNodeContentResponse, CortexCheckpointCreate,
    CortexRecurseRequest, CortexNodeDetailResponse,
)

router = APIRouter(prefix="/api/v1/cortex", tags=["CORTEX Memory"])


def _cortex_service(db: AsyncSession, company_id: UUID) -> CortexService:
    return CortexService(db=db, company_id=company_id)


# ===================================================================
# Tree Management
# ===================================================================

@router.post("/trees", response_model=CortexTreeResponse, status_code=201)
async def create_tree(
    body: CortexTreeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Create a new CORTEX cognitive tree for an entity."""
    svc = _cortex_service(db, current_user.company_id)
    tree = await svc.create_tree(
        entity_id=body.entity_id,
        user_id=current_user.id,
        task_description=body.task_description,
        max_children=body.max_children,
        page_size_tokens=body.page_size_tokens,
        context_budget_pct=body.context_budget_pct,
    )
    await db.commit()
    status = await svc.get_tree_status(tree.id)
    return status


@router.get("/trees", response_model=list)
async def list_trees(
    entity_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """List CORTEX trees for the current company."""
    svc = _cortex_service(db, current_user.company_id)
    return await svc.list_trees(entity_id=entity_id, status=status)


@router.get("/trees/{tree_id}")
async def get_tree(
    tree_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Get tree status and metadata."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        return await svc.get_tree_status(tree_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/trees/{tree_id}/resume")
async def resume_tree(
    tree_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Resume a suspended CORTEX tree."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        tree, viewport, checkpoint = await svc.resume_tree(tree_id)
        await db.commit()
        return {
            "tree": await svc.get_tree_status(tree_id),
            "viewport": viewport.to_dict(),
            "last_checkpoint": checkpoint,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/trees/{tree_id}/suspend")
async def suspend_tree(
    tree_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Suspend a CORTEX tree with automatic checkpoint."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        checkpoint_id = await svc.suspend_tree(tree_id)
        await db.commit()
        return {"status": "suspended", "checkpoint_id": str(checkpoint_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===================================================================
# Navigation
# ===================================================================

@router.post("/trees/{tree_id}/navigate/{node_id}", response_model=CortexViewportResponse)
async def navigate_node(
    tree_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Navigate to a node and return the viewport."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        viewport = await svc.navigate(node_id)
        await db.commit()
        return viewport.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===================================================================
# Content Access (Read / Write)
# ===================================================================

@router.get("/trees/{tree_id}/nodes/{node_id}", response_model=CortexNodeContentResponse)
async def read_node(
    tree_id: UUID,
    node_id: UUID,
    page: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Read paged content from a node."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        content = await svc.read(node_id, page=page)
        await db.commit()
        return content.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trees/{tree_id}/nodes/{node_id}/detail", response_model=CortexNodeDetailResponse)
async def get_node_detail(
    tree_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Get full node metadata."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        return await svc.get_node_details(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/trees/{tree_id}/nodes", status_code=201)
async def write_node(
    tree_id: UUID,
    body: CortexNodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Write a new child node."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        node_id = await svc.write(
            parent_id=body.parent_id,
            node_type=body.node_type.value,
            title=body.title,
            content=body.content,
            summary=body.summary,
            status=body.status,
            source_ref=body.source_ref,
            metadata_extra=body.metadata_extra,
        )
        await db.commit()
        return {"id": str(node_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===================================================================
# Checkpointing & Assembly
# ===================================================================

@router.post("/trees/{tree_id}/checkpoint", status_code=201)
async def create_checkpoint(
    tree_id: UUID,
    body: CortexCheckpointCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Create a checkpoint at the current cursor."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        checkpoint_id = await svc.checkpoint(
            tree_id=tree_id,
            progress_summary=body.progress_summary,
            key_facts=body.key_facts,
            next_steps=body.next_steps,
        )
        await db.commit()
        return {"id": str(checkpoint_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trees/{tree_id}/output")
async def assemble_output(
    tree_id: UUID,
    coherence_pass: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Assemble complete output from the output subtree."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        output = await svc.assemble_output(tree_id, coherence_pass=coherence_pass)
        return {"output": output}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===================================================================
# Recursive Execution
# ===================================================================

@router.post("/trees/{tree_id}/recurse", status_code=201)
async def recurse_node(
    tree_id: UUID,
    body: CortexRecurseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Spawn a recursive child execution scoped to a subtree."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        task_node_id, child_run_id = await svc.recurse(
            node_id=body.node_id,
            task=body.task,
            result_slot=body.result_slot,
            model_override=getattr(body, 'model_override', None),
            priority=getattr(body, 'priority', 0),
        )
        await db.commit()
        return {"task_node_id": str(task_node_id), "child_run_id": str(child_run_id) if child_run_id else None}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===================================================================
# Document Ingestion (Gap #6)
# ===================================================================

class IngestDocumentRequest(BaseModel):
    document_id: UUID
    content: str
    filename: str
    knowledge_root_id: Optional[UUID] = None


@router.post("/trees/{tree_id}/ingest", status_code=201)
async def ingest_document(
    tree_id: UUID,
    body: IngestDocumentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> Any:
    """Ingest a document into the CORTEX tree as hierarchical knowledge nodes."""
    svc = _cortex_service(db, current_user.company_id)
    try:
        # Get knowledge root if not provided
        if body.knowledge_root_id:
            parent_id = body.knowledge_root_id
        else:
            kr = await svc.get_knowledge_root(tree_id)
            if not kr:
                raise ValueError(f"No knowledge root found for tree {tree_id}")
            parent_id = kr.id

        pipeline = CortexIngestionPipeline(db, current_user.company_id)
        count = await pipeline.ingest_document(
            tree_id=tree_id,
            parent_node_id=parent_id,
            document_id=body.document_id,
            content=body.content,
            filename=body.filename,
        )
        await db.commit()
        return {"nodes_created": count}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
