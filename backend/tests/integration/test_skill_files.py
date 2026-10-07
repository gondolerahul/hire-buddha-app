"""A run's skill files are written into its workspace and named in the prompt (P5.4, R2 §7).

Before, the only way a script reached the sandbox was a symlink from every
tenant's workspace to one repo directory. Now a version's assets are written,
per tenant, into ``.skills/<slug>/<version>/`` — once, by content hash — and
the step prompt lists them. A run sees its own version's files and its
ancestor runs' (D14). Real Postgres, rolled back; workspace in a temp dir.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

from src.ai.core.prompt_utils import build_sandwich_prompt
from src.ai.governance.entity_assets import AssetRejected
from src.ai.governance.entity_versions import capture_head
from src.ai.orm import ExecutionRun, HierarchicalEntity
from src.ai.orm.versions import EntityAsset, EntityVersion
from src.ai.tools.sandbox import skill_files as sf
from src.ai.tools.sandbox.skill_files import SkillFiles, render_skill_files, run_skill_files

pytestmark = pytest.mark.needs_db


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    from src.common.config import settings
    monkeypatch.setattr(settings, "SANDBOX_WORKSPACE_ROOT", str(tmp_path), raising=False)
    return tmp_path


async def _entity_with_files(db, company_id, name, files):
    ent = HierarchicalEntity(company_id=company_id, type="SKILL", status="ACTIVE", name=name, goal="g")
    db.add(ent)
    await db.flush()
    vid = await capture_head(db, ent.id)
    for path, body in files.items():
        db.add(EntityAsset(entity_version_id=vid, path=path, content_hash=f"h-{path}", language=None,
                           body=body, size_bytes=len(body)))
    await db.flush()
    return ent, vid


async def _company(db):
    from src.auth.models import Company
    c = Company(name=f"p54-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()
    return c.id


async def _run(db, ent, vid, parent=None):
    run = ExecutionRun(entity_id=ent.id, company_id=ent.company_id, status="RUNNING", input_data={},
                       entity_version_id=vid, parent_run_id=parent)
    db.add(run)
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_files_land_in_the_tenant_workspace_with_a_marker(db, workspace):
    company = await _company(db)
    ent, vid = await _entity_with_files(db, company, "Docx Skill", {"office/validate.py": "print('ok')\n"})
    run = await _run(db, ent, vid)

    [skill] = await run_skill_files(db, run)

    assert (skill.root, skill.paths) == (".skills/docx-skill/1", ["office/validate.py"])
    root = workspace / str(company) / ".skills" / "docx-skill" / "1"
    assert (root / "office" / "validate.py").read_text() == "print('ok')\n"
    digest = (await db.execute(select(EntityVersion.content_hash).where(EntityVersion.id == vid))).scalar()
    assert (root / ".content-hash").read_text() == digest


@pytest.mark.asyncio
async def test_a_warm_workspace_is_not_rewritten(db, monkeypatch):
    company = await _company(db)
    ent, vid = await _entity_with_files(db, company, "warm", {"a.py": "1"})
    run = await _run(db, ent, vid)
    await run_skill_files(db, run)

    def _boom(*_a, **_k):
        raise AssertionError("rewritten")
    monkeypatch.setattr(sf, "materialise", _boom)
    assert [s.paths for s in await run_skill_files(db, run)] == [["a.py"]]


@pytest.mark.asyncio
async def test_a_stale_tree_is_replaced(db, workspace):
    company = await _company(db)
    ent, vid = await _entity_with_files(db, company, "stale", {"a.py": "new", "b.py": "b"})
    root = workspace / str(company) / ".skills" / "stale" / "1"
    os.makedirs(root)
    (root / "a.py").write_text("old")
    (root / "left-over.py").write_text("x")
    (root / ".content-hash").write_text("something else")

    await run_skill_files(db, await _run(db, ent, vid))

    assert sorted(os.listdir(root)) == [".content-hash", "a.py", "b.py"]
    assert (root / "a.py").read_text() == "new"


@pytest.mark.asyncio
async def test_a_child_run_sees_its_ancestors_files(db):
    company = await _company(db)
    skill, skill_v = await _entity_with_files(db, company, "family-skill", {"tool.py": "t"})
    action, action_v = await _entity_with_files(db, company, "family-action", {})
    parent = await _run(db, skill, skill_v)
    child = await _run(db, action, action_v, parent=parent.id)

    assert [(s.entity_name, s.root) for s in await run_skill_files(db, child)] == [
        ("family-skill", ".skills/family-skill/1")]


@pytest.mark.asyncio
async def test_a_bad_path_written_around_put_asset_is_not_materialised(db, workspace):
    company = await _company(db)
    ent, vid = await _entity_with_files(db, company, "evil", {"../escape.py": "x"})
    assert await run_skill_files(db, await _run(db, ent, vid)) == []      # logged and left out
    assert not (workspace / str(company) / ".skills" / "escape.py").exists()
    with pytest.raises(AssetRejected):
        sf.materialise(company, ".skills/evil/1", "d", {"../escape.py": "x"})


def test_the_prompt_lists_scripts_first_and_caps_the_list():
    many = [f"schemas/s{i:03}.xsd" for i in range(50)] + ["run.py"]
    text = render_skill_files([SkillFiles("Docx", 3, ".skills/docx/3", many)])
    lines = text.splitlines()
    assert lines[1] == "- Docx v3: `.skills/docx/3/`"
    assert lines[2] == "  - `.skills/docx/3/run.py`"
    assert lines[-1] == "  - … and 11 more (`ls -R .skills/docx/3`)"
    prompt = build_sandwich_prompt(identity="I", skill_files=text)
    assert "## Skill Files\nThese files are already in your workspace" in prompt
    assert render_skill_files([]) is None


@pytest.mark.asyncio
async def test_a_tool_step_gets_its_files_before_the_tool_runs_once_per_run(monkeypatch):
    from types import SimpleNamespace

    from src.ai.schemas.planning import PlanStep, StepType
    from src.ai.step_executor import StepExecutorService
    order: list[str] = []

    async def _files(_db, run):
        order.append("files")
        return []

    async def _tool(self, run, entity, step, context):
        order.append("tool")
        return {"output": "ok"}

    monkeypatch.setattr(sf, "run_skill_files", _files)
    monkeypatch.setattr(StepExecutorService, "_execute_tool_call", _tool)
    svc = StepExecutorService.__new__(StepExecutorService)
    svc.db = None
    run = SimpleNamespace(id=uuid.uuid4())
    step = PlanStep(step_id="s", name="s", type=StepType.TOOL_CALL, tool_id="terminal")
    await svc._execute_step(run, None, step, {})
    await svc._execute_step(run, None, step, {})
    assert order == ["files", "tool", "tool"]
