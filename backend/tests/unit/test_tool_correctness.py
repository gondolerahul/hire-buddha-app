"""Tool correctness (P6.8 — TL-31, TL-32/TL-57, TL-58, TL-61, TL-62, TL-60).

- TL-31: ``trim_clip``'s re-encode fallback raised ValueError, so it never ran.
- TL-57/TL-32: IMAP, SMTP and the Veo SDK blocked the worker's event loop, with
  no socket timeout on mail.
- TL-58: ``email_ingest`` returned sequence numbers labelled ``uid``;
  ``email_classify`` moved by them, and they renumber after every expunge.
- TL-61: ``sandbox_code`` took any timeout the model chose.
- TL-62: ``headless_browser`` opened a fresh session per call, so its
  click/type/get_text never composed; and every fallback into it sent an
  action it does not have.
- TL-60: ``batch_web_search`` ignored ``max_per_query``, never deduplicated and
  was billed one search for up to 25.
"""
from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

CTX = {"company_id": "c-1", "run_id": "r-1"}


# ── TL-31 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_trim_that_stream_copy_cannot_do_is_re_encoded(monkeypatch):
    from src.ai.tools.media.video import _ffmpeg
    calls = []

    async def _run(context, args, timeout):
        calls.append(list(args))
        if len(calls) == 1:
            raise _ffmpeg.FFmpegError("not on a keyframe")

    monkeypatch.setattr(_ffmpeg, "run_ffmpeg", _run)
    await _ffmpeg.trim_clip(None, "in.mp4", "out.mp4", start=1.5, duration=2)
    copy, reencode = calls
    assert copy[-3:] == ["-c", "copy", "out.mp4"]
    assert reencode == ["-ss", "1.5", "-i", "in.mp4", "-t", "2", "-c:v", "libx264", "-c:a", "aac", "out.mp4"]


# ── TL-61 ────────────────────────────────────────────────────────────────

def test_sandbox_code_holds_the_timeout_to_the_ceiling():
    from src.ai.tools.sandbox.sandbox_executor import SandboxCodeParams, SandboxCodeTool
    assert SandboxCodeParams(code="print(1)", timeout_s=9999).timeout_s == 120
    assert SandboxCodeTool().get_function_schema()["parameters"]["properties"]["timeout_s"]["maximum"] == 120


def test_sandbox_code_takes_fenced_plan_text():
    from src.ai.tools.sandbox.sandbox_executor import SandboxCodeTool
    params = SandboxCodeTool().parse_args("```bash\necho hi\n```")
    assert (params.language, params.code) == ("bash", "echo hi")


# ── TL-62 ────────────────────────────────────────────────────────────────

class _Page:
    url, log = "about:blank", []

    async def title(self):
        return "t"

    async def goto(self, url, **_kw):
        self.log.append(("goto", url))


@pytest.fixture
def browser(monkeypatch):
    import src.ai.tools.sandbox.browser_runner as br
    import src.ai.tools.sandbox.runtime as runtime
    import src.common.net_guard as net_guard
    sessions = []
    page = _Page()
    page.log = []

    @asynccontextmanager
    async def _open_page(**_kw):
        sessions.append(page)
        yield page

    async def _resolve(_ctx):
        return runtime.SubprocessRuntime()

    async def _dir(_ctx):
        return None

    async def _guard(_page):
        return []

    async def _public(_url):
        return None

    monkeypatch.setattr(br, "open_page", _open_page)
    monkeypatch.setattr(runtime, "resolve_sandbox_runtime", _resolve)
    monkeypatch.setattr(runtime, "resolve_persistent_browser_dir", _dir)
    monkeypatch.setattr(runtime, "guard_requests", _guard)
    monkeypatch.setattr(net_guard, "check_url", _public)

    def _action(name):
        async def act(pg, step, *_a):
            pg.log.append((name, step.get("url") or step.get("selector")))
            if step.get("selector") == "#missing":
                raise LookupError("not found")
            return {"url": "https://example.com/after"}
        return act

    for name in ("navigate", "click", "type", "get_text", "screenshot"):
        monkeypatch.setitem(br.ACTIONS, name, _action(name))
    from src.ai.tools.sandbox.browser_tool import HeadlessBrowserTool
    return SimpleNamespace(tool=HeadlessBrowserTool(), sessions=sessions, page=page)


@pytest.mark.asyncio
async def test_steps_run_in_order_on_one_page_in_one_session(browser):
    out = await browser.tool.invoke({"url": "https://example.com/login", "steps": [
        {"action": "type", "selector": "#user", "text": "me"},
        {"action": "click", "selector": "#go"},
        {"action": "get_text"},
    ]}, CTX)
    assert out.success and len(browser.sessions) == 1
    assert browser.page.log == [("goto", "https://example.com/login"), ("navigate", "https://example.com/login"),
                                ("type", "#user"), ("click", "#go"), ("get_text", None)]


@pytest.mark.asyncio
async def test_a_failing_step_stops_the_session_and_says_which(browser):
    out = await browser.tool.invoke({"steps": [{"action": "click", "selector": "#missing"},
                                               {"action": "get_text"}]}, CTX)
    assert not out.success and out.error == "step 1 (click): LookupError: not found"
    assert browser.page.log == [("click", "#missing")]


@pytest.mark.asyncio
async def test_the_single_action_form_is_one_step(browser):
    out = await browser.tool.invoke({"action": "navigate", "url": "https://example.com"}, CTX)
    assert out.success and browser.page.log == [("goto", "https://example.com"), ("navigate", "https://example.com")]


def test_every_fallback_into_the_browser_is_a_call_it_accepts():
    from src.ai.tool_fallback import _browser_to_scraper, _scraper_to_browser, _web_search_to_browser
    from src.ai.tools.core.scraper import ScraperTool
    from src.ai.tools.sandbox.browser_tool import HeadlessBrowserTool
    browser = HeadlessBrowserTool()
    for converted in (_web_search_to_browser('{"query": "ai agents"}'),
                      _scraper_to_browser('{"url": "https://example.com"}')):
        params = browser.parse_args(converted)                 # raised "extract_text" before
        assert [s.action for s in params.steps] == ["get_text"]
    assert ScraperTool().parse_args(_browser_to_scraper(
        json.dumps({"steps": [{"action": "navigate", "url": "https://e.com"}]}))).url == "https://e.com"


# ── TL-60 ────────────────────────────────────────────────────────────────

@pytest.fixture
def searches(monkeypatch):
    import src.ai.tools.core.batch_search as bs
    from src.ai.tools.core.search import WebSearchTool
    _sleep = asyncio.sleep
    monkeypatch.setattr(bs.asyncio, "sleep", lambda _s: _sleep(0))  # no rate-limit pauses here
    pages = {
        "q1": ([{"url": f"https://a/{i}", "title": f"a{i}", "snippet": ""} for i in range(8)], "serpapi"),
        "q2": ([{"url": "https://a/0", "title": "dup", "snippet": ""},
                {"url": "https://b/1", "title": "b1", "snippet": ""}], "serpapi"),
        "q3": ([{"url": "https://c/1", "title": "c1", "snippet": ""}], "ddg"),
    }

    async def _search(self, query, ctx):
        return pages[query]

    monkeypatch.setattr(WebSearchTool, "search", _search)
    return bs.BatchWebSearchTool()


@pytest.mark.asyncio
async def test_batch_keeps_max_per_query_drops_seen_urls_and_counts_paid_queries(searches):
    out = await searches.invoke({"queries": ["q1", "q2", "q3"], "max_per_query": 3}, CTX)
    assert out.success
    assert "a2" in out.output and "a3" not in out.output          # 3 of q1's 8
    assert "dup" not in out.output and "b1" in out.output          # q2's repeat of a/0 dropped
    assert out.metadata == {"billable_units": 2, "queries": 3, "duplicates_dropped": 1}


@pytest.mark.asyncio
async def test_batch_finds_the_queries_in_a_plan_steps_markdown(searches):
    text = '## Queries\n```json\n["q3"]\n```'
    out = await searches.invoke(text, CTX)
    assert out.success and "c1" in out.output and out.metadata["billable_units"] == 0


@pytest.mark.asyncio
async def test_a_charge_is_the_price_times_the_units(monkeypatch):
    from src.ai.governance.tool_cost_resolver import ToolCostResolver
    from src.ai.services.cost_attribution import CostLedger
    rows = []

    async def _add(self, **kw):
        rows.append(kw)

    async def _resolve(self, tool_id):
        return Decimal("0.01"), "registry", None

    monkeypatch.setattr(CostLedger, "add", _add)
    monkeypatch.setattr(ToolCostResolver, "resolve", _resolve)
    resolver = ToolCostResolver(None, "c-1")
    run = SimpleNamespace(id="r-1", company_id="c-1")
    assert (await resolver.charge(run=run, tool_id="batch_web_search", units=7)).amount == Decimal("0.07")
    assert rows[-1]["raw_quantity"] == 7.0
    assert (await resolver.charge(run=run, tool_id="web_search", units=0)).amount == 0 and len(rows) == 1


@pytest.mark.asyncio
async def test_web_search_bills_only_a_serpapi_answer(monkeypatch):
    from src.ai.tools.core.search import WebSearchTool

    async def _ddg(self, query, ctx):
        return [{"url": "https://x", "title": "x", "snippet": ""}], "ddg"

    monkeypatch.setattr(WebSearchTool, "search", _ddg)
    out = await WebSearchTool().invoke({"query": "x"}, CTX)
    assert out.metadata["billable_units"] == 0


# ── TL-58, TL-57 ─────────────────────────────────────────────────────────

class _Imap:
    def __init__(self, capabilities=("IMAP4REV1", "MOVE")):
        self.capabilities, self.calls, self.thread = capabilities, [], None

    def select(self, folder):
        self.thread = threading.get_ident()
        self.calls.append(("select", folder))

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b"41 42"]
        if command == "FETCH":
            return "OK", [(b"x", b"From: a@b\r\nSubject: s" + args[0] + b"\r\n\r\nbody")]
        return "OK", [None]

    def list(self, *_a):
        return "OK", [b"exists"]

    def logout(self):
        self.calls.append(("logout",))


@pytest.fixture
def mailbox(monkeypatch):
    from src.ai.tools.email import email_tool
    box = _Imap()

    async def _resolve(company_id, email_address=None):
        return {"imap_host": "imap.example.com", "imap_port": 993, "email_address": "me@example.com",
                "password": "p", "smtp_host": "smtp.example.com", "smtp_port": 587}

    monkeypatch.setattr(email_tool, "_resolve_connection", _resolve)
    monkeypatch.setattr(email_tool, "_get_imap_connection", lambda *a: box)
    return box


@pytest.mark.asyncio
async def test_ingest_returns_real_uids_and_does_not_block_the_loop(mailbox):
    from src.ai.tools.email.email_tool import EmailIngestTool
    out = json.loads(await EmailIngestTool().run_with_context(json.dumps({"count": 2}), CTX))
    assert [e["uid"] for e in out["emails"]] == ["42", "41"]
    assert ("uid", "SEARCH", None, "UNSEEN") in mailbox.calls
    assert mailbox.thread != threading.get_ident()          # ran in a worker thread


@pytest.mark.asyncio
async def test_classify_moves_by_uid(mailbox):
    from src.ai.tools.email.email_tool import EmailClassifyTool
    out = json.loads(await EmailClassifyTool().run_with_context(
        json.dumps({"uid": "42", "category": "Sales"}), CTX))
    assert out["success"] and ("uid", "MOVE", "42", "AI-Classified/Sales") in mailbox.calls


@pytest.mark.asyncio
async def test_without_move_classify_copies_flags_and_expunges_by_uid(mailbox):
    from src.ai.tools.email.email_tool import EmailClassifyTool
    mailbox.capabilities = ("IMAP4REV1", "UIDPLUS")
    await EmailClassifyTool().run_with_context(json.dumps({"uid": "42", "category": "Sales"}), CTX)
    assert [c[1] for c in mailbox.calls if c[0] == "uid"] == ["COPY", "STORE", "EXPUNGE"]


def test_mail_connections_have_a_timeout(monkeypatch):
    from src.ai.tools.email import email_tool
    seen = {}

    class _Fake:
        def __init__(self, host, port, timeout=None):
            seen["timeout"] = timeout

        def login(self, *_a):
            pass

    monkeypatch.setattr(email_tool.imaplib, "IMAP4_SSL", _Fake)
    email_tool._get_imap_connection("h", 993, "a", "p")
    assert seen["timeout"] == email_tool._MAIL_TIMEOUT_S
