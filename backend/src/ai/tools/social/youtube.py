"""
YouTube AI Agent Tools.

Provides tools for YouTube content management via the YouTube Data API v3:
- YouTubeUploadVideoTool: Upload videos with metadata
- YouTubeManagePlaylistsTool: Create/update/delete playlists and manage items
- YouTubeGetAnalyticsTool: Channel and video-level analytics
- YouTubeManageCommentsTool: List, reply, moderate comments
"""
import asyncio
import json
import logging
import mimetypes
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"
# Videos stream through in chunks, never whole in memory (YT-E4): every chunk but
# the last is a multiple of 256 KiB, as YouTube's resumable protocol requires.
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_MAX_VIDEO_BYTES = 128 * 1024 * 1024 * 1024        # YouTube takes up to 256 GB; a sane ceiling below it
_CHUNK_ATTEMPTS = 5
_MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
YOUTUBE_ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2"
YOUTUBE_REPORTING_BASE = "https://youtubereporting.googleapis.com/v1"
# The YouTube Analytics API's dimensions an agent may ask for (YT-E6).
ANALYTICS_DIMENSIONS = frozenset({
    "day", "month", "video", "insightTrafficSourceType", "insightTrafficSourceDetail", "insightPlaybackLocationType",
    "country", "province", "deviceType", "operatingSystem", "ageGroup", "gender", "subscribedStatus",
    "liveOrOnDemand", "youtubeProduct", "sharingService", "creatorContentType",
})
_REPORT_BYTES = 5 * 1024 * 1024
_REPORT_ROWS = 200
# YouTube's reasons, said plainly (YT-E4).
UPLOAD_ERRORS = {
    "quotaExceeded": "HireBuddha's YouTube allowance for today is used up; uploads work again after midnight Pacific time.",
    "uploadLimitExceeded": ("YouTube limits how many videos one channel may upload in a day, and this channel has "
                            "reached it; try again tomorrow."),
    "forbidden": "YouTube refused the upload for this channel (check the channel is in good standing and verified).",
}


class _Source:
    """The video's bytes as a stream, its size if known, and its type."""

    def __init__(self, stream: AsyncIterator[bytes], size: Optional[int], content_type: str) -> None:
        self.stream, self.size, self.content_type = stream, size, content_type


async def _url_stream(url: str) -> AsyncIterator[bytes]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk


async def _video_source(params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> _Source:
    """``video_key``: a file in the business's own storage; ``video_url``: a public URL (SSRF-guarded)."""
    if params.get("video_key"):
        from src.common.platform.storage import company_namespaces, get_storage, split_key

        key = str(params["video_key"])
        namespace, _ = split_key(key)
        if namespace not in company_namespaces((context or {}).get("company_id")):
            raise ValueError("video_key is not one of this business's files")
        storage = get_storage()
        size = await storage.size(key)
        if size is None:
            raise ValueError(f"no file is stored under {key}")
        return _Source(storage.open_stream(key), size, mimetypes.guess_type(key)[0] or "video/*")
    from src.common.net_guard import check_url

    url = str(params["video_url"])
    await check_url(url)
    size, content_type = None, ""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            head = await client.head(url)
        if head.status_code < 400:
            size = int(head.headers["content-length"]) if head.headers.get("content-length") else None
            content_type = head.headers.get("content-type", "").split(";")[0]
    except Exception:  # noqa: BLE001 - the size is learnt at the end instead
        logger.info("no HEAD answer for %s", url)
    return _Source(_url_stream(url), size, content_type or mimetypes.guess_type(url)[0] or "video/*")


async def _chunks(stream: AsyncIterator[bytes], size: int) -> AsyncIterator[Tuple[bytes, bool]]:
    """``(chunk, is_last)`` of ``size`` bytes each but the last."""
    buffer = bytearray()
    ready: Optional[bytes] = None
    async for piece in stream:
        buffer.extend(piece)
        while len(buffer) >= size:
            if ready is not None:
                yield ready, False
            ready = bytes(buffer[:size])
            del buffer[:size]
    if buffer:
        if ready is not None:
            yield ready, False
        yield bytes(buffer), True
    elif ready is not None:
        yield ready, True


def _reason(resp: httpx.Response) -> Optional[str]:
    try:
        errors = (resp.json().get("error") or {}).get("errors") or []
        return str(errors[0].get("reason")) if errors else None
    except (ValueError, AttributeError):
        return None


def _upload_error(resp: httpx.Response) -> str:
    reason = _reason(resp)
    return UPLOAD_ERRORS.get(reason or "", f"YouTube answered {resp.status_code}: {resp.text[:300]}")


def _acknowledged(resp: httpx.Response) -> int:
    """The bytes YouTube holds, from a 308's ``Range: bytes=0-N``."""
    value = resp.headers.get("range") or ""
    try:
        return int(value.rsplit("-", 1)[1]) + 1 if value else 0
    except (IndexError, ValueError):
        return 0


async def _send_chunks(session_url: str, token: str, source: _Source) -> Dict[str, Any]:
    """PUT the video chunk by chunk; a failed chunk asks YouTube what it holds and
    resumes from there (YT-E4). Returns the video resource."""
    offset = 0
    async with httpx.AsyncClient(timeout=600) as client:
        async for chunk, last in _chunks(source.stream, UPLOAD_CHUNK_BYTES):
            if offset + len(chunk) > _MAX_VIDEO_BYTES:
                raise RuntimeError(f"the video is larger than {_MAX_VIDEO_BYTES // 1024 ** 3} GB")
            total = str(source.size) if source.size is not None else (str(offset + len(chunk)) if last else "*")
            sent = 0                                  # of this chunk, confirmed by YouTube
            for attempt in range(_CHUNK_ATTEMPTS):
                part = chunk[sent:]
                start = offset + sent
                try:
                    resp = await client.put(session_url, content=part, headers={
                        "Authorization": f"Bearer {token}", "Content-Length": str(len(part)),
                        "Content-Range": f"bytes {start}-{start + len(part) - 1}/{total}"})
                except httpx.TransportError:
                    resp = None
                if resp is not None and resp.status_code in (200, 201):
                    return resp.json()
                if resp is not None and resp.status_code == 308:
                    held = _acknowledged(resp) - offset
                    if held >= len(chunk):
                        break
                    sent = max(held, 0)
                    continue
                if resp is not None and resp.status_code < 500 and resp.status_code != 429:
                    raise RuntimeError(_upload_error(resp))
                # A dropped connection or a 5xx: ask what arrived, then resume.
                await asyncio.sleep(min(2 ** attempt, 30))
                try:
                    status = await client.put(session_url, content=b"", headers={
                        "Authorization": f"Bearer {token}", "Content-Length": "0",
                        "Content-Range": f"bytes */{total}"})
                except httpx.TransportError:
                    continue
                if status.status_code in (200, 201):
                    return status.json()
                if status.status_code == 308:
                    sent = max(_acknowledged(status) - offset, 0)
                    if sent >= len(chunk):
                        break
            else:
                raise RuntimeError(f"the upload stopped at byte {offset + sent} after {_CHUNK_ATTEMPTS} attempts")
            offset += len(chunk)
    raise RuntimeError("YouTube did not confirm the upload after its last chunk")


class YouTubeUploadVideoTool(SocialMediaTool):
    """Upload videos to YouTube with title, description, tags, and category."""

    name = "youtube_upload_video"
    platform = "youtube"
    description = (
        "Upload a video to YouTube with title, description, tags, category, "
        "and privacy settings. The video streams in resumable chunks from the business's "
        "files (video_key) or a public URL (video_url), at any size YouTube takes."
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
                        "description": "Public URL of the video file (or give video_key)",
                    },
                    "video_key": {
                        "type": "string",
                        "description": "Storage key of a video in the business's own files (or give video_url)",
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
                "required": ["title", "made_for_kids", "contains_synthetic_media"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        if not params.get("video_url") and not params.get("video_key"):
            return {"error": "give video_key (a file in the business's storage) or video_url (a public URL)"}
        # YouTube's upload contract (YT-E2): the audience and the AI-content
        # disclosure are answered, never guessed by default.
        for answer in ("made_for_kids", "contains_synthetic_media"):
            if not isinstance(params.get(answer), bool):
                return {"error": f"{answer} must be true or false: YouTube requires it on every upload"}
        try:
            source = await _video_source(params, context)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"could not read the video: {exc}"}
        video_type = source.content_type if source.content_type.startswith("video/") else "video/*"
        if source.size is not None and source.size > _MAX_VIDEO_BYTES:
            return {"error": f"the video is larger than {_MAX_VIDEO_BYTES // 1024 ** 3} GB"}
        # One business may not use up the project's daily uploads (YT-E4).
        from src.ai.tools.social import quota
        from src.common.config import settings

        refused = await quota.draw("youtube_uploads", (context or {}).get("company_id"),
                                   total=settings.YOUTUBE_UPLOADS_PER_DAY,
                                   share=settings.YOUTUBE_UPLOADS_PER_BUSINESS_PER_DAY, what="YouTube uploads")
        if refused:
            return {"error": refused}

        # 1. Open a resumable session on the upload endpoint; 2. stream the bytes
        # to the session URL it returns, chunk by chunk, resuming after a failure.
        # Until P6.6 the tool sent only the metadata and reported success (TL-43).
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

        upload_headers = {"X-Upload-Content-Type": video_type}
        if source.size is not None:
            upload_headers["X-Upload-Content-Length"] = str(source.size)
        try:
            session = await self._api_request(
                "POST",
                f"{YOUTUBE_UPLOAD_BASE}/videos",
                headers=self._bearer_headers(access_token, upload_headers),
                json_body=body,
                params={"part": "snippet,status", "uploadType": "resumable"},
            )
        except httpx.HTTPStatusError as exc:
            return {"error": _upload_error(exc.response)}
        location = session.headers.get("Location")
        if not location:
            return {"error": "YouTube did not open an upload session (no Location header)"}
        try:
            uploaded = await _send_chunks(location, access_token, source)
        except Exception as exc:  # noqa: BLE001 - say where it stopped
            return {"error": f"the upload did not finish: {exc}"}
        video_id = uploaded.get("id", "")
        if not video_id:
            return {"error": "YouTube accepted the bytes but returned no video id"}

        result: Dict[str, Any] = {
            "success": True,
            "video_id": video_id,
            "title": params["title"],
            "privacy_status": status["privacyStatus"],
            # uploaded → processed (or failed/rejected): youtube_get_video_status says which.
            "upload_status": (uploaded.get("status") or {}).get("uploadStatus", "uploaded"),
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
                    "dimensions": {
                        "type": "string",
                        "description": "Optional, comma-separated: " + ", ".join(sorted(ANALYTICS_DIMENSIONS))
                                       + " (e.g. insightTrafficSourceType for views by traffic source)",
                    },
                    "filters": {
                        "type": "string",
                        "description": "Optional: dimension==value, ';' between (e.g. insightTrafficSourceType==ADVERTISING)",
                    },
                    "sort": {"type": "string", "description": "Optional: e.g. -views (most first)"},
                    "max_results": {"type": "integer", "description": "Optional: at most this many rows (≤ 200)"},
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

        query_params: Dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
        }
        # Answers by day, video, traffic source (ADVERTISING among them), country,
        # device … (YT-E6); YouTube's own names, checked before the call.
        dimensions = [d.strip() for d in str(params.get("dimensions") or "").split(",") if d.strip()]
        unknown = [d for d in dimensions if d not in ANALYTICS_DIMENSIONS]
        if unknown:
            return {"error": f"unknown dimensions {unknown}; use some of {sorted(ANALYTICS_DIMENSIONS)}"}
        filters = [f.strip() for f in str(params.get("filters") or "").split(";") if f.strip()]
        for item in filters:
            if "==" not in item or item.split("==", 1)[0] not in ANALYTICS_DIMENSIONS | {"video"}:
                return {"error": f"filter {item!r} is not dimension==value on a known dimension"}
        if analytics_type == "video":
            video_id = params.get("video_id", "")
            if not video_id:
                return {"error": "video_id is required for video analytics"}
            filters.insert(0, f"video=={video_id}")
        if dimensions:
            query_params["dimensions"] = ",".join(dimensions)
        if filters:
            query_params["filters"] = ";".join(filters)
        if params.get("sort"):
            query_params["sort"] = str(params["sort"])
        if params.get("max_results"):
            query_params["maxResults"] = max(1, min(int(params["max_results"]), 200))

        resp = await self._api_request(
            "GET", f"{YOUTUBE_ANALYTICS_BASE}/reports",
            headers=headers, params=query_params,
        )
        data = resp.json()
        columns = [c.get("name") for c in data.get("columnHeaders", [])]
        return {
            "analytics_type": analytics_type,
            "source": "YouTube Analytics",
            "rows": [dict(zip(columns, row)) for row in data.get("rows", []) or []],
            "metrics": metrics,
            "dimensions": dimensions,
            "date_range": {"start": start_date, "end": end_date},
            # YT-E6: YouTube's numbers are YouTube's; what is worked out from them is not.
            "note": "These numbers are YouTube's. A total, rate or comparison you work out from them is HireBuddha's, "
                    "and must be labelled so; never compare with other businesses' channels.",
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


class YouTubeGetVideoStatusTool(SocialMediaTool):
    """Where an uploaded video is: uploaded, processing, processed, failed or rejected (YT-E4)."""

    name = "youtube_get_video_status"
    platform = "youtube"
    description = ("Check an uploaded YouTube video's processing: its upload status, privacy, and how far "
                   "YouTube's processing has got (or why it failed or was rejected).")

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "The video's id, from the upload"},
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["video_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        resp = await self._api_request(
            "GET", f"{YOUTUBE_API_BASE}/videos", headers=self._bearer_headers(credentials["access_token"]),
            params={"part": "status,processingDetails", "id": params["video_id"]},
        )
        items = resp.json().get("items", [])
        if not items:
            return {"error": f"no video {params['video_id']} on this channel"}
        status = items[0].get("status") or {}
        processing = items[0].get("processingDetails") or {}
        return {"video_id": params["video_id"], "upload_status": status.get("uploadStatus"),
                "privacy_status": status.get("privacyStatus"), "publish_at": status.get("publishAt"),
                "failure_reason": status.get("failureReason"), "rejection_reason": status.get("rejectionReason"),
                "processing_status": processing.get("processingStatus"),
                "processing_progress": processing.get("processingProgress")}


class YouTubeManageReportsTool(SocialMediaTool):
    """The YouTube Reporting API: daily bulk reports for the channel (YT-E6)."""

    name = "youtube_manage_reports"
    platform = "youtube"
    description = (
        "YouTube's daily bulk reports for the channel (Reporting API). Actions: 'list' with what = "
        "report_types, jobs or reports (of a job_id); 'create' a job for a report_type_id (YouTube then "
        "makes that report every day); 'get' a report's rows from its download_url. Reports describe "
        "this channel only."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "create", "get"]},
                    "what": {"type": "string", "enum": ["report_types", "jobs", "reports"],
                             "description": "For 'list'"},
                    "job_id": {"type": "string", "description": "For listing a job's reports"},
                    "report_type_id": {"type": "string", "description": "For 'create', e.g. channel_basic_a2"},
                    "download_url": {"type": "string", "description": "For 'get': a report's downloadUrl"},
                    "account_name": {"type": "string", "description": "Optional: specific YouTube account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        token = credentials["access_token"]
        headers = self._bearer_headers(token)
        action = params.get("action")
        if action == "list":
            what = params.get("what") or "jobs"
            if what == "report_types":
                resp = await self._api_request("GET", f"{YOUTUBE_REPORTING_BASE}/reportTypes", headers=headers)
                return {"report_types": [{"id": t.get("id"), "name": t.get("name")}
                                         for t in resp.json().get("reportTypes", [])]}
            if what == "reports":
                if not params.get("job_id"):
                    return {"error": "job_id is required to list a job's reports"}
                resp = await self._api_request("GET", f"{YOUTUBE_REPORTING_BASE}/jobs/{params['job_id']}/reports",
                                               headers=headers)
                return {"reports": [{"id": r.get("id"), "start": r.get("startTime"), "end": r.get("endTime"),
                                     "download_url": r.get("downloadUrl")} for r in resp.json().get("reports", [])]}
            resp = await self._api_request("GET", f"{YOUTUBE_REPORTING_BASE}/jobs", headers=headers)
            return {"jobs": [{"id": j.get("id"), "report_type_id": j.get("reportTypeId"), "name": j.get("name")}
                             for j in resp.json().get("jobs", [])]}
        if action == "create":
            report_type = params.get("report_type_id")
            if not report_type:
                return {"error": "report_type_id is required (list report_types first)"}
            resp = await self._api_request("POST", f"{YOUTUBE_REPORTING_BASE}/jobs", headers=headers,
                                           json_body={"reportTypeId": report_type, "name": f"HireBuddha {report_type}"})
            job = resp.json()
            return {"success": True, "job_id": job.get("id"), "report_type_id": job.get("reportTypeId"),
                    "message": "YouTube makes the first report within about a day, then one every day."}
        if action == "get":
            url = str(params.get("download_url") or "")
            if not url.startswith("https://youtubereporting.googleapis.com/"):
                return {"error": "download_url is a report's downloadUrl from YouTube's Reporting API"}
            text = await self._report_text(url, token)
            lines = text.splitlines()
            header = lines[0].split(",") if lines else []
            rows = [dict(zip(header, line.split(","))) for line in lines[1:_REPORT_ROWS + 1]]
            return {"source": "YouTube Reporting API", "columns": header, "rows": rows,
                    "total_rows": max(len(lines) - 1, 0), "truncated": len(lines) - 1 > _REPORT_ROWS}
        return {"error": f"Unknown action: {action}"}

    @staticmethod
    async def _report_text(url: str, token: str) -> str:
        chunks: List[bytes] = []
        size = 0
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    chunks.append(chunk)
                    if size > _REPORT_BYTES:
                        break
        return b"".join(chunks).decode("utf-8", "replace")
