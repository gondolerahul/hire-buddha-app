"""First-party social SKILLs: what a platform is for and how to work it (R2, P6.3).

The 52 per-verb social tools carried their platform knowledge in function
schemas, in every prompt that granted them. Now one primitive, ``social_api``,
does the calls, and a SKILL per platform carries the knowledge: when to use
which operation, the platform's rules, and what to report. A SKILL's version
is data — editing it is not a deploy.

Each SKILL grants only ``social_api`` (EXPERIMENTAL: the company must opt in
with ``tools.experimental.social_api``) and asks the model to ``describe`` the
platform before acting, so the operations it uses are the ones that exist.
"""
from __future__ import annotations

from typing import Any, Dict, List

_COMMON = (
    "Use the social_api tool for every call to {label}. First call it with "
    'platform "{platform}" and operation "describe" to see the operations and their parameters; '
    "use only those. Credentials come from the company's {label} connection — never ask for "
    "tokens or passwords. If a result says truncated, more results exist: say so. If an "
    "operation fails, report the platform's error as given; do not retry a post, a message or a "
    "campaign you are not sure failed (a write is never repeated within a run). Before publishing "
    "anything public, check it against the instructions you were given; when the instructions do "
    "not say to publish, draft and report instead."
)

PLATFORMS: List[Dict[str, Any]] = [
    {
        "platform": "linkedin", "label": "LinkedIn",
        "goal": "Publish, monitor and answer on LinkedIn for the company.",
        "guidance": (
            "Posts: create_post; keep a post under 3,000 characters; use link_url for a link "
            "preview; post_as_organization posts as the company page. Images are not supported. "
            "Analytics: get_analytics with analytics_type post (needs post_id) or page. Comments: "
            "manage_comments to list, reply or delete. Profile: get_profile."
        ),
    },
    {
        "platform": "twitter", "label": "X (Twitter)",
        "goal": "Publish, search and monitor on X for the company.",
        "guidance": (
            "Posts: create_post; 280 characters for a standard account; reply_to_tweet_id builds a "
            "thread one post at a time. search accepts X operators (from:, #tag, -term). "
            "get_mentions and get_analytics take tweet ids."
        ),
    },
    {
        "platform": "facebook", "label": "Facebook",
        "goal": "Publish to and look after the company's Facebook Page.",
        "guidance": (
            "Page posts: create_post. Insights: get_insights. Comments: manage_comments to list, "
            "reply, hide or delete — hide rather than delete unless told otherwise. Messenger: "
            "send_message only to someone who wrote to the Page, and only in reply."
        ),
    },
    {
        "platform": "instagram", "label": "Instagram",
        "goal": "Publish to and look after the company's Instagram account.",
        "guidance": (
            "publish_media takes public media URLs (images, Reels, stories, carousels of 2-10 items); "
            "a Reel is published only once Instagram has encoded it, which can take a minute. "
            "Insights: get_insights. Comments: manage_comments. discover_hashtags looks up hashtags; "
            "Instagram limits how many distinct hashtags an account may look up in a week, so look up "
            "few."
        ),
    },
    {
        "platform": "google_ads", "label": "Google Ads",
        "goal": "Report on and manage the company's Google Ads account.",
        "guidance": (
            "report runs a GAQL query — start there. create_campaign creates the budget and the "
            "campaign together and always PAUSED; amounts are in micros (1,000,000 = one unit of "
            "the account's currency). Never enable spend; say what to enable and leave it to a person. "
            "manage_keywords adds, pauses or removes keywords; get_ad_groups lists ad groups."
        ),
    },
    {
        "platform": "youtube", "label": "YouTube",
        "goal": "Publish to and look after the company's YouTube channel.",
        "guidance": (
            "upload_video takes a public video URL (up to 256 MB) and uploads it; privacy_status "
            "defaults to private — keep it private unless told to publish. manage_playlists, "
            "get_analytics and manage_comments as described."
        ),
    },
    {
        "platform": "tiktok", "label": "TikTok",
        "goal": "Publish to and monitor the company's TikTok account.",
        "guidance": (
            "publish_video pulls a video from a URL whose domain is verified with TikTok, then waits "
            "for TikTok to publish it; report 'not published yet' as it is. get_videos, "
            "get_analytics and manage_comments as described."
        ),
    },
    {
        "platform": "reddit", "label": "Reddit",
        "goal": "Take part in Reddit communities for the company.",
        "guidance": (
            "Read a subreddit's rules before posting there; many forbid promotion. create_post needs "
            "subreddit and title. search finds posts; manage_comments replies, deletes or votes; "
            "get_analytics reports karma and post stats."
        ),
    },
]


def payload(p: Dict[str, Any]) -> Dict[str, Any]:
    """The SKILL entity for one platform (``HierarchicalEntityCreate``)."""
    prompt = (
        f"You work the company's {p['label']} presence.\n\n"
        + _COMMON.format(platform=p["platform"], label=p["label"]) + "\n\n"
        + f"{p['label']}: " + p["guidance"]
    )
    return {
        "name": f"social-{p['platform'].replace('_', '-')}",
        "display_name": f"{p['label']} Skill",
        "description": f"Publishes, reports and answers on {p['label']} through social_api.",
        "goal": p["goal"],
        "type": "SKILL",
        "version": "1.0.0",
        "status": "ACTIVE",
        "tags": ["social", p["platform"], "first-party"],
        "identity": {"system_prompt": prompt},
        "capabilities": {"tools": [{"tool_id": "social_api"}]},
        "governance": {"max_cost_usd": 0.50, "timeout_ms": 300000},
        "io_contract": {
            "input_schema": {"type": "object", "properties": {"input": {
                "type": "string", "description": f"What to do on {p['label']}"}}, "required": ["input"]},
            "output_schema": {"type": "object", "properties": {"result": {
                "type": "string", "description": "What was done, with ids and links"}}},
        },
    }


SKILLS: List[Dict[str, Any]] = [payload(p) for p in PLATFORMS]
