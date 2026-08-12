"""
YouTube AI Agent Tools.

Provides tools for YouTube content management via the YouTube Data API v3:
- YouTubeUploadVideoTool: Upload videos with metadata
- YouTubeManagePlaylistsTool: Create/update/delete playlists and manage items
- YouTubeGetAnalyticsTool: Channel and video-level analytics
- YouTubeManageCommentsTool: List, reply, moderate comments
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2"


class YouTubeUploadVideoTool(SocialMediaTool):
    """Upload videos to YouTube with title, description, tags, and category."""

    name = "youtube_upload_video"
    platform = "youtube"
    description = (
        "Upload a video to YouTube with title, description, tags, category, "
        "and privacy settings. Supports resumable uploads."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Video title (required)"},
                    "description": {"type": "string", "description": "Video description"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Video tags for discoverability",
                    },
                    "category_id": {
                        "type": "string",
                        "description": "YouTube category ID (e.g. '22' for People & Blogs)",
                    },
                    "privacy_status": {
                        "type": "string",
                        "enum": ["public", "private", "unlisted"],
                        "description": "Video privacy status (default: private)",
                    },
                    "video_url": {
                        "type": "string",
                        "description": "URL or path to the video file to upload",
                    },
                    "thumbnail_url": {
                        "type": "string",
                        "description": "URL or path to custom thumbnail image",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["title", "video_url"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        # Step 1: Initialize resumable upload
        snippet = {
            "title": params["title"],
            "description": params.get("description", ""),
            "tags": params.get("tags", []),
            "categoryId": params.get("category_id", "22"),
        }
        status = {"privacyStatus": params.get("privacy_status", "private")}

        body = {"snippet": snippet, "status": status}

        resp = await self._api_request(
            "POST",
            f"{YOUTUBE_API_BASE}/videos",
            headers=headers,
            json_body=body,
            params={"part": "snippet,status", "uploadType": "resumable"},
        )

        return {
            "success": True,
            "video_id": resp.json().get("id", ""),
            "title": params["title"],
            "privacy_status": status["privacyStatus"],
            "message": "Video upload initiated on YouTube",
        }


class YouTubeManagePlaylistsTool(SocialMediaTool):
    """Create, update, delete playlists and manage playlist items."""

    name = "youtube_manage_playlists"
    platform = "youtube"
    description = (
        "Manage YouTube playlists. Actions: 'create' a playlist, 'update' title/description, "
        "'delete' a playlist, 'add_video' to a playlist, 'remove_video' from a playlist."
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
                        "enum": ["create", "update", "delete", "add_video", "remove_video", "list"],
                        "description": "Action to perform",
                    },
                    "playlist_id": {"type": "string", "description": "Playlist ID (for update/delete/add/remove)"},
                    "title": {"type": "string", "description": "Playlist title (for create/update)"},
                    "description": {"type": "string", "description": "Playlist description"},
                    "privacy_status": {
                        "type": "string",
                        "enum": ["public", "private", "unlisted"],
                        "description": "Playlist privacy (default: private)",
                    },
                    "video_id": {"type": "string", "description": "Video ID to add/remove"},
                    "playlist_item_id": {"type": "string", "description": "Playlist item ID (for remove)"},
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        action = params["action"]

        if action == "create":
            body = {
                "snippet": {
                    "title": params.get("title", "Untitled Playlist"),
                    "description": params.get("description", ""),
                },
                "status": {"privacyStatus": params.get("privacy_status", "private")},
            }
            resp = await self._api_request(
                "POST", f"{YOUTUBE_API_BASE}/playlists",
                headers=headers, json_body=body, params={"part": "snippet,status"},
            )
            data = resp.json()
            return {"action": "create", "success": True, "playlist_id": data.get("id", "")}

        elif action == "update":
            playlist_id = params.get("playlist_id", "")
            if not playlist_id:
                return {"error": "playlist_id is required for update"}
            body = {
                "id": playlist_id,
                "snippet": {
                    "title": params.get("title", ""),
                    "description": params.get("description", ""),
                },
            }
            resp = await self._api_request(
                "PUT", f"{YOUTUBE_API_BASE}/playlists",
                headers=headers, json_body=body, params={"part": "snippet"},
            )
            return {"action": "update", "success": True, "playlist_id": playlist_id}

        elif action == "delete":
            playlist_id = params.get("playlist_id", "")
            await self._api_request(
                "DELETE", f"{YOUTUBE_API_BASE}/playlists",
                headers=headers, params={"id": playlist_id},
            )
            return {"action": "delete", "success": True, "playlist_id": playlist_id}

        elif action == "add_video":
            body = {
                "snippet": {
                    "playlistId": params.get("playlist_id", ""),
                    "resourceId": {"kind": "youtube#video", "videoId": params.get("video_id", "")},
                }
            }
            resp = await self._api_request(
                "POST", f"{YOUTUBE_API_BASE}/playlistItems",
                headers=headers, json_body=body, params={"part": "snippet"},
            )
            return {"action": "add_video", "success": True, "data": resp.json()}

        elif action == "remove_video":
            item_id = params.get("playlist_item_id", "")
            await self._api_request(
                "DELETE", f"{YOUTUBE_API_BASE}/playlistItems",
                headers=headers, params={"id": item_id},
            )
            return {"action": "remove_video", "success": True}

        elif action == "list":
            resp = await self._api_request(
                "GET", f"{YOUTUBE_API_BASE}/playlists",
                headers=headers, params={"part": "snippet,contentDetails", "mine": "true", "maxResults": "25"},
            )
            return {"action": "list", "playlists": resp.json().get("items", [])}

        return {"error": f"Unknown action: {action}"}


class YouTubeGetAnalyticsTool(SocialMediaTool):
    """Fetch YouTube channel and video-level analytics."""

    name = "youtube_get_analytics"
    platform = "youtube"
    description = (
        "Get analytics for a YouTube channel or video. Returns views, watch time, "
        "CTR, audience demographics, and engagement metrics."
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
                        "enum": ["channel", "video"],
                        "description": "Type of analytics to fetch",
                    },
                    "video_id": {"type": "string", "description": "Video ID (required if analytics_type='video')"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)"},
                    "metrics": {
                        "type": "string",
                        "description": "Comma-separated metrics (default: views,estimatedMinutesWatched,likes,subscribersGained)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["analytics_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        analytics_type = params.get("analytics_type", "channel")

        metrics = params.get("metrics", "views,estimatedMinutesWatched,likes,subscribersGained")
        start_date = params.get("start_date", "2024-01-01")
        end_date = params.get("end_date", "2024-12-31")

        query_params = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
        }

        if analytics_type == "video":
            video_id = params.get("video_id", "")
            if not video_id:
                return {"error": "video_id is required for video analytics"}
            query_params["filters"] = f"video=={video_id}"

        resp = await self._api_request(
            "GET", f"{YOUTUBE_ANALYTICS_BASE}/reports",
            headers=headers, params=query_params,
        )

        return {
            "analytics_type": analytics_type,
            "data": resp.json(),
            "metrics": metrics,
            "date_range": {"start": start_date, "end": end_date},
        }


class YouTubeManageCommentsTool(SocialMediaTool):
    """List, reply to, and moderate comments on YouTube videos."""

    name = "youtube_manage_comments"
    platform = "youtube"
    description = (
        "Manage comments on YouTube videos. Actions: 'list' to retrieve comments, "
        "'reply' to post a reply, 'delete' to remove a comment, "
        "'moderate' to hold or approve comments."
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
                        "enum": ["list", "reply", "delete", "moderate"],
                        "description": "Action to perform",
                    },
                    "video_id": {"type": "string", "description": "Video ID to manage comments on"},
                    "comment_id": {"type": "string", "description": "Comment ID (for reply/delete/moderate)"},
                    "text": {"type": "string", "description": "Reply text (for 'reply' action)"},
                    "moderation_status": {
                        "type": "string",
                        "enum": ["published", "heldForReview", "rejected"],
                        "description": "Moderation status (for 'moderate' action)",
                    },
                    "max_results": {"type": "integer", "description": "Max comments to return (default: 20)"},
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        action = params["action"]

        if action == "list":
            video_id = params.get("video_id", "")
            if not video_id:
                return {"error": "video_id is required for listing comments"}
            max_results = params.get("max_results", 20)
            resp = await self._api_request(
                "GET", f"{YOUTUBE_API_BASE}/commentThreads",
                headers=headers,
                params={"part": "snippet,replies", "videoId": video_id, "maxResults": str(max_results)},
            )
            data = resp.json()
            return {"action": "list", "video_id": video_id, "comments": data.get("items", [])}

        elif action == "reply":
            comment_id = params.get("comment_id", "")
            text = params.get("text", "")
            if not comment_id or not text:
                return {"error": "comment_id and text are required for reply"}
            body = {"snippet": {"parentId": comment_id, "textOriginal": text}}
            resp = await self._api_request(
                "POST", f"{YOUTUBE_API_BASE}/comments",
                headers=headers, json_body=body, params={"part": "snippet"},
            )
            return {"action": "reply", "success": True, "data": resp.json()}

        elif action == "delete":
            comment_id = params.get("comment_id", "")
            await self._api_request(
                "DELETE", f"{YOUTUBE_API_BASE}/comments",
                headers=headers, params={"id": comment_id},
            )
            return {"action": "delete", "success": True, "comment_id": comment_id}

        elif action == "moderate":
            comment_id = params.get("comment_id", "")
            status = params.get("moderation_status", "published")
            body = {"id": comment_id, "snippet": {"moderationStatus": status}}
            resp = await self._api_request(
                "PUT", f"{YOUTUBE_API_BASE}/comments/setModerationStatus",
                headers=headers, params={"id": comment_id, "moderationStatus": status},
            )
            return {"action": "moderate", "success": True, "comment_id": comment_id, "status": status}

        return {"error": f"Unknown action: {action}"}
