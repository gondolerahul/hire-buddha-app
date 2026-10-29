"""Social calls wait out load and say when a list is partial (P6.4 — TL-37, TL-38).

``_api_request`` re-raised every status error at once — 429 and 5xx included,
the errors platforms return under load — and its two retries (timeouts and
refused connections only) were immediate. And every list operation returned
page one as if it were the whole set.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

import src.ai.tools.social.base as base
from src.ai.tools.social.base import SocialMediaTool, next_page

_REAL_CLIENT = httpx.AsyncClient


@pytest.fixture
def server(monkeypatch):
    """A scripted platform: each request takes the next response."""
    script: list = []
    seen: list = []
    waits: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    real = httpx.AsyncClient

    def _client(timeout=None):
        return real(transport=httpx.MockTransport(handler), timeout=timeout)

    async def _sleep(s):
        waits.append(s)

    monkeypatch.setattr(base.httpx, "AsyncClient", _client)
    monkeypatch.setattr(base.asyncio, "sleep", _sleep)
    return type("S", (), {"script": script, "seen": seen, "waits": waits})


def ok(body=None):
    return httpx.Response(200, json=body or {"ok": True})


@pytest.mark.asyncio
async def test_a_read_waits_out_5xx_and_succeeds(server):
    server.script += [httpx.Response(503), httpx.Response(502), ok()]
    resp = await SocialMediaTool._api_request("GET", "https://api.example.com/x")
    assert resp.status_code == 200 and len(server.waits) == 2


@pytest.mark.asyncio
async def test_retry_after_is_honoured_and_capped(server):
    server.script += [httpx.Response(429, headers={"Retry-After": "7"}),
                      httpx.Response(429, headers={"Retry-After": "600"}), ok()]
    await SocialMediaTool._api_request("GET", "https://api.example.com/x")
    assert server.waits == [7.0, 30.0]


@pytest.mark.asyncio
async def test_a_write_is_retried_on_429_only(server):
    server.script += [httpx.Response(429), ok()]
    assert (await SocialMediaTool._api_request("POST", "https://api.example.com/p")).status_code == 200
    server.script += [httpx.Response(503)]
    with pytest.raises(httpx.HTTPStatusError):
        await SocialMediaTool._api_request("POST", "https://api.example.com/p")   # may have posted
    server.script += [httpx.ReadTimeout("slow")]
    with pytest.raises(httpx.TimeoutException):
        await SocialMediaTool._api_request("POST", "https://api.example.com/p")
    assert server.seen == ["POST", "POST", "POST", "POST"]


@pytest.mark.asyncio
async def test_a_client_error_is_not_retried_and_retries_end(server):
    server.script += [httpx.Response(404)]
    with pytest.raises(httpx.HTTPStatusError):
        await SocialMediaTool._api_request("GET", "https://api.example.com/x")
    server.script += [httpx.Response(503)] * 4
    with pytest.raises(httpx.HTTPStatusError):
        await SocialMediaTool._api_request("GET", "https://api.example.com/x")
    assert len(server.seen) == 1 + 4


@pytest.mark.parametrize("body,cursor", [
    ({"paging": {"next": "https://g/next", "cursors": {"after": "AFTER"}}}, "AFTER"),   # Facebook, Instagram
    ({"paging": {"start": 0, "count": 10, "total": 25}}, "10"),                          # LinkedIn
    ({"paging": {"start": 20, "count": 10, "total": 25}}, None),
    ({"meta": {"next_token": "NT"}}, "NT"),                                              # X
    ({"nextPageToken": "PT"}, "PT"),                                                     # Google, YouTube
    ({"data": {"after": "t3_x", "children": []}}, "t3_x"),                               # Reddit
    ({"data": {"has_more": True, "cursor": 40}}, "40"),                                  # TikTok
    ({"data": {"has_more": False, "cursor": 40}}, None),
    ({"data": [1, 2]}, None),
])
def test_each_platforms_next_page(body, cursor):  # noqa: D103
    assert next_page(body) == cursor


@pytest.mark.asyncio
async def test_a_list_operation_says_it_is_partial(server, monkeypatch):
    import src.connections.client as conns   # X is reached through its connector (X-E7)
    from src.ai.tools.social.twitter import TwitterSearchTool
    monkeypatch.setattr(conns, "credentials_for", AsyncMock(return_value={"access_token": "t"}))
    server.script += [ok({"data": [{"id": "1", "text": "a"}], "meta": {"next_token": "NEXT"}})]
    out = json.loads(await TwitterSearchTool().run_with_context(
        json.dumps({"query": "ai"}), {"company_id": "00000000-0000-0000-0000-000000000001"}))
    assert out["truncated"] is True
    assert base.decode_page(out["next_page"])["v"] == "NEXT"


# ── the next page can be fetched (TL-38) ────────────────────────────────

@pytest.fixture
def connected(server, monkeypatch):
    import src.connections.client as conns   # X is reached through its connector (X-E7)
    monkeypatch.setattr(conns, "credentials_for",
                        AsyncMock(return_value={"access_token": "t", "platform_user_id": "42"}))
    requests: list = []
    real = _REAL_CLIENT

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return server.script.pop(0)

    monkeypatch.setattr(base.httpx, "AsyncClient",
                        lambda timeout=None: real(transport=httpx.MockTransport(handler), timeout=timeout))
    return requests


_CTX = {"company_id": "00000000-0000-0000-0000-000000000001"}


async def _call(tool, payload):
    return json.loads(await tool.run_with_context(json.dumps(payload), _CTX))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name, payload, param", [
    ("TwitterSearchTool", {"query": "ai"}, "next_token"),
    ("TwitterGetMentionsTool", {}, "pagination_token"),
])
async def test_the_next_page_is_fetched_with_the_platforms_cursor(server, connected, tool_name, payload, param):
    """An operation said ``truncated`` and gave ``next_page``, but took no
    cursor: the model could see there was more and never fetch it."""
    from src.ai.tools.social import twitter
    tool = getattr(twitter, tool_name)()
    server.script += [ok({"data": [{"id": "1", "text": "a"}], "meta": {"next_token": "NT2"}}),
                      ok({"data": [{"id": "2", "text": "b"}], "meta": {}})]
    first = await _call(tool, payload)
    second = await _call(tool, {**payload, "page": first["next_page"]})
    assert connected[0].url.params.get(param) is None
    assert connected[1].url.params[param] == "NT2"
    assert "truncated" not in second and "page_ignored" not in second


@pytest.mark.asyncio
async def test_a_list_read_by_post_takes_the_cursor_in_its_body(server, connected):
    from src.ai.tools.social.tiktok import TikTokGetVideosTool
    server.script += [ok({"data": {"videos": [{"id": 1}], "has_more": True, "cursor": 20}}),
                      ok({"data": {"videos": [{"id": 2}], "has_more": False, "cursor": 40}})]
    first = await _call(TikTokGetVideosTool(), {})
    await _call(TikTokGetVideosTool(), {"page": first["next_page"]})
    assert json.loads(connected[1].content)["cursor"] == "20"


@pytest.mark.asyncio
async def test_a_page_from_another_operation_is_not_applied(server, connected):
    from src.ai.tools.social.twitter import TwitterGetMentionsTool, TwitterSearchTool
    server.script += [ok({"data": [], "meta": {"next_token": "NT2"}}), ok({"data": [], "meta": {}})]
    first = await _call(TwitterSearchTool(), {"query": "ai"})
    out = await _call(TwitterGetMentionsTool(), {"page": first["next_page"]})
    assert out["page_ignored"] is True
    assert "next_token" not in connected[1].url.params and "pagination_token" not in connected[1].url.params


@pytest.mark.asyncio
async def test_a_page_this_tool_did_not_give_is_refused(server, connected):
    from src.ai.tools.social.twitter import TwitterSearchTool
    out = await _call(TwitterSearchTool(), {"query": "ai", "page": "not-a-page"})
    assert "not a next_page" in out["error"] and connected == []


@pytest.mark.asyncio
async def test_reads_take_a_page_and_writes_do_not():
    from src.ai.tools.social.social_api import SocialAPITool
    described = json.loads((await SocialAPITool().invoke(
        {"platform": "twitter", "operation": "describe"}, _CTX)).output)
    ops = {o["operation"]: o for o in described["operations"]}
    assert "page" in ops["search"]["parameters"]["properties"]
    assert "page" not in ops["create_post"]["parameters"]["properties"]
    refused = await SocialAPITool().invoke(
        {"platform": "twitter", "operation": "create_post", "payload": {"text": "hi", "page": "x"}}, _CTX)
    assert not refused.success and "unknown ['page']" in refused.error
