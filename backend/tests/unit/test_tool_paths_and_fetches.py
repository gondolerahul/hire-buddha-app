"""Tools touch only the company's files and the public internet (P3.5).

TL-07 — a process-wide ``<root>/output`` symlink pointed at whichever company ran last.
TL-08 — no SSRF guard on ``scraper_tool`` or ``headless_browser``.
TL-54 — document, image and video tools read and wrote any host path the model gave.
TL-55 — ``pdf_generator`` rendered model HTML with a live fetcher, and its image
         search spanned every company's artifacts.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.artifact_service import ARTIFACT_BASE_DIR, ORIGIN_SYSTEM
from src.common.platform.storage import company_namespace, get_storage
from src.ai.tools.sandbox.workspace import (
    PathOutsideWorkspace, confine_path, safe_filename, tenant_workspace,
)
from src.common.net_guard import BlockedURL, check_url, check_url_sync

BACKEND_ENV = str(Path(__file__).resolve().parents[2] / ".env")


@pytest.fixture
def company():
    cid = str(uuid4())
    ws = Path(tenant_workspace(cid))
    ws.mkdir(parents=True, exist_ok=True)
    yield cid
    shutil.rmtree(ws, ignore_errors=True)
    shutil.rmtree(ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / cid, ignore_errors=True)
    shutil.rmtree(ARTIFACT_BASE_DIR / company_namespace(cid), ignore_errors=True)


def _ctx(cid):
    return {"company_id": cid, "run_id": str(uuid4())}


# ── confinement ──────────────────────────────────────────────────────────────


def test_a_relative_path_resolves_in_the_workspace(company):
    assert confine_path(company, "scratch/a.docx") == os.path.realpath(
        os.path.join(tenant_workspace(company), "scratch", "a.docx"))


def test_the_companys_artifacts_are_reachable(company):
    own = ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / company / "2026-10-01" / "r.docx"
    assert confine_path(company, str(own)) == os.path.realpath(own)


@pytest.mark.parametrize("path", [
    BACKEND_ENV,
    "../../etc/passwd",
    "../" + "x" * 8 + "/secret.txt",
])
def test_host_paths_and_escapes_are_refused(company, path):
    with pytest.raises(PathOutsideWorkspace):
        confine_path(company, path)


def test_another_companys_artifacts_are_refused(company):
    other = ARTIFACT_BASE_DIR / ORIGIN_SYSTEM / str(uuid4()) / "x.pdf"
    with pytest.raises(PathOutsideWorkspace):
        confine_path(company, str(other))


def test_a_symlink_out_of_the_workspace_is_refused(company, tmp_path):
    link = Path(tenant_workspace(company)) / "escape"
    try:
        os.symlink(tmp_path, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this platform")
    with pytest.raises(PathOutsideWorkspace):
        confine_path(company, "escape/file.txt")


def test_an_output_name_has_no_directory():
    assert safe_filename("../../etc/cron.d/x.docx", "d.docx") == "x.docx"
    assert safe_filename("..", "d.docx") == "d.docx"
    assert safe_filename("a\\..\\b.xlsx", "d.xlsx") == "b.xlsx"


# ── the tools ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module, cls, params", [
    ("src.ai.tools.documents.docx_tool", "DocxTool", {"action": "read", "file_path": BACKEND_ENV}),
    ("src.ai.tools.documents.pptx_tool", "PptxTool", {"action": "read", "file_path": BACKEND_ENV}),
    ("src.ai.tools.documents.excel", "ExcelTool", {"action": "read_rows", "file_path": BACKEND_ENV}),
    ("src.ai.tools.documents.docx_tool", "DocxTool",
     {"action": "update", "file_path": "a.docx", "save_as": "/tmp/../etc/owned.docx"}),
    ("src.ai.tools.documents.document_save", "DocumentSaveTool",
     {"source_path": BACKEND_ENV, "filename": "env", "format": "pdf"}),
    ("src.ai.tools.media.image_generation", "ImageGenerationTool",
     {"prompt": "x", "reference_image_path": BACKEND_ENV}),
    ("src.ai.tools.media.video.video_generate", "VideoGenerateTool",
     {"prompt": "x", "start_frame_path": BACKEND_ENV}),
    ("src.ai.tools.media.video.video_edit", "VideoEditTool",
     {"operation": "concat", "inputs": [BACKEND_ENV]}),
    ("src.ai.tools.media.video.video_add_sound", "VideoAddSoundTool",
     {"video_path": BACKEND_ENV, "source": "file"}),
])
async def test_a_tool_refuses_a_path_outside_the_companys_files(company, module, cls, params):
    import importlib
    tool = getattr(importlib.import_module(module), cls)()
    out = json.loads(await tool.run_with_context(json.dumps(params), _ctx(company)))
    assert "outside this company's workspace" in out.get("error", ""), out


@pytest.mark.asyncio
async def test_docx_create_keeps_its_file_in_the_companys_artifacts(company, monkeypatch):
    from src.ai.tools.documents.docx_tool import DocxTool
    import src.ai.artifact_service as artifact_service

    async def _keep(context, *, file_name, file_bytes, **_kw):
        # save_artifact's own storage, without the database row.
        key = artifact_service.new_storage_key(ORIGIN_SYSTEM, "documents", context["company_id"], file_name)
        await get_storage().put(key, file_bytes)
        return type("A", (), {"id": "a-1", "file_path": str(get_storage().local_path(key))})()

    monkeypatch.setattr(artifact_service, "save_tool_output", _keep)
    out = json.loads(await DocxTool().run_with_context(json.dumps({
        "action": "create", "filename": "../../../../escape.docx", "title": "t", "sections": [],
    }), _ctx(company)))
    assert out.get("status") == "success", out
    path = Path(out["file_path"]).resolve()
    assert path.name.endswith("_escape.docx")
    from src.ai.tools.sandbox.workspace import company_roots
    assert any(Path(root).resolve() in path.parents for root in company_roots(company))
    # ...and a follow-up call can name the path the tool returned.
    assert confine_path(company, out["file_path"]) == os.path.realpath(out["file_path"])
    shutil.rmtree(path.parents[1], ignore_errors=True)


def test_sandbox_code_no_longer_links_a_shared_output_dir():
    import inspect
    from src.ai.tools.sandbox import sandbox_executor
    assert "os.symlink" not in inspect.getsource(sandbox_executor)


# ── fetches ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost:8000/api/v1/health",
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://100.64.0.1/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "gopher://example.com/",
])
async def test_internal_and_non_web_urls_are_refused(url):
    with pytest.raises(BlockedURL):
        await check_url(url)
    with pytest.raises(BlockedURL):
        check_url_sync(url)


@pytest.mark.asyncio
async def test_a_public_address_is_allowed():
    await check_url("https://93.184.215.14/")
    check_url_sync("https://93.184.215.14/")


@pytest.mark.asyncio
async def test_a_name_that_resolves_inside_is_refused(monkeypatch):
    import src.common.net_guard as ng
    monkeypatch.setattr(ng, "_addresses", AsyncMock(return_value=["93.184.215.14", "10.1.2.3"]))
    with pytest.raises(BlockedURL, match="10.1.2.3"):
        await check_url("https://rebind.example/")


@pytest.mark.asyncio
async def test_the_scraper_refuses_an_internal_url_before_any_request(company, monkeypatch):
    import httpx
    from src.ai.tools.core.scraper import ScraperTool
    post = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    out = await ScraperTool().invoke({"url": "http://169.254.169.254/latest/meta-data/"}, _ctx(company))
    assert not out.success and "URL refused" in out.error
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_browser_checks_every_request_the_page_makes():
    from src.ai.tools.sandbox.runtime import guard_requests

    page = SimpleNamespace(handler=None)

    async def _route(pattern, handler):
        page.handler = handler
    page.route = _route
    refused = await guard_requests(page)

    def _req(url):
        return SimpleNamespace(request=SimpleNamespace(url=url), continue_=AsyncMock(), abort=AsyncMock())

    inside, outside, inline = _req("http://169.254.169.254/x"), _req("https://93.184.215.14/a.js"), _req("data:,x")
    for r in (inside, outside, inline):
        await page.handler(r)
    inside.abort.assert_awaited_once()
    inside.continue_.assert_not_awaited()
    outside.continue_.assert_awaited_once()
    inline.continue_.assert_awaited_once()
    assert refused == ["http://169.254.169.254/x"]


@pytest.mark.asyncio
async def test_browser_navigate_refuses_an_internal_url():
    from src.ai.tools.sandbox.browser_runner import run_step
    from src.common.net_guard import check_url
    page = SimpleNamespace(goto=AsyncMock())
    out = await run_step(page, {"action": "navigate", "url": "http://localhost:8000/"}, 1000, None, check_url)
    assert out["status"] == "error" and "URL refused" in out["error"]
    page.goto.assert_not_awaited()


def test_the_pdf_renderer_fetches_only_company_files_and_public_urls(company, monkeypatch):
    from src.ai.tools.documents import pdf_generator as pg
    fetched = []
    # The real fetch (WeasyPrint's URLFetcher.fetch) records instead of fetching.
    monkeypatch.setattr(pg.URLFetcher, "fetch", lambda self, url, headers=None: fetched.append(url) or {})
    fetch = pg._guarded_fetcher(company)
    assert isinstance(fetch, pg.URLFetcher)  # WeasyPrint 66+ takes a URLFetcher, not a function
    own = Path(tenant_workspace(company)) / "chart.png"
    own.write_bytes(b"png")
    fetch(own.as_uri())
    fetch("https://93.184.215.14/logo.png")
    fetch("data:image/png;base64,AAAA")
    for url in (Path(BACKEND_ENV).as_uri(), "http://169.254.169.254/", "ftp://example.com/x"):
        with pytest.raises(ValueError):
            fetch(url)
    assert len(fetched) == 3
