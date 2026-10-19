"""Code lanes end to end (Phase 14 WS6 6.3–6.5; tech spec §11.2; D35, D36).

A throwaway business database, the built-in Git as bare repositories in a
temporary folder (``LocalGitProvider``), storage in memory:

* an agent's code is kept as scratch (files in storage, a clean-up date in
  ``time_index``); promotion commits it with a test scaffold on a branch
  ``hb/<id>-<slug>`` and opens a pull request; the checks run on the head and
  are kept on the review; an owner's approval squash-merges it — the item is
  an asset at the merge commit, its scratch files and clean-up date gone;
* a pull request whose checks failed (a secret) cannot be approved; rejecting
  it closes it and the item stays scratch until its date, when it expires;
* only owners and admins approve;
* a synthesized tool's code is scratch from the moment it is drafted.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.needs_db


class StaticChecks:
    """The real static checks; no tests (they need the sandbox image)."""

    async def run(self, company_id, files, *, tests=True):
        from src.code_lanes.checks import LocalChecksRunner

        return await LocalChecksRunner().run(company_id, files, tests=False)


@pytest_asyncio.fixture
async def lane(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import src.common.orm_models  # noqa: F401
    from src.automation import store
    from src.code_lanes.git import LocalGitProvider, set_builtin_provider
    from src.common import database
    from src.common.config import settings
    from src.common.platform.storage import set_storage
    from tests.harness.storage import MemoryStorage
    from tests.harness.tenant_db import scratch_tenant

    control = create_async_engine(settings.CONTROL_DATABASE_URL, poolclass=NullPool,
                                  json_serializer=database.json_serializer)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(control, expire_on_commit=False))
    monkeypatch.setattr(database, "engine", control)

    async def _nudge(company_id, event_id, **kw):
        return None

    monkeypatch.setattr(store, "nudge", _nudge)
    queued = []

    async def _enqueue(function, *args, **kwargs):
        queued.append((function, args, kwargs))

    monkeypatch.setattr("src.common.job_queue.enqueue_job", _enqueue)
    storage = MemoryStorage()
    set_storage(storage)
    git = LocalGitProvider(tmp_path / "git")
    set_builtin_provider(git)
    try:
        async with scratch_tenant("lanes") as t:
            t.storage, t.git, t.queued = storage, git, queued
            t.owner = SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", email="owner@acme.test")
            t.staff = SimpleNamespace(id=uuid.uuid4(), role="tenant_user", email="staff@acme.test")
            yield t
    finally:
        set_storage(None)
        set_builtin_provider(None)
        await control.dispose()


async def _time_index(company_id, item_id):
    from src.automation.models import TimeIndexEntry
    from src.common.tenancy.session import control_session

    async with control_session() as cdb:
        return (await cdb.execute(select(TimeIndexEntry).where(
            TimeIndexEntry.company_id == company_id, TimeIndexEntry.ref_id == uuid.UUID(str(item_id))))).scalar()


async def test_scratch_code_is_promoted_through_a_reviewed_pull_request(lane):
    from src.code_lanes import service

    repo = await service.create_repo(lane.company_id, lane.owner.id, "tools")
    assert repo["provider"] == "builtin" and repo["full_name"] == f"t-{lane.key}/tools"
    run_id = uuid.uuid4()
    item = await service.register_scratch(lane.company_id, kind="script", name="Invoice parser",
                                          files={"parse.py": "def total(xs):\n    return sum(xs)\n"},
                                          description="adds up invoices", run_id=run_id)
    assert item["lane"] == "scratch" and item["files"] == ["parse.py"]
    assert await lane.storage.get(f"t-{lane.key}/scratch/code/{item['id']}/parse.py")
    due = await _time_index(lane.company_id, item["id"])
    assert due is not None and due.ref_kind == "scratch_cleanup"

    review = await service.promote(lane.company_id, item["id"], repo_id=repo["id"], user_id=lane.owner.id,
                                   run_id=run_id)
    assert review["status"] == "open" and review["number"] == 1
    assert review["branch"] == f"hb/{run_id.hex[:8]}-invoice-parser"
    assert lane.queued[-1][0] == "run_review_checks"
    tree = await lane.git.read_file(repo["full_name"], review["branch"], "scripts/invoice-parser/parse.py")
    assert b"sum(xs)" in tree
    assert await lane.git.read_file(repo["full_name"], review["branch"], "scripts/invoice-parser/test_smoke.py")

    with pytest.raises(service.CodeProblem, match="checks have not passed"):
        await service.approve(lane.company_id, review["id"], user=lane.owner)
    checked = await service.run_review_checks(lane.company_id, review["id"], runner=StaticChecks())
    assert checked["checks_status"] == "passed"
    assert {c["name"] for c in checked["checks"]} == {"secrets", "code", "dependencies"}
    with pytest.raises(service.CodeProblem) as refused:
        await service.approve(lane.company_id, review["id"], user=lane.staff)
    assert refused.value.status == 403

    merged = await service.approve(lane.company_id, review["id"], user=lane.owner)
    assert merged["status"] == "merged" and merged["merged_by_user_id"] == str(lane.owner.id)
    asset = await service.get_item(lane.company_id, item["id"])
    assert asset["lane"] == "asset" and asset["status"] == "promoted" and asset["commit_sha"] == merged["merge_sha"]
    assert asset["path"] == "scripts/invoice-parser" and asset["retention_until"] is None
    assert await lane.git.read_file(repo["full_name"], "main", "scripts/invoice-parser/parse.py")
    assert await _time_index(lane.company_id, item["id"]) is None
    assert not [k for k in lane.storage.objects if f"/scratch/code/{item['id']}/" in k]
    with pytest.raises(service.CodeProblem):
        await service.promote(lane.company_id, item["id"], repo_id=repo["id"])


async def test_failed_checks_block_approval_and_rejected_scratch_expires(lane):
    from src.code_lanes import service

    repo = await service.create_repo(lane.company_id, lane.owner.id, "leaky")
    item = await service.register_scratch(lane.company_id, kind="tool", name="uploader",
                                          files={"up.py": "KEY = 'AKIAABCDEFGHIJKLMNOP'\n"})
    review = await service.promote(lane.company_id, item["id"], repo_id=repo["id"], run_checks=False)
    checked = await service.run_review_checks(lane.company_id, review["id"], runner=StaticChecks())
    assert checked["checks_status"] == "failed"
    secrets = next(c for c in checked["checks"] if c["name"] == "secrets")
    assert secrets["conclusion"] == "failure" and "AWS access key" in secrets["summary"]
    stored = lane.git._load(repo["full_name"])  # noqa: SLF001 - the pull request's own record
    assert stored["reviews"]["1"]["checks"]["secrets"]["conclusion"] == "failure"   # posted to the pull request
    with pytest.raises(service.CodeProblem, match="failed"):
        await service.approve(lane.company_id, review["id"], user=lane.owner)

    closed = await service.reject(lane.company_id, review["id"], user=lane.owner)
    assert closed["status"] == "closed"
    rejected = await service.get_item(lane.company_id, item["id"])
    assert rejected["lane"] == "scratch" and rejected["status"] == "rejected"

    from src.automation.scheduler import Due, fire_scratch_cleanup

    due = await _time_index(lane.company_id, item["id"])
    result = await fire_scratch_cleanup(Due(company_id=due.company_id, ref_kind=due.ref_kind, ref_id=due.ref_id,
                                            due_at=due.due_at))
    assert result == {"item": item["id"], "expired": True}
    assert (await service.get_item(lane.company_id, item["id"]))["status"] == "expired"
    assert not [k for k in lane.storage.objects if f"/scratch/code/{item['id']}/" in k]
    assert await _time_index(lane.company_id, item["id"]) is None


async def test_an_app_change_is_a_pull_request_and_a_closed_one_outside_is_followed(lane):
    from src.code_lanes import service

    repo = await service.create_repo(lane.company_id, lane.owner.id, "site")
    await lane.git.commit_files(repo["full_name"], branch="main", base="main", files={"index.html": b"<h1>a</h1>"},
                                message="start")
    review = await service.open_change(lane.company_id, repo_id=repo["id"], branch="hb/abcd1234-new-title",
                                       files={"index.html": b"<h1>b</h1>"}, title="New title", run_checks=False)
    assert review["status"] == "open" and review["head_sha"]
    assert await lane.git.read_file(repo["full_name"], "hb/abcd1234-new-title", "index.html") == b"<h1>b</h1>"
    again = await service.open_change(lane.company_id, repo_id=repo["id"], branch="hb/abcd1234-new-title",
                                      files={"index.html": b"<h1>c</h1>"}, title="New title", run_checks=False)
    assert again["id"] == review["id"] and again["number"] == review["number"]   # the same pull request, updated

    await lane.git.close_review(repo["full_name"], review["number"])
    followed = await service.review_closed_outside(lane.company_id, "builtin", repo["full_name"], review["number"],
                                                   merged=False)
    assert followed["status"] == "closed"


async def test_a_synthesized_tool_is_scratch_code_linked_to_its_registry_row(lane, monkeypatch):
    from src.ai.meta.tool_synthesis_pipeline import register_draft_tool
    from src.ai.orm.tools import ToolRegistryEntry
    from src.ai.schemas.tools import ToolSpec
    from src.code_lanes import service
    from src.common.tenancy.session import control_session

    monkeypatch.setattr("src.ai.tools.ToolRegistry.register_tenant_tool", lambda *a, **k: None)
    spec = ToolSpec(name=f"word_count_{uuid.uuid4().hex[:6]}", description="counts words",
                    input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                    output_contract="an integer", examples=[], allowed_imports=[], est_cost_usd=0)
    async with control_session() as cdb:
        entry_id = await register_draft_tool(cdb, lane.company_id, spec, "def run(text):\n    return len(text.split())\n",
                                             audit={})
    try:
        items = await service.list_items(lane.company_id, kind="tool")
        mine = [i for i in items if i["name"] == spec.name]
        assert len(mine) == 1 and mine[0]["lane"] == "scratch"
        detail = await service.get_item(lane.company_id, mine[0]["id"], with_files=True)
        assert "len(text.split())" in detail["contents"][f"{spec.name}.py"]
    finally:
        async with control_session() as cdb:
            row = await cdb.get(ToolRegistryEntry, uuid.UUID(entry_id))
            if row is not None:
                await cdb.delete(row)
                await cdb.commit()
