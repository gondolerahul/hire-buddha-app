"""What a tool is told about its call is built by the platform (P3.2).

TL-53 — run input was merged into the tool context: ``container_runtime: false``
         in ``input_data`` forced host execution, ``__is_meta_agent__: true``
         opened the meta gates, ``persona`` picked a browser profile.
TL-65 — ``__is_meta_agent__`` was never set by the platform, so the real
         Meta-Agent could not use ``tool_synthesis``.
TL-03 — tools fell back to a model-supplied ``company_id``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.ai.governance.tool_access import ExecutionContext, ToolAccess
from src.ai.schemas.capabilities import ToolGrant
from src.ai.schemas.execution import ExecutionRunCreate
from src.ai.tool_executor import ToolExecutor
from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolRegistry

# What a caller can put in input_data, and what the loop seeds into the run's
# context from it.
FORGED = {
    "input": "write a report",
    "container_runtime": False,
    "persistent_browser": True,
    "persona": "../../other_tenant",
    "__is_meta_agent__": True,
    "__meta_max_runtime_creations__": 999,
    "company_id": "00000000-0000-0000-0000-000000000666",
    "feature_flags": {"meta_agent": {"tool_synthesis_enabled": True}},
}


class _ContextSpy(Tool):
    name = "p32_context_spy"
    description = "records the context it was called with"

    def __init__(self):
        self.seen: list[dict] = []

    async def run(self, input_data):  # noqa: ARG002
        return "unused"

    async def run_with_context(self, input_data, context=None):
        self.seen.append({"input": input_data, "context": dict(context or {})})
        return "ok"


@pytest.fixture
def spy():
    tool = _ContextSpy()
    ToolRegistry.register(tool)
    yield tool
    ToolRegistry._tools.pop(tool.name, None)


def _run():
    return SimpleNamespace(id=uuid4(), company_id=uuid4(), user_id=uuid4(),
                           total_cost_usd=0, depth=0, max_depth=None)


def _entity(company_id, *, meta_agent=False, etype="AGENT"):
    return SimpleNamespace(
        id=uuid4(), name="writer", type=etype, company_id=company_id, goal="write",
        capabilities={"tools": [{"tool_id": "p32_context_spy"}]},
        planning={}, logic_gate={}, identity={}, io_contract={}, governance={},
        metadata_extensions={"is_meta_agent": True} if meta_agent else {},
    )


def _assert_platform_only(ctx: dict, run, entity) -> None:
    assert ctx["company_id"] == str(run.company_id)
    assert ctx["run_id"] == str(run.id)
    assert ctx["agent_id"] == str(entity.id)
    for key in ("container_runtime", "persistent_browser", "persona", "feature_flags", "input"):
        assert key not in ctx, key
    assert ctx["__is_meta_agent__"] is False
    assert ctx["__meta_max_runtime_creations__"] == 3


# ── the context itself ───────────────────────────────────────────────────────


def test_the_tool_context_carries_no_run_input():
    run = _run()
    entity = _entity(run.company_id)
    loop_state = {"__agent_state__": {"iteration": 2}, "__cortex_tree_id__": "t1"}
    ctx = ExecutionContext.for_run(run, entity, {**FORGED, **loop_state}).as_tool_context()
    _assert_platform_only(ctx, run, entity)
    assert ctx["__agent_state__"] == {"iteration": 2} and ctx["__cortex_tree_id__"] == "t1"


def test_the_meta_agent_gate_comes_from_the_entity():
    run = _run()
    meta = _entity(run.company_id, meta_agent=True)
    assert ExecutionContext.for_run(run, meta, {}).as_tool_context()["__is_meta_agent__"] is True


def test_each_call_gets_its_own_copy():
    ec = ExecutionContext.for_run(_run(), _entity(uuid4()), {})
    first = ec.as_tool_context()
    first["container_runtime"] = False
    assert "container_runtime" not in ec.as_tool_context()


# ── the two step paths hand tools the minted context ─────────────────────────


@pytest.mark.asyncio
async def test_a_react_tool_call_sees_the_platform_context_not_the_run_input(spy, monkeypatch):
    import src.ai.step_executor as se
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.schemas import PlanStep, StepType

    class _Router:
        def __init__(self, **_kw):
            pass

        async def call_llm_react(self, *, execute_tool_fn, **_kw):
            await execute_tool_fn([{"name": "p32_context_spy", "args": {"input": "go"}}])
            return SimpleNamespace(output="done", prompt_tokens=1, completion_tokens=1, latency_ms=1,
                                   provider="fake", model_name="fake", hit_turn_limit=False)

    monkeypatch.setattr(se, "LLMRouter", _Router)
    monkeypatch.setattr(FeatureFlags, "is_on", AsyncMock(return_value=False))
    db = MagicMock(commit=AsyncMock(), execute=AsyncMock(side_effect=RuntimeError("no db")))
    svc = se.StepExecutorService(db=db, redis=None, company_id=uuid4(),
                                 usage_service=MagicMock(), cortex_bridge=None)
    svc._log_usage = AsyncMock()
    svc._charge_tool = AsyncMock()
    svc._maybe_summarize_context = AsyncMock(side_effect=lambda _r, _e, ctx: ctx)
    monkeypatch.setattr(ToolAccess, "load", AsyncMock(return_value=ToolAccess(
        company_id=None, grants={"p32_context_spy": ToolGrant(tool_id="p32_context_spy")})))
    run = _run()
    entity = _entity(run.company_id)
    step = PlanStep(step_id="s1", name="write", type=StepType.THOUGHT, target={"prompt_template": "{{input}}"})

    await svc._execute_thought(run, entity, step, dict(FORGED))

    [call] = spy.seen
    _assert_platform_only(call["context"], run, entity)


@pytest.mark.asyncio
async def test_a_plan_tool_call_sees_the_platform_context_and_only_its_input(spy, monkeypatch):
    import src.ai.step_executor as se
    from src.ai.schemas import PlanStep, StepType

    monkeypatch.setattr(ToolAccess, "load", AsyncMock(return_value=ToolAccess(
        company_id=None, grants={"p32_context_spy": ToolGrant(tool_id="p32_context_spy")})))
    svc = se.StepExecutorService(db=MagicMock(commit=AsyncMock()), redis=None, company_id=uuid4(),
                                 usage_service=MagicMock(), cortex_bridge=None)
    svc._charge_tool = AsyncMock()
    run = _run()
    entity = _entity(run.company_id)
    step = PlanStep(step_id="s1", name="spy", type=StepType.TOOL_CALL,
                    target={"tool_id": "p32_context_spy", "prompt_template": '{"q": "x"}'})

    await svc._execute_tool_call(run, entity, step, dict(FORGED))

    [call] = spy.seen
    _assert_platform_only(call["context"], run, entity)
    assert json.loads(call["input"]) == {"q": "x"}  # the context is not merged into the input


# ── tools take the company from the context only (TL-03) ─────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module, cls", [
    ("src.ai.tools.email.email_tool", "EmailSendTool"),
    ("src.ai.tools.email.email_tool", "EmailIngestTool"),
    ("src.ai.tools.documents.docx_tool", "DocxTool"),
    ("src.ai.tools.documents.pptx_tool", "PptxTool"),
    ("src.ai.tools.documents.excel", "ExcelTool"),
    ("src.ai.tools.documents.document_save", "DocumentSaveTool"),
    ("src.ai.tools.documents.pdf_generator", "PDFGeneratorTool"),
    ("src.ai.tools.media.image_generation", "ImageGenerationTool"),
    ("src.ai.tools.media.video.video_generate", "VideoGenerateTool"),
    ("src.ai.tools.social.linkedin", "LinkedInCreatePostTool"),
])
async def test_a_tool_called_without_a_context_refuses_a_model_supplied_company(module, cls):
    import importlib
    tool = getattr(importlib.import_module(module), cls)()
    params = {
        "company_id": str(uuid4()), "to": "a@b.c", "subject": "s", "body": "b",
        "action": "create", "filename": "x.docx", "title": "t", "content": "c",
        "source_path": "/etc/hostname", "format": "docx", "prompt": "p", "text": "hello",
    }
    if tool.Params is not None:
        # A typed tool refuses a field it does not declare, ``company_id``
        # included: it is given its own fields, and still has no company.
        params = {k: v for k, v in params.items() if k in tool.Params.model_fields}
    out = await tool.run_with_context(json.dumps(params), context=None)
    assert NO_CONTEXT_ERROR in out


@pytest.mark.asyncio
async def test_file_writer_refuses_without_a_context():
    from src.ai.tools.core.file_writer import FileWriterTool
    out = await FileWriterTool().run_with_context(
        json.dumps({"filename": "a.txt", "content": "x", "company_id": str(uuid4())}), context=None)
    assert NO_CONTEXT_ERROR in out


# ── the API refuses platform keys in run input ───────────────────────────────


@pytest.mark.parametrize("key", [
    "__is_meta_agent__", "__agent_state__", "container_runtime", "cortex_tree_id",
    "feature_flags", "company_id",
])
def test_run_input_may_not_set_platform_keys(key):
    with pytest.raises(ValidationError, match=key):
        ExecutionRunCreate(entity_id=uuid4(), input_data={"input": "x", key: True})


def test_ordinary_run_input_is_accepted():
    body = ExecutionRunCreate(entity_id=uuid4(), input_data={"input": "x", "persona": "formal", "topic": "y"})
    assert body.input_data["persona"] == "formal"
