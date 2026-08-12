"""
TikTok AI Agent Tools.

Provides tools for TikTok content management via the TikTok Content Posting API v2:
- TikTokPublishVideoTool: Upload and publish videos
- TikTokGetVideosTool: List creator's published videos
- TikTokGetAnalyticsTool: Video and account performance metrics
- TikTokManageCommentsTool: List and reply to comments
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokPublishVideoTool(SocialMediaTool):
    """Upload and publish videos to TikTok."""

    name = "tiktok_publish_video"
    platform = "tiktok"
    description = (
        "Publish a video to TikTok. Supports direct upload and share URL methods. "
        "Requires a TikTok connection with video.upload scope."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "video_url": {"type": "string", "description": "URL or path to the video file"},
                    "title": {"type": "string", "description": "Video title/caption"},
                    "privacy_level": {
                        "type": "string",
                        "enum": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
                        "description": "Privacy setting (default: PUBLIC_TO_EVERYONE)",
                    },
                    "disable_comment": {"type": "boolean", "description": "Disable comments on the video"},
                    "disable_duet": {"type": "boolean", "description": "Disable duets"},
                    "disable_stitch": {"type": "boolean", "description": "Disable stitch"},
                    "account_name": {"type": "string", "description": "Optional: specific TikTok account"},
                },
                "required": ["video_url", "title"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        body = {
            "post_info": {
                "title": params["title"],
                "privacy_level": params.get("privacy_level", "PUBLIC_TO_EVERYONE"),
                "disable_comment": params.get("disable_comment", False),
                "disable_duet": params.get("disable_duet", False),
                "disable_stitch": params.get("disable_stitch", False),
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": params["video_url"],
            },
        }

        resp = await self._api_request(
            "POST", f"{TIKTOK_API_BASE}/post/publish/video/init/",
            headers=headers, json_body=body,
        )

        data = resp.json()
        return {
            "success": True,
            "publish_id": data.get("data", {}).get("publish_id", ""),
            "title": params["title"],
            "message": "Video publish initiated on TikTok",
        }


class TikTokGetVideosTool(SocialMediaTool):
    """List creator's published videos on TikTok."""

    name = "tiktok_get_videos"
    platform = "tiktok"
    description = (
        "List published videos for the connected TikTok account. "
        "Returns video IDs, titles, view counts, and creation times."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum number of videos to return (default: 20, max: 20)",
                    },
                    "cursor": {"type": "integer", "description": "Cursor for pagination"},
                    "account_name": {"type": "string", "description": "Optional: specific TikTok account"},
                },
                "required": [],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        body = {"max_count": params.get("max_count", 20)}
        cursor = params.get("cursor")
        if cursor is not None:
            body["cursor"] = cursor

        resp = await self._api_request(
            "POST", f"{TIKTOK_API_BASE}/video/list/",
            headers=headers, json_body=body,
        )

        data = resp.json()
        videos = data.get("data", {}).get("videos", [])
        return {
            "videos": videos[:20],
            "cursor": data.get("data", {}).get("cursor"),
            "has_more": data.get("data", {}).get("has_more", False),
            "total": len(videos),
        }


class TikTokGetAnalyticsTool(SocialMediaTool):
    """Get TikTok video and account performance metrics."""

    name = "tiktok_get_analytics"
    platform = "tiktok"
    description = (
        "Get performance analytics for a TikTok account or specific videos. "
        "Returns views, likes, comments, shares, and engagement rates."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "analytics_type": {
                        "type": "string",
                        "enum": ["account", "video"],
                        "description": "Type of analytics: 'account' or 'video'",
                    },
                    "video_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Video IDs for video-level analytics",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to fetch (e.g. view_count, like_count, share_count)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific TikTok account"},
                },
                "required": ["analytics_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        analytics_type = params.get("analytics_type", "account")

        if analytics_type == "account":
            resp = await self._api_request(
                "GET", f"{TIKTOK_API_BASE}/research/user/info/",
                headers=headers,
                params={"fields": ",".join(params.get("fields", ["display_name", "follower_count", "following_count", "likes_count", "video_count"]))},
            )
            return {"analytics_type": "account", "data": resp.json()}

        elif analytics_type == "video":
            video_ids = params.get("video_ids", [])
            if not video_ids:
                return {"error": "video_ids required for video analytics"}
            fields = params.get("fields", ["view_count", "like_count", "comment_count", "share_count"])
            body = {"filters": {"video_ids": video_ids}, "fields": fields}
            resp = await self._api_request(
                "POST", f"{TIKTOK_API_BASE}/video/query/",
                headers=headers, json_body=body,
            )
            return {"analytics_type": "video", "data": resp.json()}

        return {"error": f"Unknown analytics_type: {analytics_type}"}


class TikTokManageCommentsTool(SocialMediaTool):
    """List and reply to comments on TikTok videos."""

    name = "tiktok_manage_comments"
    platform = "tiktok"
    description = (
        "Manage comments on TikTok videos. Actions: 'list' to retrieve comments, "
        "'reply' to post a reply to a comment."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "reply"],
                        "description": "Action to perform",
                    },
                    "video_id": {"type": "string", "description": "Video ID to manage comments on"},
                    "comment_id": {"type": "string", "description": "Comment ID to reply to (for 'reply')"},
                    "text": {"type": "string", "description": "Reply text (for 'reply' action)"},
                    "max_count": {"type": "integer", "description": "Max comments to return (default: 20)"},
                    "cursor": {"type": "integer", "description": "Cursor for pagination"},
                    "account_name": {"type": "string", "description": "Optional: specific TikTok account"},
                },
                "required": ["action", "video_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        action = params["action"]
        video_id = params["video_id"]

        if action == "list":
            body = {"video_id": video_id, "max_count": params.get("max_count", 20)}
            cursor = params.get("cursor")
            if cursor is not None:
                body["cursor"] = cursor
            resp = await self._api_request(
                "POST", f"{TIKTOK_API_BASE}/comment/list/",
                headers=headers, json_body=body,
            )
            data = resp.json()
            return {
                "action": "list",
                "video_id": video_id,
                "comments": data.get("data", {}).get("comments", []),
                "has_more": data.get("data", {}).get("has_more", False),
            }

        elif action == "reply":
            comment_id = params.get("comment_id", "")
            text = params.get("text", "")
            if not comment_id or not text:
                return {"error": "comment_id and text are required for reply"}
            body = {"video_id": video_id, "comment_id": comment_id, "text": text}
            resp = await self._api_request(
                "POST", f"{TIKTOK_API_BASE}/comment/reply/",
                headers=headers, json_body=body,
            )
            return {"action": "reply", "success": True, "data": resp.json()}

        return {"error": f"Unknown action: {action}"}
