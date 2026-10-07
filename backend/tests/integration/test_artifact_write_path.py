"""One artifact write path, found by run (P6.7 — TL-59, EP-21, EP-I5).

Six tools wrote a first copy under ``backend/src/artifact`` and registered a
second under ``backend/artifact``, mostly with no run, returning the path of
the unregistered copy; an edit overwrote that copy and was never registered.
The run page found files by matching regular expressions in step outputs.
Now a tool hands bytes to ``save_tool_output`` (the call's run, agent and
campaign come from its context) and returns the stored path, and the run page
asks the artifact table for the run's files. Real Postgres, rolled back.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from src.ai.artifact_models import Artifact
from src.ai.artifact_service import ARTIFACT_BASE_DIR, ORIGIN_SYSTEM, ArtifactService, save_tool_output
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.common.orm_models import import_all_models

import_all_models()  # the artifact row references campaigns

pytestmark = pytest.mark.needs_db

BACKEND = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
async def tree(db, monkeypatch):
    import src.common.database as database

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(database, "AsyncSessionLocal", _session)

    from src.auth.models import Company
    c = Company(name=f"p67-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    ent = HierarchicalEntity(company_id=c.id, type="AGENT", status="ACTIVE", name="maker")
    db.add(ent)
    await db.flush()
    parent = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={})
    other = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={})
    db.add_all([parent, other])
    await db.flush()
    child = ExecutionRun(entity_id=ent.id, company_id=c.id, status="RUNNING", input_data={},
                         parent_run_id=parent.id, depth=1)
    db.add(child)
    await db.flush()
    yield type("T", (), {"company": c.id, "entity": ent.id, "parent": parent.id, "child": child.id,
                         "other": other.id})
    shutil.rmtree(ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / str(c.id), ignore_errors=True)


def _ctx(t, run):
    return {"company_id": str(t.company), "run_id": str(run), "agent_id": str(t.entity)}


@pytest.mark.asyncio
async def test_a_tool_output_is_one_artifact_of_its_run(db, tree):
    artifact = await save_tool_output(_ctx(tree, tree.child), file_name="notes.md", file_bytes=b"# hi",
                                      mime_type="text/markdown", file_category="text", generated_by="t")
    assert (artifact.run_id, artifact.agent_id) == (tree.child, tree.entity)
    path = pathlib.Path(artifact.file_path)
    assert path.read_bytes() == b"# hi" and ARTIFACT_BASE_DIR in path.parents


@pytest.mark.asyncio
async def test_a_runs_files_include_its_child_runs_and_no_other(db, tree):
    for run, name in ((tree.parent, "p.md"), (tree.child, "c.md"), (tree.other, "o.md")):
        await save_tool_output(_ctx(tree, run), file_name=name, file_bytes=b"x", mime_type="text/plain",
                               file_category="text", generated_by="t")
    names = {a.file_name for a in await ArtifactService(db).list_artifacts(tree.company, run_id=tree.parent)}
    assert names == {"p.md", "c.md"}
    assert {a.file_name for a in await ArtifactService(db).list_artifacts(tree.company, run_id=tree.child)} == {"c.md"}


@pytest.mark.asyncio
async def test_docx_returns_the_registered_file_and_an_edit_is_a_new_one(db, tree):
    from src.ai.tools.documents.docx_tool import DocxTool
    ctx = _ctx(tree, tree.child)
    made = json.loads(await DocxTool().run_with_context(json.dumps(
        {"action": "create", "filename": "plan.docx", "title": "Plan", "sections": []}), ctx))
    rows = (await db.execute(select(Artifact).where(Artifact.run_id == tree.child))).scalars().all()
    assert [r.file_path for r in rows] == [made["file_path"]] and made["artifact_id"] == str(rows[0].id)

    edited = json.loads(await DocxTool().run_with_context(json.dumps(
        {"action": "update", "file_path": made["file_path"], "append_paragraphs": ["more"]}), ctx))
    assert edited["updated_from"] == made["file_path"] and edited["file_path"] != made["file_path"]
    assert pathlib.Path(made["file_path"]).exists()                 # the original is unchanged
    assert len((await db.execute(select(Artifact).where(Artifact.run_id == tree.child))).scalars().all()) == 2


def test_no_tool_writes_the_old_tree():
    offenders = [p.relative_to(BACKEND).as_posix() for p in (BACKEND / "src").rglob("*.py")
                 if 'parents[3] / "artifact"' in p.read_text(encoding="utf-8")
                 or 'parents[4] / "artifact"' in p.read_text(encoding="utf-8")]
    assert offenders == []
