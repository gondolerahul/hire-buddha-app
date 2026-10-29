"""Wave 3 of the connector fixes (docs/phase15/14_connector_approvals/10): no database.

Retention rules in the catalog (SH-E2), what staff see (SH-E6), LinkedIn as its
Page with one client (LI-E3…E5, X-E7), the conversation rules (META-E4/E5),
YouTube's streamed uploads, analytics and reports (YT-E4, YT-E6), Google Ads'
Demand Gen, ceiling, reports and allowance (GADS-E3/E5/E6), the Drive tool
(GOOG-E4) and the API's security headers (SH-E5). The database-backed halves are
in tests/integration/test_wave3_data_rules.py.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest


class _Reply:
    def __init__(self, body, status=200, headers=None):
        self._body, self.status_code, self.headers = body, status, headers or {}

    def json(self):
        return self._body


# ── Retention by source (SH-E2, LI-E2, X-E4, YT-E5) ─────────────────────────

def test_each_providers_limit_is_in_its_catalog_entry():
    from src.connections.catalog import load_specs

    specs = load_specs()
    linkedin, x, youtube = specs["linkedin_org"].retention, specs["x_account"].retention, specs["youtube_channel"].retention
    assert (linkedin.hours, linkedin.results, linkedin.records) == (23, True, False)   # inside LinkedIn's 24 h
    assert linkedin.exempt == ["get_analytics"] and linkedin.exempt_hours == 8760      # the Page's statistics: a year
    assert (x.hours, x.records) == (23, False) and "24 hours" in x.rule
    assert youtube.hours == 720 and "get_analytics" in youtube.exempt and youtube.exempt_hours is None
    assert specs["gmail"].retention.hours is None and specs["gmail"].retention.records  # Google: while used


def test_a_call_notes_the_connections_it_used():
    from src.connections import source_data

    source_data.note_use("c1", "linkedin_org")      # outside a watched call: nothing
    with source_data.watch() as used:
        source_data.note_use("c1", "linkedin_org")
        source_data.note_use("c1", "linkedin_org")
        source_data.note_use("c2", "gmail")
    assert used == [{"connection_id": "c1", "connector_id": "linkedin_org"},
                    {"connection_id": "c2", "connector_id": "gmail"}]


async def test_a_write_or_a_call_outside_a_run_is_not_marked():
    from src.connections import source_data

    used = [{"connection_id": "00000000-0000-0000-0000-000000000009", "connector_id": "linkedin_org"}]
    post = {"platform": "linkedin", "operation": "create_post", "payload": {"text": "Hi"}}
    assert await source_data.mark({"company_id": "c", "run_id": "r"}, "social_api", post, used) == 0
    assert await source_data.mark({}, "social_api", {"operation": "manage_comments"}, used) == 0


def test_the_removal_notice_names_the_provider_and_its_rule():
    from datetime import datetime

    from src.connections.source_data import notice

    text = notice([SimpleNamespace(connector_id="linkedin_org")], datetime(2026, 10, 29, 10, 0))
    assert text.startswith("[Removed 2026-10-29 10:00 UTC") and "LinkedIn" in text and "48 hours" in text


# ── Staff and connected-account content (SH-E6) ─────────────────────────────

def test_only_staff_working_in_another_business_are_held_back():
    from src.auth.support_access import staff_elsewhere

    business = "00000000-0000-0000-0000-00000000000b"
    assert staff_elsewhere(SimpleNamespace(role="app_admin", company_id="platform"), business)
    assert staff_elsewhere(SimpleNamespace(role="app_user", company_id="platform"), business)
    assert not staff_elsewhere(SimpleNamespace(role="app_admin", company_id=business), business)
    assert not staff_elsewhere(SimpleNamespace(role="tenant_admin", company_id="other"), business)
    assert not staff_elsewhere(SimpleNamespace(role="partner_admin", company_id="p"), business)  # under their grants


def test_a_withheld_run_keeps_what_it_did_and_loses_what_it_read():
    from datetime import datetime

    from src.ai.schemas.execution import ExecutionRunResponse
    from src.auth.support_access import Access, withhold_run

    now = datetime.utcnow()
    run = ExecutionRunResponse.model_validate({
        "id": "00000000-0000-0000-0000-000000000001", "entity_id": "00000000-0000-0000-0000-000000000002",
        "company_id": "00000000-0000-0000-0000-00000000000b", "parent_run_id": None, "error_message": None,
        "started_at": now, "completed_at": now,
        "status": "COMPLETED", "created_at": now, "input_data": {"input": "Read Asha's mail"},
        "result_data": {"output": "Asha wants a refund"}, "context_state": {"memo": "x"}, "dynamic_plan": None,
        "tool_logs": [{"id": "00000000-0000-0000-0000-000000000003", "tool_id": "email_ingest",
                       "tool_name": "email_ingest", "input_parameters": {"limit": 5},
                       "output_result": "From: asha@x.test", "success": True, "latency_ms": 40, "created_at": now}],
        "llm_logs": [{"id": "00000000-0000-0000-0000-000000000004", "model_provider": "google", "model_name": "g",
                      "input_prompt": "Asha's mail", "output_response": "refund", "prompt_tokens": 1,
                      "completion_tokens": 1, "latency_ms": 9, "created_at": now}],
        "human_approvals": [{"id": "00000000-0000-0000-0000-000000000005", "checkpoint_trigger": "CONNECTOR_ACTION",
                             "status": "PENDING", "requested_at": now,
                             "context_snapshot": {"kind": "connector_action", "tool": "email_send",
                                                  "content": "Dear Asha"}}],
    })
    withheld = withhold_run(run, Access(withheld={str(run.id): ["gmail"]}))
    text = json.dumps(withheld.model_dump(mode="json"))
    assert "Asha" not in text and "refund" not in text
    assert withheld.tool_logs[0].tool_name == "email_ingest" and withheld.tool_logs[0].latency_ms == 40
    assert withheld.human_approvals[0].context_snapshot["tool"] == "email_send"
    assert withheld.content_withheld["connectors"] == ["gmail"] and "Gmail" in withheld.content_withheld["message"]


def test_a_live_frame_keeps_its_kind_and_loses_its_content():
    from src.auth.support_access import withhold_frame

    frame = json.loads(withhold_frame(json.dumps({"type": "span_end", "kind": "tool", "name": "email_ingest",
                                                  "payload": {"output": "Asha"}, "cost_usd": 0.1})))
    assert frame["type"] == "span_end" and frame["name"] == "email_ingest" and frame["cost_usd"] == 0.1
    assert "Asha" not in json.dumps(frame) and "support access" in frame["payload"]


# ── LinkedIn as its Page, one client (LI-E3…E5, X-E7) ───────────────────────

PAGE = {"access_token": "t", "platform_user_id": "urn:li:organization:42",
        "oauth_metadata": {"organization_urn": "urn:li:organization:42"}}


async def test_linkedin_posts_and_replies_as_the_page(monkeypatch):
    from src.ai.tools.social import linkedin

    sent = []

    async def request(method, url, **kw):
        sent.append((method, url, kw.get("json_body")))
        return _Reply({}, headers={"x-restli-id": "urn:li:share:7"})

    monkeypatch.setattr(linkedin.LinkedInCreatePostTool, "_api_request", staticmethod(request))
    monkeypatch.setattr(linkedin.LinkedInManageCommentsTool, "_api_request", staticmethod(request))
    out = await linkedin.LinkedInCreatePostTool()._execute({"text": "Hiring"}, PAGE, None)
    assert out["author"] == "urn:li:organization:42" and sent[0][2]["author"] == "urn:li:organization:42"
    await linkedin.LinkedInManageCommentsTool()._execute(
        {"action": "create", "post_id": "urn:li:share:7", "comment_text": "Thanks!"}, PAGE, None)
    method, url, body = sent[-1]
    assert body["actor"] == "urn:li:organization:42" and "urn%3Ali%3Ashare%3A7" in url
    refused = await linkedin.LinkedInCreatePostTool()._execute({"text": "x"}, {"access_token": "t"}, None)
    assert "names no Page" in refused["error"]


async def test_linkedin_comments_carry_the_least_member_data(monkeypatch):
    from src.ai.tools.social import linkedin

    async def request(method, url, **kw):
        return _Reply({"elements": [{"$URN": "urn:li:comment:(urn:li:share:7,9)", "actor": "urn:li:person:abc",
                                     "message": {"text": "Love it"}, "created": {"time": 1}, "likesSummary": {
                                         "totalLikes": 2}, "commenter": {"firstName": "Asha", "headline": "CTO"}}]})

    monkeypatch.setattr(linkedin.LinkedInManageCommentsTool, "_api_request", staticmethod(request))
    out = await linkedin.LinkedInManageCommentsTool()._execute({"action": "list", "post_id": "urn:li:share:7"},
                                                               PAGE, None)
    assert out["comments"] == [{"comment_urn": "urn:li:comment:(urn:li:share:7,9)", "author": "urn:li:person:abc",
                                "text": "Love it", "created_at_ms": 1, "likes": 2}]
    assert "Asha" not in json.dumps(out) and "forbid saving" in out["note"]


async def test_linkedin_reads_the_pages_statistics_and_no_members_profile(monkeypatch):
    from src.ai.tools.social import linkedin

    urls = []

    async def request(method, url, **kw):
        urls.append(url)
        return _Reply({"elements": []})

    monkeypatch.setattr(linkedin.LinkedInGetAnalyticsTool, "_api_request", staticmethod(request))
    await linkedin.LinkedInGetAnalyticsTool()._execute({"analytics_type": "post", "post_id": "urn:li:share:7"},
                                                       PAGE, None)
    assert urls[-1].endswith("organizationalEntity=urn%3Ali%3Aorganization%3A42&shares=List(urn%3Ali%3Ashare%3A7)")
    profile = await linkedin.LinkedInGetProfileTool()._execute({"profile_type": "user"}, PAGE, None)
    assert "not members' profiles" in profile["error"]


async def test_linkedin_and_x_never_fall_back_to_old_rows(monkeypatch):
    from src.common.config import settings
    from src.connections import client, service

    monkeypatch.setattr(settings, "CONNECTIONS_LEGACY_FALLBACK", True)
    monkeypatch.setattr(service, "connections_for", AsyncMock(return_value=[]))
    legacy = AsyncMock(return_value={"access_token": "old"})
    monkeypatch.setattr(client, "_legacy", legacy)
    ctx = {"company_id": "00000000-0000-0000-0000-000000000001", "agent_id": "a"}
    for platform in ("linkedin", "twitter", "x"):
        assert await client.credentials_for(ctx, platform) == {}
    assert not legacy.called
    assert (await client.credentials_for(ctx, "tiktok"))["access_token"] == "old"   # no connector yet: still

    from fastapi import HTTPException

    from src.ai.social_router import _connector_only
    with pytest.raises(HTTPException) as gone:
        _connector_only("linkedin")
    assert gone.value.status_code == 410
    _connector_only("tiktok")


# ── Conversations (META-E4, META-E5) ────────────────────────────────────────

def test_a_request_for_a_person_and_stop_words_are_recognised():
    from src.messaging.rules import opt_keyword, wants_person

    for text in ("human", "Can I talk to a person?", "speak to someone please", "I want customer service"):
        assert wants_person(text), text
    for text in ("my agent told me", "the person who ordered", "hello"):
        assert not wants_person(text), text
    assert opt_keyword("STOP") == "out" and opt_keyword(" start ") == "in" and opt_keyword("stop the order") is None


async def test_messenger_replies_say_they_come_from_an_ai_and_wait_while_a_person_has_it(monkeypatch):
    from datetime import datetime, timedelta

    from src.ai.tools.social import facebook
    from src.messaging import rules

    sent = []

    async def request(method, url, **kw):
        sent.append(kw["json_body"])
        return _Reply({"recipient_id": "psid-1", "message_id": "m1"})

    async def fresh(company_id, sender):
        return datetime.utcnow() - timedelta(hours=1)

    monkeypatch.setattr(facebook.FacebookSendMessageTool, "_api_request", staticmethod(request))
    monkeypatch.setattr(facebook, "last_message_at", fresh)
    replied = AsyncMock()
    monkeypatch.setattr(rules, "replied", replied)
    monkeypatch.setattr(rules, "before_reply", AsyncMock(return_value=rules.Reply(
        text=f"{rules.disclosure('Acme')}\n\nYour order ships today.", disclosed=True)))
    tool, ctx = facebook.FacebookSendMessageTool(), {"company_id": "00000000-0000-0000-0000-000000000001"}
    out = await tool._execute({"recipient_id": "psid-1", "message_text": "Your order ships today."},
                              {"access_token": "t", "platform_page_id": "page1"}, ctx)
    assert out["disclosed_ai"] and sent[0]["message"]["text"].startswith("You're chatting with Acme's AI assistant")
    assert replied.await_args.kwargs["disclosed"] is True
    monkeypatch.setattr(rules, "before_reply", AsyncMock(return_value=rules.Reply(text="x", refusal="A person has it")))
    assert (await tool._execute({"recipient_id": "psid-1", "message_text": "x"}, {"access_token": "t"}, ctx)
            )["error"] == "A person has it" and len(sent) == 1


def test_a_customers_message_to_a_page_is_read_for_the_rules():
    from src.connections.webhooks import _dm

    data = {"platform": "facebook", "account_id": "page1",
            "value": {"sender": {"id": "psid1"}, "message": {"text": "human please"}}}
    assert _dm(data) == ("messenger", "page1", "psid1", "human please")
    assert _dm({**data, "value": {"sender": {"id": "page1"}, "message": {"text": "x", "is_echo": True}}}) is None
    assert _dm({**data, "platform": "instagram"})[0] == "instagram"


# ── YouTube: streamed uploads, analytics, reports (YT-E4, YT-E6) ────────────

async def _stream(*parts):
    for part in parts:
        yield part


async def test_a_video_is_sent_in_chunks_of_256_kib_multiples():
    from src.ai.tools.social import youtube

    chunks = [(len(c), last) async for c, last in youtube._chunks(_stream(b"a" * 5, b"b" * 7, b"c" * 2), 4)]
    assert chunks == [(4, False), (4, False), (4, False), (2, True)]
    assert youtube.UPLOAD_CHUNK_BYTES % (256 * 1024) == 0


async def test_an_upload_resumes_from_what_youtube_holds_after_a_failure(monkeypatch):
    from src.ai.tools.social import youtube

    puts = []

    def answer(request: httpx.Request) -> httpx.Response:
        puts.append((request.headers["content-range"], len(request.content)))
        if len(puts) == 1:
            return httpx.Response(503)                                   # the first chunk fails
        if request.headers["content-range"] == "bytes */10":
            return httpx.Response(308, headers={"range": "bytes=0-3"})   # YouTube holds 4 of its bytes
        return httpx.Response(200, json={"id": "vid1", "status": {"uploadStatus": "uploaded"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(youtube.httpx, "AsyncClient",
                        lambda timeout=None, **kw: real(transport=httpx.MockTransport(answer), timeout=timeout))
    monkeypatch.setattr(youtube.asyncio, "sleep", AsyncMock())
    video = await youtube._send_chunks("https://upload.example/s", "t", youtube._Source(_stream(b"0123456789"), 10,
                                                                                         "video/mp4"))
    assert video["id"] == "vid1"
    assert puts == [("bytes 0-9/10", 10), ("bytes */10", 0), ("bytes 4-9/10", 6)]


async def test_an_upload_streams_from_the_business_files_within_its_daily_share(monkeypatch):
    from src.ai.tools.social import quota, youtube

    sent = {}

    async def request(method, url, **kw):
        sent["headers"] = kw["headers"]
        return _Reply({}, headers={"Location": "https://upload.example/session"})

    async def source(params, context):
        return youtube._Source(_stream(b"bytes"), 5, "video/mp4")

    async def chunks(location, token, src):
        return {"id": "vid1", "status": {"uploadStatus": "uploaded"}}

    monkeypatch.setattr(youtube.YouTubeUploadVideoTool, "_api_request", staticmethod(request))
    monkeypatch.setattr(youtube, "_video_source", source)
    monkeypatch.setattr(youtube, "_send_chunks", chunks)
    monkeypatch.setattr(quota, "draw", AsyncMock(return_value=None))
    params = {"title": "Demo", "video_key": "t-acme/videos/demo.mp4", "made_for_kids": False,
              "contains_synthetic_media": False}
    done = await youtube.YouTubeUploadVideoTool()._execute(params, {"access_token": "t"}, {"company_id": "c"})
    assert done["video_id"] == "vid1" and done["upload_status"] == "uploaded"
    assert sent["headers"]["X-Upload-Content-Length"] == "5"
    monkeypatch.setattr(quota, "draw", AsyncMock(return_value="This business has used its share"))
    refused = await youtube.YouTubeUploadVideoTool()._execute(params, {"access_token": "t"}, {"company_id": "c"})
    assert refused["error"].startswith("This business has used its share")


async def test_a_file_of_another_business_is_not_uploaded(monkeypatch):
    from src.ai.tools.social import youtube

    monkeypatch.setattr("src.common.platform.storage.company_namespaces", lambda company_id: ["t-acme"])
    with pytest.raises(ValueError, match="not one of this business's files"):
        await youtube._video_source({"video_key": "t-other/v.mp4"}, {"company_id": "c"})


def test_youtubes_upload_refusals_are_said_plainly():
    from src.ai.tools.social.youtube import _upload_error

    quota_out = httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
    limit = httpx.Response(403, json={"error": {"errors": [{"reason": "uploadLimitExceeded"}]}})
    assert "midnight Pacific" in _upload_error(quota_out) and "upload limit" not in _upload_error(quota_out)
    assert "limits how many videos" in _upload_error(limit)


async def test_analytics_answer_by_traffic_source_as_youtubes_numbers(monkeypatch):
    from src.ai.tools.social.youtube import YouTubeGetAnalyticsTool

    asked = {}

    async def request(method, url, **kw):
        asked.update(kw["params"])
        return _Reply({"columnHeaders": [{"name": "insightTrafficSourceType"}, {"name": "views"}],
                       "rows": [["ADVERTISING", 120], ["YT_SEARCH", 30]]})

    monkeypatch.setattr(YouTubeGetAnalyticsTool, "_api_request", staticmethod(request))
    tool = YouTubeGetAnalyticsTool()
    out = await tool._execute({"analytics_type": "video", "video_id": "v1", "metrics": "views",
                               "dimensions": "insightTrafficSourceType"}, {"access_token": "t"}, None)
    assert asked["filters"] == "video==v1" and asked["dimensions"] == "insightTrafficSourceType"
    assert out["rows"][0] == {"insightTrafficSourceType": "ADVERTISING", "views": 120}
    assert out["source"] == "YouTube Analytics" and "HireBuddha's" in out["note"]
    bad = await tool._execute({"analytics_type": "channel", "dimensions": "planet"}, {"access_token": "t"}, None)
    assert "unknown dimensions" in bad["error"]


async def test_bulk_reports_are_listed_created_and_read(monkeypatch):
    from src.ai.tools.social.youtube import YouTubeManageReportsTool

    async def request(method, url, **kw):
        if url.endswith("/jobs") and method == "POST":
            return _Reply({"id": "job1", "reportTypeId": kw["json_body"]["reportTypeId"]})
        return _Reply({"jobs": [{"id": "job1", "reportTypeId": "channel_basic_a2", "name": "n"}]})

    async def report(url, token):
        return "date,views\n20261027,10\n20261028,12\n"

    monkeypatch.setattr(YouTubeManageReportsTool, "_api_request", staticmethod(request))
    monkeypatch.setattr(YouTubeManageReportsTool, "_report_text", staticmethod(report))
    tool = YouTubeManageReportsTool()
    assert (await tool._execute({"action": "list", "what": "jobs"}, {"access_token": "t"}, None))["jobs"][0]["id"] == "job1"
    made = await tool._execute({"action": "create", "report_type_id": "channel_basic_a2"}, {"access_token": "t"}, None)
    assert made["job_id"] == "job1"
    rows = await tool._execute({"action": "get", "download_url": "https://youtubereporting.googleapis.com/v1/media/x"},
                               {"access_token": "t"}, None)
    assert rows["rows"] == [{"date": "20261027", "views": "10"}, {"date": "20261028", "views": "12"}]
    assert "error" in await tool._execute({"action": "get", "download_url": "https://evil.example/x"},
                                          {"access_token": "t"}, None)


# ── Google Ads (GADS-E3, GADS-E5, GADS-E6) ──────────────────────────────────

ADS = {"access_token": "t", "oauth_metadata": {"customer_id": "123-456-7890"}}
CTX = {"company_id": "00000000-0000-0000-0000-000000000001"}


@pytest.fixture
def ads(monkeypatch):
    """Google Ads played by URL; the business's ceiling and the daily allowance."""
    from src.ai.tools.social import google_ads, quota
    from src.automation.limits import AutomationLimits

    state = SimpleNamespace(sent=[], budgets=[], ceiling=10_000)

    async def request(method, url, **kw):
        body = kw.get("json_body") or {}
        state.sent.append((url, body))
        if url.endswith("googleAds:searchStream"):
            if "currency_code" in body.get("query", ""):
                return _Reply([{"results": [{"customer": {"currencyCode": "INR"}}]}])
            if "campaign_budget" in body.get("query", ""):
                return _Reply([{"results": [{"campaignBudget": {"resourceName": f"b{i}", "amountMicros": str(a)}}
                                            for i, a in enumerate(state.budgets)]}])
            return _Reply([{"results": [{"metrics": {"costMicros": "2500000", "impressions": "10"}}]}])
        return _Reply({"mutateOperationResponses": [{"campaignResult": {"resourceName": "customers/1/campaigns/2"}},
                                                    {"adGroupResult": {"resourceName": "customers/1/adGroups/3"}}]})

    async def limits(company_id):
        return AutomationLimits(ads_monthly_ceiling=state.ceiling)

    async def download(url, max_bytes):
        return b"PNGDATA", "image/png"

    for cls in (google_ads.GoogleAdsCreateCampaignTool, google_ads.GoogleAdsCreateDemandGenCampaignTool,
                google_ads.GoogleAdsReportTool):
        monkeypatch.setattr(cls, "_api_request", staticmethod(request))
    monkeypatch.setattr(google_ads.GoogleAdsCreateDemandGenCampaignTool, "_download", staticmethod(download))
    monkeypatch.setattr("src.automation.limits.limits_for", limits)
    monkeypatch.setattr(quota, "draw", AsyncMock(return_value=None))
    return state


DEMAND_GEN = {"campaign_name": "Diwali", "daily_budget_micros": 100_000_000, "contains_eu_political_advertising": False,
              "locations": ["IN"], "languages": ["en", "hi"], "video_id": "dQw4w9WgXcQ", "final_url": "https://acme.test",
              "business_name": "Acme", "headlines": ["Diwali sale"], "long_headlines": ["Our biggest Diwali sale"],
              "descriptions": ["Up to 40% off"], "logo_image_url": "https://acme.test/logo.png",
              "call_to_action": "SHOP_NOW"}


async def test_a_demand_gen_campaign_is_made_paused_with_its_video_ad_in_one_mutate(ads):
    from src.ai.tools.social.google_ads import GoogleAdsCreateDemandGenCampaignTool

    out = await GoogleAdsCreateDemandGenCampaignTool()._execute(DEMAND_GEN, ADS, CTX)
    assert out["success"] and out["status"] == "PAUSED"
    url, body = ads.sent[-1]
    assert url.endswith("/customers/1234567890/googleAds:mutate")
    ops = body["mutateOperations"]
    kinds = [next(iter(op)) for op in ops]
    assert kinds == ["campaignBudgetOperation", "campaignOperation", "campaignCriterionOperation",
                     "campaignCriterionOperation", "campaignCriterionOperation", "adGroupOperation", "assetOperation",
                     "assetOperation", "assetOperation", "adGroupAdOperation"]
    campaign = ops[1]["campaignOperation"]["create"]
    assert campaign["advertisingChannelType"] == "DEMAND_GEN" and campaign["status"] == "PAUSED"
    assert ops[2]["campaignCriterionOperation"]["create"]["location"]["geoTargetConstant"] == "geoTargetConstants/2356"
    ad = ops[-1]["adGroupAdOperation"]["create"]["ad"]["demandGenVideoResponsiveAd"]
    assert ad["videos"] == [{"asset": "customers/1234567890/assets/-4"}] and ad["businessName"] == {"text": "Acme"}
    assert ops[6]["assetOperation"]["create"]["youtubeVideoAsset"]["youtubeVideoId"] == "dQw4w9WgXcQ"


async def test_a_campaign_past_the_monthly_ceiling_or_without_one_is_refused(ads):
    from src.ai.tools.social.google_ads import GoogleAdsCreateDemandGenCampaignTool

    ads.budgets = [250_000_000]                # an existing 250 a day: 7,600 a month already
    over = await GoogleAdsCreateDemandGenCampaignTool()._execute(DEMAND_GEN, ADS, CTX)   # +100 a day
    assert over["code"] == "over_ceiling" and "10,640 a month" in over["error"]
    ads.ceiling = None
    assert (await GoogleAdsCreateDemandGenCampaignTool()._execute(DEMAND_GEN, ADS, CTX))["code"] == "no_ceiling"
    bad = await GoogleAdsCreateDemandGenCampaignTool()._execute({**DEMAND_GEN, "headlines": ["x" * 41]}, ADS, CTX)
    assert "at most 40 characters" in bad["error"]


async def test_a_named_report_runs_over_its_dates_with_costs_in_the_accounts_currency(ads):
    from src.ai.tools.social.google_ads import GoogleAdsReportTool

    out = await GoogleAdsReportTool()._execute({"report": "video_performance", "date_range": "LAST_7_DAYS"}, ADS, CTX)
    query = ads.sent[0][1]["query"]
    assert "FROM video" in query and "DURING LAST_7_DAYS" in query and "metrics.video_trueview_views" in query
    assert out["currency"] == "INR" and out["source"] == "Google Ads"
    assert out["results"][0]["metrics"]["cost"] == 2.5 and out["results"][0]["metrics"]["costMicros"] == "2500000"


def test_google_ads_setup_and_rate_limit_answers_are_said_plainly():
    from src.ai.tools.social.google_ads import _ads_error

    setup = httpx.Response(403, text='{"error": {"details": [{"errors": [{"errorCode": {"authorizationError": '
                                     '"CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"}}]}]}}')
    assert _ads_error(setup)["code"] == "setup" and "HireBuddha's side" in _ads_error(setup)["error"]
    assert _ads_error(httpx.Response(429, text="RESOURCE_EXHAUSTED"))["code"] == "rate_limited"


async def test_the_daily_allowance_is_shared_and_each_business_has_a_share(monkeypatch):
    from src.ai.tools.social import quota

    store: dict = {}

    class Redis:
        async def incrby(self, key, amount):
            store[key] = store.get(key, 0) + amount
            return store[key]

        async def decrby(self, key, amount):
            store[key] -= amount

        async def expire(self, key, seconds):
            return True

    monkeypatch.setattr("src.common.redis_client.shared_redis", lambda: Redis())
    assert await quota.draw("ops", "a", amount=3, total=5, share=4, what="ops") is None
    assert "this business" in (await quota.draw("ops", "a", amount=2, total=5, share=4, what="ops")).lower()
    assert await quota.draw("ops", "b", amount=2, total=5, share=4, what="ops") is None
    assert "shared by all" in await quota.draw("ops", "b", amount=1, total=5, share=4, what="ops")
    assert sum(v for k, v in store.items() if k.count(":") == 2) == 5                     # nothing over the whole


# ── Google Drive: chosen files only (GOOG-E4) ───────────────────────────────

async def test_drive_opens_only_chosen_or_created_files_and_writes_wait(monkeypatch):
    from src.ai.governance.connector_actions import outbound
    from src.ai.tools.drive import google_drive
    from src.connections import client, service

    creds = {"access_token": "t", "connection_id": "conn1", "oauth_metadata": {
        "picked_files": [{"id": "doc1", "name": "Price list", "mime_type": "application/vnd.google-apps.document"}],
        "created_files": [{"id": "new1", "name": "Report"}]}}
    monkeypatch.setattr(client, "credentials_for", AsyncMock(return_value=creds))
    remembered = AsyncMock()
    monkeypatch.setattr(service, "remember_created_file", remembered)

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/export"):
            return httpx.Response(200, content=b"Prices: A 10, B 20")
        if request.method == "POST":
            return httpx.Response(200, json={"id": "new2", "name": "Notes", "mimeType": "text/plain"})
        return httpx.Response(200, json={"id": "doc1", "name": "Price list",
                                         "mimeType": "application/vnd.google-apps.document"})

    real = httpx.AsyncClient
    monkeypatch.setattr(google_drive.httpx, "AsyncClient",
                        lambda timeout=None, **kw: real(transport=httpx.MockTransport(answer), timeout=timeout))
    tool = google_drive.GoogleDriveTool()
    listed = await tool.execute(tool.Params(operation="list_files"), CTX)
    assert {f["id"] for f in listed.output["files"]} == {"doc1", "new1"}
    read = await tool.execute(tool.Params(operation="read_file", file_id="doc1"), CTX)
    assert read.output["text"] == "Prices: A 10, B 20"
    refused = await tool.execute(tool.Params(operation="read_file", file_id="secret9"), CTX)
    assert not refused.success and refused.error_code == "file_not_chosen"
    made = await tool.execute(tool.Params(operation="create_file", name="Notes", content="hi"), CTX)
    assert made.output["id"] == "new2" and remembered.await_args.args[2]["id"] == "new2"
    assert outbound("google_drive", {"operation": "create_file"}) and not outbound("google_drive",
                                                                                  {"operation": "read_file"})


# ── Security headers (SH-E5) ────────────────────────────────────────────────

def test_every_api_answer_carries_the_security_headers():
    from src.common.security_headers import HTML_POLICY, JSON_POLICY, headers_for

    json_answer = dict(headers_for("/api/v1/x", [(b"content-type", b"application/json")], 31536000))
    assert json_answer[b"strict-transport-security"] == b"max-age=31536000; includeSubDomains"
    assert json_answer[b"content-security-policy"] == JSON_POLICY.encode()
    assert json_answer[b"x-frame-options"] == b"DENY" and json_answer[b"x-content-type-options"] == b"nosniff"
    page = dict(headers_for("/webhook/provider/meta/data-deletion/HB1", [(b"content-type", b"text/html")], 1))
    assert page[b"content-security-policy"] == HTML_POLICY.encode()
    kept = dict(headers_for("/api/v1/files/1", [(b"content-security-policy", b"sandbox")], 1))
    assert b"content-security-policy" not in kept                                 # a route's own policy stays
    assert b"content-security-policy" not in dict(headers_for("/docs", [], 1))     # Swagger loads from a CDN
    assert b"strict-transport-security" not in dict(headers_for("/api/v1/x", [], 0))
