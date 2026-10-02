"""One tool contract, one entry point (P6.1 — TL-41, TL-30, TX-I2).

A tool could be entered through ``run``, ``run_with_context``, ``run_typed``
or the executor's reflection, which discovered ``run_typed`` by type hints and
fell back to the string path silently on any error; two classes were named
``ToolResult``. Now a tool declares ``Params`` and ``execute``; ``invoke`` is
the one entry point — arguments that do not fit are a failed call naming the
fields — and the function schema is derived from ``Params``. Tools not yet
converted run through one adapter in ``invoke`` (decision D16).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from pydantic import Field

import src.ai.tools  # noqa: F401  (registers every tool)
from src.ai.tool_executor import ToolExecutor
from src.ai.tools.base import Tool, ToolOutput, ToolParams, ToolRegistry

CTX = {"company_id": "c-1", "run_id": "r-1"}

# Tools still on the adapter (D16). This list may only shrink: a new tool
# declares ``Params``; converting one removes it from here.
UNCONVERTED = {
    "agent_introspect", "agent_reflect", "batch_web_search", "crm_update_lead",
    "document_save", "docx_tool", "email_classify", "email_draft", "email_ingest", "email_send",
    "excel_tool", "file_writer", "get_current_datetime", "google_calendar_create_event",
    "headless_browser", "image_generation", "meta_entity_creator", "meta_entity_executor",
    "meta_platform_introspect", "meta_registry_search", "meta_schema_validator", "meta_spec_critic",
    "pdf_generator", "pptx_tool", "sandbox_code", "terminal", "tool_synthesis", "video_add_sound",
    "video_edit", "video_generate", "whatsapp_send_tenant",
    # social: collapsed into one typed primitive in P6.2
    "facebook_create_post", "facebook_get_insights", "facebook_manage_comments", "facebook_send_message",
    "google_ads_create_campaign", "google_ads_get_ad_groups", "google_ads_manage_keywords", "google_ads_report",
    "instagram_discover_hashtags", "instagram_get_insights", "instagram_manage_comments", "instagram_publish_media",
    "linkedin_ads_create_campaign", "linkedin_ads_manage_audiences", "linkedin_ads_manage_creatives",
    "linkedin_ads_report", "linkedin_create_post", "linkedin_get_analytics", "linkedin_get_profile",
    "linkedin_manage_comments", "linkedin_sales_get_lead", "linkedin_sales_get_lists", "linkedin_sales_save_lead",
    "linkedin_sales_search_leads", "meta_ads_create_campaign", "meta_ads_manage_adsets",
    "meta_ads_manage_audiences", "meta_ads_report", "pinterest_create_pin", "pinterest_get_analytics",
    "pinterest_manage_boards", "pinterest_search_pins", "reddit_create_post", "reddit_get_analytics",
    "reddit_manage_comments", "reddit_search", "snapchat_ads_create_campaign", "snapchat_ads_manage_ad_squads",
    "snapchat_ads_manage_audiences", "snapchat_ads_report", "tiktok_get_analytics", "tiktok_get_videos",
    "tiktok_manage_comments", "tiktok_publish_video", "twitter_create_post", "twitter_get_analytics",
    "twitter_get_mentions", "twitter_search", "youtube_get_analytics", "youtube_manage_comments",
    "youtube_manage_playlists", "youtube_upload_video",
}


class _EchoParams(ToolParams):
    text: str = Field(..., description="What to echo")
    times: int = Field(1, ge=1, le=3, description="How many times")


class _Echo(Tool):
    name = "p61_echo"
    description = "Echoes."
    Params = _EchoParams
    string_field = "text"

    async def execute(self, params: _EchoParams, ctx: Dict[str, Any]) -> ToolOutput:
        return ToolOutput(output=" ".join([params.text] * params.times) + f" for {ctx.get('company_id')}")


def test_a_new_tool_is_typed_and_the_unconverted_list_only_shrinks():
    unconverted = {n for n, t in ToolRegistry._tools.items() if t.Params is None}
    assert unconverted <= UNCONVERTED, f"new untyped tools: {sorted(unconverted - UNCONVERTED)}"


def test_the_schema_is_derived_from_params():
    schema = _Echo().get_function_schema()
    params = schema["parameters"]
    assert params["required"] == ["text"]
    assert params["properties"]["times"] == {"type": "integer", "minimum": 1, "maximum": 3,
                                             "default": 1, "description": "How many times"}
    assert ToolRegistry._tools["web_search"].get_function_schema()["parameters"]["required"] == ["query"]


@pytest.mark.asyncio
async def test_invoke_validates_and_names_what_is_wrong():
    out = await _Echo().invoke({"text": "hi", "times": 9, "volume": 3}, CTX)
    assert not out.success and out.error_code == "invalid_arguments"
    assert "times" in out.error and "volume" in out.error and "required ['text']" in out.error


@pytest.mark.asyncio
async def test_a_plan_steps_text_fills_the_string_field_and_json_is_an_object():
    assert (await _Echo().invoke("hello", CTX)).output == "hello for c-1"
    assert (await _Echo().invoke('{"text": "x", "times": 2}', CTX)).output == "x x for c-1"


@pytest.mark.asyncio
async def test_the_legacy_bridge_and_adapter():
    assert await _Echo().run_with_context("hey", CTX) == "hey for c-1"
    assert (await _Echo().run_with_context('{"times": 2}', CTX)).startswith("Error: p61_echo: invalid arguments")

    class _Old(Tool):
        name, description = "p61_old", "old"

        async def run_with_context(self, input_data, context=None):
            return f"got {input_data}"

    assert (await _Old().invoke({"input": "plain", "x": 1}, CTX)).output == "got plain"
    assert (await _Old().invoke({"a": 1, "company_id": "spoof"}, CTX)).output == 'got {"a": 1}'


@pytest.mark.asyncio
async def test_the_executor_has_one_path_for_model_calls_and_plan_steps():
    tool = _Echo()

    class _Access:  # what the entity may run: here, the echo
        def resolve(self, name, via):
            return tool

    access = _Access()
    [bad] = await ToolExecutor.execute_from_function_calls(
        [{"name": "p61_echo", "args": {"times": 2}}], CTX, access=access)
    assert not bad.success and "required ['text']" in bad.error          # no silent fallback
    [good] = await ToolExecutor.execute_tools([{"tool": "p61_echo", "input": "plan text"}], CTX, access=access)
    assert good.success and good.output == "plan text for c-1"


@pytest.mark.asyncio
async def test_web_search_returns_the_number_of_results_asked_for(monkeypatch):
    from src.ai.tools.core.search import WebSearchTool
    tool = WebSearchTool()
    monkeypatch.setattr(WebSearchTool, "_resolve_keys", lambda self, ctx: _async({}))
    monkeypatch.setattr(WebSearchTool, "_search_ddg_library", lambda self, q: _async(
        [{"title": f"t{i}", "url": f"https://e/{i}", "snippet": ""} for i in range(10)]))
    out = await tool.invoke({"query": "x", "num_results": 3}, CTX)
    assert out.success and "3. t2" in out.output and "4. t3" not in out.output


async def _async(value):
    return value


def test_there_is_one_tool_result_class():
    import src.ai.tools.base as base
    assert not hasattr(base, "ToolResult") and not hasattr(Tool, "run_typed")
