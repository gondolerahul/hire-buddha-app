"""Operations that reported success they did not have (P6.6 — TL-43…TL-49).

- TL-43 YouTube upload sent only metadata, to the metadata endpoint.
- TL-44 TikTok publish said success on init; publishing is asynchronous.
- TL-45 Instagram published a Reel before its container was encoded.
- TL-46 video_generate reported ``has_audio`` from an option it never sent.
- TL-47 LinkedIn advertised ``image_url`` and dropped it (and ``time_range``).
- TL-48 ``LinkedIn-Version: 202401`` was hardcoded four times here.
- TL-49 Google Ads created a budget and a campaign in two mutates.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import src.ai.tools.social.base as base

CTX = {"company_id": "00000000-0000-0000-0000-000000000001"}


@pytest.fixture
def platform(monkeypatch):
    """A scripted platform: each request gets the next response; requests are kept."""
    script: list = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return script.pop(0)

    real = httpx.AsyncClient

    def _client(timeout=None, **kw):
        return real(transport=httpx.MockTransport(handler), timeout=timeout)

    async def _no_wait(_s):
        return None

    import src.ai.social_connection_service as conns
    import src.common.net_guard as net_guard
    monkeypatch.setattr(base.httpx, "AsyncClient", _client)
    monkeypatch.setattr(base.asyncio, "sleep", _no_wait)
    monkeypatch.setattr(net_guard, "check_url", AsyncMock())
    monkeypatch.setattr(conns, "resolve_connection", AsyncMock(return_value={
        "access_token": "tok", "platform_page_id": "123", "platform_user_id": "ig1",
        "oauth_metadata": {"customer_id": "999", "developer_token": "dev"}}))
    return SimpleNamespace(script=script, requests=requests)


async def _run(tool, params):
    return json.loads(await tool.run_with_context(json.dumps(params), CTX))


@pytest.mark.asyncio
async def test_google_ads_creates_budget_and_campaign_in_one_mutate(platform, monkeypatch):
    from src.ai.tools.social import quota
    from src.ai.tools.social.google_ads import GoogleAdsCreateCampaignTool
    from src.automation.limits import AutomationLimits

    async def limits(company_id):
        return AutomationLimits(ads_monthly_ceiling=1000)

    monkeypatch.setattr("src.automation.limits.limits_for", limits)
    monkeypatch.setattr(quota, "draw", AsyncMock(return_value=None))
    platform.script += [
        httpx.Response(200, json=[{"results": []}]),          # the account's budgets, for the ceiling
        httpx.Response(200, json={"mutateOperationResponses": [
            {"campaignBudgetResult": {"resourceName": "customers/999/campaignBudgets/5"}},
            {"campaignResult": {"resourceName": "customers/999/campaigns/7"}}]})]
    out = await _run(GoogleAdsCreateCampaignTool(), {
        "campaign_name": "C", "campaign_type": "SEARCH", "budget_amount_micros": 1000000,
        "bidding_strategy": "MAXIMIZE_CLICKS"})
    budgets, req = platform.requests
    assert budgets.url.path.endswith("/googleAds:searchStream")
    assert req.url.path.endswith("/customers/999/googleAds:mutate")
    ops = json.loads(req.content)["mutateOperations"]
    temp = ops[0]["campaignBudgetOperation"]["create"]["resourceName"]
    assert temp == "customers/999/campaignBudgets/-1"
    assert ops[1]["campaignOperation"]["create"]["campaignBudget"] == temp
    assert out["campaign_resource"] == "customers/999/campaigns/7"


@pytest.mark.asyncio
async def test_youtube_uploads_the_bytes_to_the_session_it_opens(platform, monkeypatch):
    from src.ai.tools.social import quota
    from src.ai.tools.social.youtube import YouTubeUploadVideoTool

    monkeypatch.setattr(quota, "draw", AsyncMock(return_value=None))
    platform.script += [
        httpx.Response(200, headers={"content-type": "video/mp4", "content-length": "10"}),   # HEAD: the size
        httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session/abc"}),
        httpx.Response(200, content=b"VIDEOBYTES", headers={"content-type": "video/mp4"}),   # streamed
        httpx.Response(200, json={"id": "vid1"}),
        httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"}),
        httpx.Response(200, json={}),
    ]
    out = await _run(YouTubeUploadVideoTool(), {"title": "T", "video_url": "https://cdn.example.com/v.mp4",
                                                "made_for_kids": False, "contains_synthetic_media": False,
                                                "thumbnail_url": "https://cdn.example.com/t.png"})
    head, start, get, put, _thumb_get, thumb = platform.requests
    assert head.method == "HEAD" and get.method == "GET"
    assert start.url.path == "/upload/youtube/v3/videos" and start.headers["X-Upload-Content-Length"] == "10"
    assert (put.method, str(put.url), put.content) == ("PUT", "https://www.googleapis.com/upload/session/abc",
                                                       b"VIDEOBYTES")
    assert put.headers["Content-Range"] == "bytes 0-9/10"                     # one chunk, resumable (YT-E4)
    assert thumb.url.path == "/upload/youtube/v3/thumbnails/set" and thumb.url.params["videoId"] == "vid1"
    assert out["success"] and out["video_id"] == "vid1" and out["thumbnail_set"] is True


@pytest.mark.asyncio
async def test_youtube_without_a_session_is_a_failure(platform, monkeypatch):
    from src.ai.tools.social import quota
    from src.ai.tools.social.youtube import YouTubeUploadVideoTool

    monkeypatch.setattr(quota, "draw", AsyncMock(return_value=None))
    platform.script += [httpx.Response(200, headers={"content-type": "video/mp4", "content-length": "1"}),
                        httpx.Response(200)]
    out = await _run(YouTubeUploadVideoTool(), {"title": "T", "video_url": "https://cdn.example.com/v.mp4",
                                                "made_for_kids": False, "contains_synthetic_media": False})
    assert "error" in out and "Location" in out["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses,expect", [
    (["PROCESSING_DOWNLOAD", "PUBLISH_COMPLETE"], "published"),
    (["PROCESSING_DOWNLOAD", "FAILED"], "failed"),
    (["PROCESSING_DOWNLOAD", "PROCESSING_DOWNLOAD"], "processing"),
])
async def test_tiktok_reports_what_the_publish_became(platform, monkeypatch, statuses, expect):
    import src.ai.tools.social.tiktok as tiktok
    monkeypatch.setattr(tiktok, "_PUBLISH_POLLS", 2)
    monkeypatch.setattr(tiktok.asyncio, "sleep", AsyncMock())
    platform.script.append(httpx.Response(200, json={"data": {"publish_id": "p1"}}))
    platform.script += [httpx.Response(200, json={"data": {"status": st, "fail_reason": "bad_video"}})
                        for st in statuses]
    out = await _run(tiktok.TikTokPublishVideoTool(), {"video_url": "https://cdn.example.com/v.mp4", "title": "T"})
    if expect == "published":
        assert out["success"] and out["status"] == "PUBLISH_COMPLETE"
    elif expect == "failed":
        assert "bad_video" in out["error"]
    else:
        assert "success" not in out and "not published yet" in out["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("final,published", [("FINISHED", True), ("ERROR", False)])
async def test_instagram_publishes_a_reel_only_once_encoded(platform, monkeypatch, final, published):
    import src.ai.tools.social.instagram as ig
    monkeypatch.setattr(ig.asyncio, "sleep", AsyncMock())
    platform.script += [httpx.Response(200, json={"id": "c1"}),
                        httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
                        httpx.Response(200, json={"status_code": final}),
                        httpx.Response(200, json={"id": "m1"})]
    tool = ig.InstagramPublishMediaTool()
    out = await tool._publish_single("ig1", "tok", "reel", {"video_url": "https://cdn.example.com/r.mp4"}, "cap")
    paths = [r.url.path for r in platform.requests]
    assert paths.count("/v22.0/c1") == 2
    assert ("/v22.0/ig1/media_publish" in paths) is published
    assert out.get("success") is (True if published else None)


def test_linkedin_advertises_only_what_it_sends_and_one_version(monkeypatch):
    from src.ai.tools.social import linkedin
    from src.common.config import settings
    post = linkedin.LinkedInCreatePostTool().get_function_schema()["parameters"]["properties"]
    analytics = linkedin.LinkedInGetAnalyticsTool().get_function_schema()["parameters"]["properties"]
    assert "image_url" not in post and "time_range" not in analytics
    monkeypatch.setattr(settings, "LINKEDIN_API_VERSION", "209912", raising=False)
    assert linkedin._linkedin_version() == "209912"


@pytest.mark.asyncio
async def test_video_generate_sends_the_audio_option_it_reports():
    from src.ai.tools.media.video.video_generate import VideoGenerateTool
    seen = {}

    def _generate(**kw):
        seen["config"] = kw["config"]
        raise RuntimeError("stop after the request")

    client = SimpleNamespace(models=SimpleNamespace(generate_videos=_generate))
    with pytest.raises(RuntimeError):
        await VideoGenerateTool()._generate_single_video(
            client=client, model_name="veo", prompt="p", duration=4, output_path="x.mp4", generate_audio=False)
    assert seen["config"].generate_audio is False


@pytest.mark.asyncio
@pytest.mark.parametrize("on, people", [(False, "allow_adult"), (True, "allow_all")])
async def test_whom_a_video_may_depict_is_the_companys_policy(monkeypatch, on, people):
    """TL-46: person_generation was "allow_all" for every company."""
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.tools.media.video import video_generate as vg
    seen = {}

    async def _is_on(self, key, *, company_id=None, **_kw):
        seen["key"] = key
        return on

    def _generate(**kw):
        seen["config"] = kw["config"]
        raise RuntimeError("stop after the request")

    monkeypatch.setattr(FeatureFlags, "is_on", _is_on)
    policy = await vg.person_generation(CTX["company_id"])
    assert seen["key"] == "tools.video.people_of_all_ages" and policy == people
    client = SimpleNamespace(models=SimpleNamespace(generate_videos=_generate))
    with pytest.raises(RuntimeError):
        await vg.VideoGenerateTool()._generate_single_video(
            client=client, model_name="veo", prompt="p", duration=4, output_path="x.mp4",
            person_generation=policy)
    assert seen["config"].person_generation == people


@pytest.mark.asyncio
async def test_an_unreadable_policy_is_the_stricter_one(monkeypatch):
    from src.ai.core.feature_flags import FeatureFlags
    from src.ai.tools.media.video import video_generate as vg

    async def _broken(self, *_a, **_kw):
        raise OSError("database unavailable")

    monkeypatch.setattr(FeatureFlags, "is_on", _broken)
    assert await vg.person_generation(CTX["company_id"]) == "allow_adult"
