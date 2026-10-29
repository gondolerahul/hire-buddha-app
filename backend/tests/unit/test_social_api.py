"""One social primitive (P6.2 — R2, PO-07, TL-40, decision D17).

52 per-verb social tools each put a function declaration in the prompt, and
three lists disagreed on the platforms: the connection API took 8, the refresh
table covered the same 8, and tools existed for 13 — so 20 tools could never
get a credential. Now ``social_api(platform, operation, payload)`` is the one
registered tool, ``describe`` lists a platform's operations, and the platforms
are one list.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

import src.ai.tools  # noqa: F401
from src.ai.social_connection_service import PLATFORM_REFRESH_CONFIG
from src.ai.social_router import VALID_PLATFORMS
from src.ai.tools.base import ToolRegistry, ToolStatus, tool_category
from src.ai.tools.social.social_api import SOCIAL_PLATFORMS, SocialAPITool, operations

CTX = {"company_id": "00000000-0000-0000-0000-000000000001", "run_id": "r-1"}


def test_the_platforms_are_one_list():
    assert set(operations()) == set(PLATFORM_REFRESH_CONFIG) == VALID_PLATFORMS == set(SOCIAL_PLATFORMS)
    schema = ToolRegistry._tools["social_api"].get_function_schema()["parameters"]
    assert schema["properties"]["platform"]["enum"] == list(SOCIAL_PLATFORMS)
    assert schema["required"] == ["platform", "operation"]


def test_one_registered_tool_opt_in_and_listed_as_social():
    social = [n for n in ToolRegistry._tools if any(n.startswith(p + "_") for p in SOCIAL_PLATFORMS)]
    assert social == []
    tool = ToolRegistry._tools["social_api"]
    assert tool.status is ToolStatus.EXPERIMENTAL and tool_category(tool) == "social"


@pytest.mark.asyncio
async def test_describe_lists_a_platforms_operations_and_their_parameters():
    out = await SocialAPITool().invoke({"platform": "twitter", "operation": "describe"}, CTX)
    described = json.loads(out.output)
    ops = {o["operation"]: o for o in described["operations"]}
    assert set(ops) == {"create_post", "search", "get_mentions", "get_analytics"}
    assert ops["create_post"]["writes"] is True and ops["search"]["writes"] is False
    assert ops["create_post"]["parameters"]["required"] == ["text"]


@pytest.mark.asyncio
async def test_what_social_api_refuses():
    tool = SocialAPITool()
    unknown_platform = await tool.invoke({"platform": "pinterest", "operation": "describe"}, CTX)
    assert unknown_platform.error_code == "invalid_arguments" and "linkedin" in unknown_platform.error
    unknown_op = await tool.invoke({"platform": "twitter", "operation": "delete_everything"}, CTX)
    assert unknown_op.error_code == "unknown_operation" and "create_post" in unknown_op.error
    bad_payload = await tool.invoke({"platform": "twitter", "operation": "create_post",
                                     "payload": {"txt": "typo"}}, CTX)
    assert bad_payload.error_code == "invalid_arguments"
    assert "missing ['text']" in bad_payload.error and "unknown ['txt']" in bad_payload.error


@pytest.mark.asyncio
async def test_an_operation_runs_with_the_calls_context_and_the_companys_connection(monkeypatch):
    import src.connections.client as client
    from src.ai.tools.social.twitter import TwitterCreatePostTool
    # X is reached through its connector only (X-E7): the run's agent's x_account connection.
    resolve = AsyncMock(return_value={"access_token": "tok", "source": "connections"})
    seen = {}

    async def _execute(self, params, credentials, context):
        seen.update(params=params, credentials=credentials, context=context)
        return {"success": True, "tweet_id": "1"}

    monkeypatch.setattr(client, "credentials_for", resolve)
    monkeypatch.setattr(TwitterCreatePostTool, "_execute", _execute)
    out = await SocialAPITool().invoke({"platform": "twitter", "operation": "create_post",
                                        "payload": {"text": "hello"}}, CTX)
    assert out.success and json.loads(out.output)["tweet_id"] == "1"
    # X charges per post: the call carries its price for the business (X-E5).
    assert out.metadata == {"platform": "twitter", "operation": "create_post", "writes": True,
                            "also_bill": {"x_post": 1}}
    assert seen["params"] == {"text": "hello"} and seen["context"]["company_id"] == CTX["company_id"]
    assert resolve.await_args.args[0]["company_id"] == CTX["company_id"] and resolve.await_args.args[1] == "twitter"


@pytest.mark.asyncio
async def test_a_platform_error_is_a_failed_call(monkeypatch):
    import src.ai.social_connection_service as conns
    monkeypatch.setattr(conns, "resolve_connection", AsyncMock(return_value={}))
    out = await SocialAPITool().invoke({"platform": "reddit", "operation": "search",
                                        "payload": {"query": "x"}}, CTX)
    assert not out.success and "No active reddit connection" in out.error
