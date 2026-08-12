"""
Instagram AI Agent Tools.

Provides tools for Instagram content management via the Instagram Graph API:
- InstagramPublishMediaTool: Publish images, carousels, Reels, Stories
- InstagramGetInsightsTool: Post and account-level insights
- InstagramManageCommentsTool: Retrieve/post/hide/delete comments
- InstagramDiscoverHashtagsTool: Hashtag search for content discovery
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

IG_GRAPH_BASE = "https://graph.facebook.com/v22.0"


class InstagramPublishMediaTool(SocialMediaTool):
    """Publish media to Instagram (images, carousels, Reels, Stories)."""

    name = "instagram_publish_media"
    platform = "instagram"
    description = (
        "Publish content to Instagram. Supports single image, carousel (up to 10 items), "
        "Reels (video), and Stories. Uses the two-step container → publish flow."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "media_type": {
                        "type": "string",
                        "description": "Type of media: image, carousel, reel, story",
                        "enum": ["image", "carousel", "reel", "story"]
                    },
                    "image_url": {
                        "type": "string",
                        "description": "Public URL of the image (required for image/story types)"
                    },
                    "video_url": {
                        "type": "string",
                        "description": "Public URL of the video (required for reel type)"
                    },
                    "caption": {
                        "type": "string",
                        "description": "Post caption (supports hashtags and mentions)"
                    },
                    "carousel_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "media_type": {"type": "string", "enum": ["IMAGE", "VIDEO"]},
                                "url": {"type": "string"}
                            }
                        },
                        "description": "Carousel items (2-10, required for carousel type)"
                    },
                    "location_id": {
                        "type": "string",
                        "description": "Optional Facebook Location Page ID for location tagging"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Instagram account to use"
                    },
                },
                "required": ["media_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ig_user_id = credentials.get("platform_user_id", "")

        if not ig_user_id:
            return {"error": "No platform_user_id configured for Instagram publishing"}

        media_type = params["media_type"]
        caption = params.get("caption", "")

        if media_type == "carousel":
            return await self._publish_carousel(ig_user_id, access_token, params, caption)
        else:
            return await self._publish_single(ig_user_id, access_token, media_type, params, caption)

    async def _publish_single(
        self, ig_user_id: str, access_token: str, media_type: str,
        params: Dict[str, Any], caption: str
    ) -> Dict[str, Any]:
        """Two-step: create container → publish."""
        container_data: Dict[str, Any] = {
            "access_token": access_token,
            "caption": caption,
        }

        if media_type == "image" or media_type == "story":
            container_data["image_url"] = params.get("image_url", "")
            if media_type == "story":
                container_data["media_type"] = "STORIES"
        elif media_type == "reel":
            container_data["media_type"] = "REELS"
            container_data["video_url"] = params.get("video_url", "")

        location_id = params.get("location_id")
        if location_id:
            container_data["location_id"] = location_id

        # Step 1: Create media container
        resp = await self._api_request(
            "POST", f"{IG_GRAPH_BASE}/{ig_user_id}/media",
            data=container_data,
        )
        container_id = resp.json().get("id")

        # Step 2: Publish the container
        publish_resp = await self._api_request(
            "POST", f"{IG_GRAPH_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        return {
            "success": True,
            "media_id": publish_resp.json().get("id"),
            "media_type": media_type,
            "message": f"Instagram {media_type} published successfully",
        }

    async def _publish_carousel(
        self, ig_user_id: str, access_token: str,
        params: Dict[str, Any], caption: str
    ) -> Dict[str, Any]:
        """Multi-step: create item containers → create carousel container → publish."""
        items = params.get("carousel_items", [])
        if len(items) < 2 or len(items) > 10:
            return {"error": "Carousel requires 2-10 items"}

        # Step 1: Create individual item containers
        item_ids = []
        for item in items:
            item_data: Dict[str, Any] = {
                "access_token": access_token,
                "is_carousel_item": True,
            }
            if item.get("media_type", "IMAGE") == "VIDEO":
                item_data["media_type"] = "VIDEO"
                item_data["video_url"] = item["url"]
            else:
                item_data["image_url"] = item["url"]

            resp = await self._api_request(
                "POST", f"{IG_GRAPH_BASE}/{ig_user_id}/media",
                data=item_data,
            )
            item_ids.append(resp.json().get("id"))

        # Step 2: Create carousel container
        carousel_data = {
            "access_token": access_token,
            "media_type": "CAROUSEL",
            "caption": caption,
            "children": ",".join(item_ids),
        }
        resp = await self._api_request(
            "POST", f"{IG_GRAPH_BASE}/{ig_user_id}/media",
            data=carousel_data,
        )
        carousel_id = resp.json().get("id")

        # Step 3: Publish
        publish_resp = await self._api_request(
            "POST", f"{IG_GRAPH_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": carousel_id, "access_token": access_token},
        )
        return {
            "success": True,
            "media_id": publish_resp.json().get("id"),
            "media_type": "carousel",
            "item_count": len(item_ids),
            "message": f"Instagram carousel with {len(item_ids)} items published",
        }


class InstagramGetInsightsTool(SocialMediaTool):
    """Get insights for Instagram account or individual posts."""

    name = "instagram_get_insights"
    platform = "instagram"
    description = (
        "Get analytics insights for an Instagram Business/Creator account or specific posts. "
        "Returns metrics like impressions, reach, engagement, saves, and video views."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "insights_type": {
                        "type": "string",
                        "description": "Type: 'account' for account-level, 'media' for a specific post",
                        "enum": ["account", "media"]
                    },
                    "media_id": {
                        "type": "string",
                        "description": "Instagram media ID (required if insights_type='media')"
                    },
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific metrics to fetch"
                    },
                    "period": {
                        "type": "string",
                        "description": "Period: day, week, days_28 (for account insights)",
                        "enum": ["day", "week", "days_28"]
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Instagram account to use"
                    },
                },
                "required": ["insights_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ig_user_id = credentials.get("platform_user_id", "")
        insights_type = params.get("insights_type", "account")

        if insights_type == "media":
            media_id = params.get("media_id", "")
            if not media_id:
                return {"error": "media_id is required for media insights"}

            default_metrics = ["impressions", "reach", "engagement", "saved"]
            query_params = {
                "access_token": access_token,
                "metric": ",".join(params.get("metrics", default_metrics)),
            }
            resp = await self._api_request(
                "GET", f"{IG_GRAPH_BASE}/{media_id}/insights",
                params=query_params,
            )
            return {"insights_type": "media", "media_id": media_id, "data": resp.json().get("data", [])}

        else:
            default_metrics = ["impressions", "reach", "profile_views", "website_clicks"]
            query_params = {
                "access_token": access_token,
                "metric": ",".join(params.get("metrics", default_metrics)),
                "period": params.get("period", "day"),
            }
            resp = await self._api_request(
                "GET", f"{IG_GRAPH_BASE}/{ig_user_id}/insights",
                params=query_params,
            )
            return {"insights_type": "account", "data": resp.json().get("data", [])}


class InstagramManageCommentsTool(SocialMediaTool):
    """Manage comments on Instagram posts."""

    name = "instagram_manage_comments"
    platform = "instagram"
    description = (
        "Manage comments on Instagram posts. Actions: 'list' to retrieve comments, "
        "'create' to reply, 'delete' to remove, 'hide' to hide a comment."
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
                        "description": "Action: list, create, delete, hide",
                        "enum": ["list", "create", "delete", "hide"]
                    },
                    "media_id": {
                        "type": "string",
                        "description": "Instagram media ID"
                    },
                    "comment_text": {
                        "type": "string",
                        "description": "Comment text (required for 'create')"
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "Comment ID (required for 'delete' and 'hide')"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Instagram account to use"
                    },
                },
                "required": ["action", "media_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        action = params["action"]
        media_id = params["media_id"]

        if action == "list":
            query_params = {
                "access_token": access_token,
                "fields": "id,text,username,timestamp,like_count,replies{id,text,username,timestamp}",
            }
            resp = await self._api_request(
                "GET", f"{IG_GRAPH_BASE}/{media_id}/comments",
                params=query_params,
            )
            data = resp.json()
            return {
                "action": "list",
                "media_id": media_id,
                "comments": data.get("data", []),
                "total": len(data.get("data", [])),
            }

        elif action == "create":
            comment_text = params.get("comment_text", "")
            if not comment_text:
                return {"error": "comment_text is required for 'create' action"}

            resp = await self._api_request(
                "POST", f"{IG_GRAPH_BASE}/{media_id}/comments",
                data={"message": comment_text, "access_token": access_token},
            )
            return {
                "action": "create",
                "success": True,
                "comment_id": resp.json().get("id"),
            }

        elif action == "delete":
            comment_id = params.get("comment_id", "")
            if not comment_id:
                return {"error": "comment_id is required"}

            await self._api_request(
                "DELETE", f"{IG_GRAPH_BASE}/{comment_id}",
                params={"access_token": access_token},
            )
            return {"action": "delete", "success": True, "comment_id": comment_id}

        elif action == "hide":
            comment_id = params.get("comment_id", "")
            if not comment_id:
                return {"error": "comment_id is required"}

            await self._api_request(
                "POST", f"{IG_GRAPH_BASE}/{comment_id}",
                data={"hide": True, "access_token": access_token},
            )
            return {"action": "hide", "success": True, "comment_id": comment_id}

        return {"error": f"Unknown action: {action}"}


class InstagramDiscoverHashtagsTool(SocialMediaTool):
    """Search and discover content via Instagram hashtags."""

    name = "instagram_discover_hashtags"
    platform = "instagram"
    description = (
        "Search Instagram hashtags and discover recent public posts. "
        "Limited to 30 unique hashtags per 7-day period per account."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "hashtag": {
                        "type": "string",
                        "description": "Hashtag to search (without # prefix)"
                    },
                    "result_type": {
                        "type": "string",
                        "description": "Result type: 'recent' or 'top'",
                        "enum": ["recent", "top"]
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Instagram account to use"
                    },
                },
                "required": ["hashtag"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ig_user_id = credentials.get("platform_user_id", "")
        hashtag = params["hashtag"].lstrip("#")
        result_type = params.get("result_type", "recent")

        # Step 1: Search for hashtag ID
        resp = await self._api_request(
            "GET", f"{IG_GRAPH_BASE}/ig_hashtag_search",
            params={"q": hashtag, "user_id": ig_user_id, "access_token": access_token},
        )
        hashtag_data = resp.json().get("data", [])
        if not hashtag_data:
            return {"error": f"Hashtag '#{hashtag}' not found"}

        hashtag_id = hashtag_data[0]["id"]

        # Step 2: Get recent or top media for hashtag
        edge = "recent_media" if result_type == "recent" else "top_media"
        resp = await self._api_request(
            "GET", f"{IG_GRAPH_BASE}/{hashtag_id}/{edge}",
            params={
                "user_id": ig_user_id,
                "access_token": access_token,
                "fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
            },
        )
        posts = resp.json().get("data", [])
        return {
            "hashtag": f"#{hashtag}",
            "result_type": result_type,
            "post_count": len(posts),
            "posts": posts[:25],  # Limit for LLM context
        }
