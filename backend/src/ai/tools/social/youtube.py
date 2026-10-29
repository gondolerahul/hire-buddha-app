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
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"
# What one call may upload (held in memory while it is sent).
_MAX_VIDEO_BYTES = 256 * 1024 * 1024
_MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
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
                    "made_for_kids": {
                        "type": "boolean",
                        "description": "Whether the video is made for children (YouTube requires the answer; "
                                       "ask the person when unsure)",
                    },
                    "contains_synthetic_media": {
                        "type": "boolean",
                        "description": "Whether the video has realistic AI-generated or altered content a viewer "
                                       "could mistake for real (YouTube requires disclosing it)",
                    },
                    "publish_at": {
                        "type": "string",
                        "description": "Optional: schedule publishing at this UTC time (ISO 8601); the video "
                                       "stays private until then",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["title", "video_url", "made_for_kids", "contains_synthetic_media"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        video_url = params.get("video_url")
        if not video_url:
            return {"error": "video_url is required: the public URL of the video file to upload"}
        # YouTube's upload contract (YT-E2): the audience and the AI-content
        # disclosure are answered, never guessed by default.
        for answer in ("made_for_kids", "contains_synthetic_media"):
            if not isinstance(params.get(answer), bool):
                return {"error": f"{answer} must be true or false: YouTube requires it on every upload"}
        try:
            video, video_type = await self._download(video_url, _MAX_VIDEO_BYTES)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"could not fetch the video: {exc}"}
        if not video_type.startswith("video/"):
            video_type = "video/*"

        # 1. Open a resumable session on the upload endpoint; 2. send the bytes
        # to the session URL it returns. Until P6.6 the tool sent only the
        # metadata, to the metadata endpoint, and reported success (TL-43).
        snippet = {
            "title": params["title"],
            "description": params.get("description", ""),
            "tags": params.get("tags", []),
            "categoryId": params.get("category_id", "22"),
        }
        status: Dict[str, Any] = {"privacyStatus": params.get("privacy_status", "private"),
                                  "selfDeclaredMadeForKids": params["made_for_kids"],
                                  "containsSyntheticMedia": params["contains_synthetic_media"]}
        if params.get("publish_at"):  # a scheduled video is private until YouTube publishes it
            status.update(privacyStatus="private", publishAt=params["publish_at"])

        body = {"snippet": snippet, "status": status}

        session = await self._api_request(
            "POST",
            f"{YOUTUBE_UPLOAD_BASE}/videos",
            headers=self._bearer_headers(access_token, {
                "X-Upload-Content-Length": str(len(video)), "X-Upload-Content-Type": video_type,
            }),
            json_body=body,
            params={"part": "snippet,status", "uploadType": "resumable"},
        )
        location = session.headers.get("Location")
        if not location:
            return {"error": "YouTube did not open an upload session (no Location header)"}
        uploaded = await self._api_request(
            "PUT", location, timeout=600, content=video,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": video_type},
        )
        video_id = uploaded.json().get("id", "")
        if not video_id:
            return {"error": "YouTube accepted the bytes but returned no video id"}

        result: Dict[str, Any] = {
            "success": True,
            "video_id": video_id,
            "title": params["title"],
            "privacy_status": status["privacyStatus"],
            "message": "Video uploaded to YouTube (processing may take a few minutes)",
        }
        if params.get("thumbnail_url"):
            try:
                image, image_type = await self._download(params["thumbnail_url"], _MAX_THUMBNAIL_BYTES)
                await self._api_request(
                    "POST", f"{YOUTUBE_UPLOAD_BASE}/thumbnails/set", params={"videoId": video_id},
                    content=image,
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": image_type},
                )
                result["thumbnail_set"] = True
            except Exception as exc:  # noqa: BLE001 - the video is up; say what did not work
                result["thumbnail_set"] = False
                result["thumbnail_error"] = str(exc)
        return result


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
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 28 days ago)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today, UTC)"},
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
        # The last 28 days by default, as YouTube Studio shows (it was always 2024).
        today = datetime.utcnow().date()
        start_date = params.get("start_date") or (today - timedelta(days=28)).isoformat()
        end_date = params.get("end_date") or today.isoformat()

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
            # comments.setModerationStatus is a POST with its arguments in the query (a PUT failed).
            # Other people's comments are removed this way (``rejected``), not with ``delete``.
            await self._api_request(
                "POST", f"{YOUTUBE_API_BASE}/comments/setModerationStatus",
                headers=headers, params={"id": comment_id, "moderationStatus": status},
            )
            return {"action": "moderate", "success": True, "comment_id": comment_id, "status": status}

        return {"error": f"Unknown action: {action}"}
