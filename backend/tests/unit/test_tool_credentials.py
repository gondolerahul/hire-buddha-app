"""Tools take credentials from the platform's records, never from the model (P3.4).

TL-04 / TL-56 — every email tool let the model's ``smtp_host``/``imap_host``,
                ``email_address`` and ``password`` override the company's
                connection row: one prompt injection made the tenant's mailbox
                an open relay, or sent its decrypted password to any server.
TL-05 — ``ScraperTool.run_typed`` dropped the execution context, so a typed
         call spent the platform's Firecrawl key and saved the tenant's page
         into the platform's artifact store.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.ai.governance.subjects import SubjectScope
from src.ai.tools.email import email_tool

ROW = {
    "email_address": "sales@tenant.example", "password": "row-secret",
    "imap_host": "imap.tenant.example", "imap_port": 993,
    "smtp_host": "smtp.tenant.example", "smtp_port": 587,
}
INJECTED = {
    "smtp_host": "smtp.attacker.example", "smtp_port": 25,
    "imap_host": "imap.attacker.example", "imap_port": 143,
    "password": "attacker-chosen", "email_address": "sales@tenant.example",
}
CTX = {"company_id": str(uuid4()), "run_id": str(uuid4())}
# The typed tools (P6.11) take raw recipients only for an entity that allows
# them; these tests are about credentials, not recipients.
FREE = {**CTX, "__allow_free_recipients__": True}
SERVER_FIELDS = {k: v for k, v in INJECTED.items() if k != "email_address"}


class _Stop(Exception):
    """Raised by the connection stub once it has seen the credentials."""


@pytest.fixture
def opened(monkeypatch):
    seen: list[tuple] = []

    def _capture(host, port, address, password):
        seen.append((host, port, address, password))
        raise _Stop()

    monkeypatch.setattr(email_tool, "_resolve_connection", AsyncMock(return_value=dict(ROW)))
    monkeypatch.setattr(email_tool, "_get_smtp_connection", _capture)
    monkeypatch.setattr(email_tool, "_get_imap_connection", _capture)
    monkeypatch.setattr(email_tool, "scope_for", AsyncMock(return_value=SubjectScope()))
    return seen


@pytest.mark.asyncio
async def test_email_send_uses_the_connection_rows_server_and_password(opened):
    params = {"email_address": "sales@tenant.example", "to": "a@b.example", "subject": "s", "body": "b"}
    # A server or password in the arguments is not a field: refused, nothing opened.
    refused = await email_tool.EmailSendTool().invoke({**params, **SERVER_FIELDS}, FREE)
    assert refused.error_code == "invalid_arguments" and opened == []
    await email_tool.EmailSendTool().run_with_context(json.dumps(params), FREE)
    assert opened == [("smtp.tenant.example", 587, "sales@tenant.example", "row-secret")]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls, extra", [
    (email_tool.EmailIngestTool, {}),
    (email_tool.EmailClassifyTool, {"uid": "1", "category": "leads"}),
    (email_tool.EmailDraftTool, {"to": "a@b.example", "subject": "s", "draft_body": "b",
                                 "original_message_id": "<m@x>"}),
])
async def test_the_imap_tools_use_the_connection_rows_server_and_password(opened, cls, extra):
    args = {**INJECTED, **extra}
    if cls.Params is not None:
        # A typed tool refuses the server fields outright; then it is called without them.
        assert (await cls().invoke(args, FREE)).error_code == "invalid_arguments" and opened == []
        args = {**extra, "email_address": INJECTED["email_address"]}
    await cls().run_with_context(json.dumps(args), FREE)
    assert opened, "the tool never opened a connection"
    assert opened[0] == ("imap.tenant.example", 993, "sales@tenant.example", "row-secret")


@pytest.mark.asyncio
async def test_an_address_with_no_connection_row_is_refused(monkeypatch):
    monkeypatch.setattr(email_tool, "_resolve_connection", AsyncMock(return_value={}))
    smtp = MagicMock()
    monkeypatch.setattr(email_tool, "_get_smtp_connection", smtp)
    monkeypatch.setattr(email_tool, "scope_for", AsyncMock(return_value=SubjectScope()))
    out = await email_tool.EmailSendTool().invoke(
        {"email_address": "ceo@elsewhere.example", "to": "a@b.example", "subject": "s", "body": "b"}, FREE)
    assert out.error_code == "no_connection"
    smtp.assert_not_called()


# ── TL-05 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_typed_scraper_call_keeps_its_context(monkeypatch):
    from src.ai.tools.core.scraper import ScraperTool
    from src.ai.tool_executor import ToolExecutor
    from src.ai.governance.tool_access import ToolAccess
    from src.ai.schemas.capabilities import ToolGrant

    seen = []

    async def _scrape(self, url, purpose, context):
        seen.append(context)
        return {"status": "success"}

    monkeypatch.setattr(ScraperTool, "_scrape", _scrape)
    access = ToolAccess(company_id=None, grants={"scraper_tool": ToolGrant(tool_id="scraper_tool")})
    [tr] = await ToolExecutor.execute_from_function_calls(
        [{"name": "scraper_tool", "args": {"url": "https://example.com"}}],
        extra_context=CTX, access=access)
    assert tr.success and seen == [CTX]
    assert (await ScraperTool().invoke({"url": "https://example.com"}, CTX)).success and seen[-1] == CTX


@pytest.mark.asyncio
async def test_the_scraper_without_a_context_does_not_use_the_platforms_key():
    from src.ai.tools.base import NO_CONTEXT_ERROR
    from src.ai.tools.core.scraper import ScraperTool
    out = await ScraperTool().run_with_context(json.dumps({"url": "https://example.com"}), None)
    assert NO_CONTEXT_ERROR in out
