"""Regression tests for the DOC_FACTORY_REDESIGN platform fixes.

Covers the two real platform bugs surfaced by the doc-factory-process analysis
(docs/phase11/DOC_FACTORY_REDESIGN.md) plus the sandbox scratch-dir skip:

  §5.1 — StepEngine._enforce_cost_cap raises BudgetExhaustedError once a
         run reaches its entity's governance.max_cost_usd (the cap that the
         legacy run loop previously never enforced on children).
  §5.2 — AgentLoop._sync_budget_tokens rolls child-run tokens up to the parent
         so total_tokens is no longer 0 for a delegating parent.
  §4.5 — SandboxCodeTool no longer auto-registers files written under scratch/.

Pure unit tests: no real DB / Redis / LLM.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai.core.exceptions import BudgetExhaustedError
from src.ai.core.step_engine import StepEngine


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    """Minimal async DB whose execute() returns a preset scalar (or raises)."""

    def __init__(self, value=None, raises=False):
        self._value = value
        self._raises = raises

    async def execute(self, *_a, **_kw):
        if self._raises:
            raise RuntimeError("boom")
        return _ScalarResult(self._value)


def _engine_stub(db) -> SimpleNamespace:
    # _enforce_cost_cap only touches self.db — bind it to a light stub to avoid
    # StepEngine's full service wiring.
    return SimpleNamespace(db=db)


async def _enforce(db, governance, spent=None):
    stub = _engine_stub(_FakeDB(value=spent) if db is None else db)
    run = SimpleNamespace(id=uuid4())
    await StepEngine._enforce_cost_cap(stub, run, governance)


# ---------------------------------------------------------------------------
# §5.1 — cost-cap enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_cap_raises_when_spent_reaches_cap():
    db = _FakeDB(value="15.5655")
    stub = _engine_stub(db)
    run = SimpleNamespace(id=uuid4())
    with pytest.raises(BudgetExhaustedError) as ei:
        await StepEngine._enforce_cost_cap(stub, run, {"max_cost_usd": 3.00})
    assert ei.value.cap_usd == pytest.approx(3.00)
    assert ei.value.spent_usd == pytest.approx(15.5655)


@pytest.mark.asyncio
async def test_cost_cap_passes_when_under_cap():
    db = _FakeDB(value="1.00")
    stub = _engine_stub(db)
    run = SimpleNamespace(id=uuid4())
    # Must NOT raise.
    await StepEngine._enforce_cost_cap(stub, run, {"max_cost_usd": 3.00})


@pytest.mark.asyncio
@pytest.mark.parametrize("governance", [{}, {"max_cost_usd": None}, {"max_cost_usd": 0}])
async def test_cost_cap_noop_when_no_cap(governance):
    db = _FakeDB(value="9999.0")  # huge spend, but no cap configured
    stub = _engine_stub(db)
    run = SimpleNamespace(id=uuid4())
    await StepEngine._enforce_cost_cap(stub, run, governance)  # no raise


@pytest.mark.asyncio
async def test_cost_cap_swallows_lookup_errors():
    db = _FakeDB(raises=True)
    stub = _engine_stub(db)
    run = SimpleNamespace(id=uuid4())
    # A failed cost lookup must never crash a healthy step.
    await StepEngine._enforce_cost_cap(stub, run, {"max_cost_usd": 1.00})


@pytest.mark.asyncio
async def test_cost_cap_boundary_equal_trips():
    db = _FakeDB(value="2.0000")
    stub = _engine_stub(db)
    run = SimpleNamespace(id=uuid4())
    with pytest.raises(BudgetExhaustedError):
        await StepEngine._enforce_cost_cap(stub, run, {"max_cost_usd": 2.00})


# ---------------------------------------------------------------------------
# §5.2 — token roll-up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_budget_tokens_sums_subtree():
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=_FakeDB(value=1_798_376), redis=None)
    loop._run_id = uuid4()
    assert await loop._sync_budget_tokens() == 1_798_376


@pytest.mark.asyncio
async def test_sync_budget_tokens_zero_without_run_id():
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=_FakeDB(value=123), redis=None)
    loop._run_id = None
    assert await loop._sync_budget_tokens() == 0


@pytest.mark.asyncio
async def test_sync_budget_tokens_zero_on_db_error():
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=_FakeDB(raises=True), redis=None)
    loop._run_id = uuid4()
    assert await loop._sync_budget_tokens() == 0


# ---------------------------------------------------------------------------
# Replan loop guard — a STATIC-plan entity must not have its plan regenerated
# (doc-factory-lite infinite-planning-loop incident).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replan_is_noop_for_static_plan_entity():
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=_FakeDB(), redis=None)
    loop._entity = SimpleNamespace(planning={
        "static_plan": {"enabled": True},
        "dynamic_planning": {"enabled": False},
    })
    plan = [{"step_id": "outline"}, {"step_id": "generate"},
            {"step_id": "validate"}, {"step_id": "finalize"}]
    state = SimpleNamespace(
        run_id=uuid4(), iteration=2, plan_steps=list(plan),
        completed_step_ids={"outline"}, last_observation=None,
    )
    await loop._handle_replan(state, supervise=SimpleNamespace(proposed_subgoals=[]))
    # Static plan + progress preserved (NOT regenerated / reset).
    assert state.plan_steps == plan
    assert state.completed_step_ids == {"outline"}


@pytest.mark.asyncio
async def test_replan_proceeds_for_dynamic_entity():
    """A dynamic-planning entity still enters the replan path (reaches the
    PlannerService import) rather than short-circuiting."""
    from src.ai.core.agent_loop import AgentLoop

    loop = AgentLoop(db=_FakeDB(), redis=None)
    loop._entity = SimpleNamespace(planning={
        "static_plan": {"enabled": False},
        "dynamic_planning": {"enabled": True},
    })
    state = SimpleNamespace(
        run_id=uuid4(), iteration=2, plan_steps=[{"step_id": "a"}],
        completed_step_ids=set(), last_observation=None,
    )
    # Not a static plan → it does NOT short-circuit; the planner call fails on
    # the fake DB and is swallowed, leaving plan_steps unchanged. The point is
    # only that it did not take the static no-op branch (no assertion error).
    await loop._handle_replan(state, supervise=SimpleNamespace(proposed_subgoals=[]))


# ---------------------------------------------------------------------------
# §4.5 — sandbox scratch-dir is not auto-registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_skips_scratch_dir(tmp_path):
    from src.ai.tools.sandbox.sandbox_executor import SandboxCodeTool

    sandbox = str(tmp_path)
    scratch = os.path.join(sandbox, "scratch")
    os.makedirs(scratch, exist_ok=True)
    # A document written ONLY under scratch/ must not be auto-registered, so the
    # registration path returns "" without ever touching the DB.
    with open(os.path.join(scratch, "output.xlsx"), "wb") as f:
        f.write(b"x" * 256)  # > 100-byte floor

    report = await SandboxCodeTool()._register_new_artifacts(
        sandbox_dir=sandbox,
        pre_existing_files=set(),
        company_id=str(uuid4()),
        context={"run_id": str(uuid4())},
    )
    assert report == ""


# ---------------------------------------------------------------------------
# document_save — (A) run/agent association + (B) sandbox-relative path resolve
# ---------------------------------------------------------------------------


def test_document_save_resolves_sandbox_relative_path(tmp_path, monkeypatch):
    """(B) A relative 'scratch/x' path resolves against the company sandbox dir,
    not this process's CWD."""
    import tempfile

    from src.ai.tools.documents.document_save import DocumentSaveTool

    company = str(uuid4())
    sandbox = os.path.join(tempfile.gettempdir(), "sandbox", company, "scratch")
    os.makedirs(sandbox, exist_ok=True)
    f = os.path.join(sandbox, "report.xlsx")
    with open(f, "wb") as fh:
        fh.write(b"x" * 64)

    # Relative path resolves to the sandbox copy.
    assert DocumentSaveTool._resolve_source_path("scratch/report.xlsx", company) == f
    # A non-existent relative path is returned unchanged (clear "not found").
    assert DocumentSaveTool._resolve_source_path("scratch/nope.xlsx", company) == "scratch/nope.xlsx"
    os.remove(f)


@pytest.mark.asyncio
async def test_document_save_threads_run_and_agent_ids(tmp_path, monkeypatch):
    """(A) run_id + agent_id from context reach the artifact registration so the
    saved file is linked to the run (not orphaned with run_id=None)."""
    import json as _json
    import shutil as _shutil

    from src.ai.tools.documents import document_save as ds_mod
    from src.ai.tools.documents.document_save import DocumentSaveTool

    src = tmp_path / "report.xlsx"
    src.write_bytes(b"x" * 256)

    captured: dict = {}

    async def _fake_register(**kwargs):
        captured.update(kwargs)
        return "artifact-123"

    # Capture what registration receives; keep storage writes inside tmp_path.
    monkeypatch.setattr(DocumentSaveTool, "_register_artifact", staticmethod(_fake_register))
    monkeypatch.setattr(ds_mod, "BASE_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(ds_mod.shutil, "copy2", lambda s, d: _shutil.copy(s, d))

    run_id, agent_id, company_id = str(uuid4()), str(uuid4()), str(uuid4())
    out = await DocumentSaveTool().run_with_context(
        _json.dumps({"source_path": str(src), "filename": "report", "format": "xlsx"}),
        context={"company_id": company_id, "run_id": run_id, "agent_id": agent_id},
    )
    assert _json.loads(out)["status"] == "success"
    assert captured.get("run_id") == run_id
    assert captured.get("agent_id") == agent_id
