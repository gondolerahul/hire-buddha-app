"""
Facebook AI Agent Tools.

Provides tools for Facebook Page management via the Meta Graph API v22.0:
- FacebookCreatePostTool: Publish text/link/photo/video posts to Pages
- FacebookGetInsightsTool: Page and post-level insights
- FacebookManageCommentsTool: Retrieve/post/delete comments
- FacebookSendMessageTool: Send Messenger messages
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

FB_GRAPH_BASE = "https://graph.facebook.com/v22.0"
MESSAGING_WINDOW = timedelta(hours=24)


async def last_message_at(company_id: Any, sender_id: str) -> Optional[datetime]:
    """When the person last wrote to the business's Page (``social.message.received``
    events — ``social.message.with_person`` while a person had the conversation —
    Messenger's ``sender.id``), or ``None``."""
    if not company_id or not sender_id:
        return None
    import uuid

    from sqlalchemy import func, or_, select

    from src.automation.models import Event
    from src.common.tenancy.session import tenant_session

    try:
        company = uuid.UUID(str(company_id))
        async with tenant_session(company) as db:
            return (await db.execute(select(func.max(Event.received_at)).where(
                Event.company_id == company,
                Event.type.in_(("social.message.received", "social.message.with_person")),
                or_(Event.data["value"]["sender"]["id"].astext == sender_id,
                    Event.data["sender"]["id"].astext == sender_id)))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - unknown is treated as outside the window
        logger.warning("last Messenger message not readable", exc_info=True)
        return None


class FacebookCreatePostTool(SocialMediaTool):
    """Publish posts to a Facebook Page."""

    name = "facebook_create_post"
    platform = "facebook"
    description = (
        "Publish a post to a Facebook Page. Supports text posts, link shares (with preview), "
        "and photo posts. Requires a Facebook connection with pages_manage_posts permission."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Post text content"
                    },
                    "link": {
                        "type": "string",
                        "description": "Optional URL to share as a link post with preview card"
                    },
                    "photo_url": {
                        "type": "string",
                        "description": "Optional photo URL to publish as a photo post"
                    },
                    "published": {
                        "type": "boolean",
                        "description": "If false, creates an unpublished (dark) post. Default: true"
                    },
                    "scheduled_publish_time": {
                        "type": "integer",
                        "description": "Unix timestamp for scheduled publishing (must be 10min to 75 days in future)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Facebook account to use"
                    },
                },
                "required": ["message"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        page_id = credentials.get("platform_page_id", "me")

        post_data: Dict[str, Any] = {
            "message": params["message"],
            "access_token": access_token,
        }

        link = params.get("link")
        if link:
            post_data["link"] = link

        published = params.get("published", True)
        post_data["published"] = published

        scheduled_time = params.get("scheduled_publish_time")
        if scheduled_time:
            post_data["scheduled_publish_time"] = scheduled_time
            post_data["published"] = False

        # Photo post uses different endpoint
        photo_url = params.get("photo_url")
        if photo_url:
            post_data["url"] = photo_url
            endpoint = f"{FB_GRAPH_BASE}/{page_id}/photos"
        else:
            endpoint = f"{FB_GRAPH_BASE}/{page_id}/feed"

        resp = await self._api_request(
            "POST", endpoint, data=post_data,
        )
        data = resp.json()
        return {
            "success": True,
            "post_id": data.get("id") or data.get("post_id"),
            "page_id": page_id,
            "published": published,
            "message": "Post published to Facebook Page",
        }


class FacebookGetInsightsTool(SocialMediaTool):
    """Get insights for Facebook Page or individual posts."""

    name = "facebook_get_insights"
    platform = "facebook"
    description = (
        "Get analytics insights for a Facebook Page or specific posts. Returns metrics "
        "like reach, impressions, engagement, likes, page views, and video views."
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
                        "description": "Type: 'page' for page-level insights, 'post' for a specific post",
                        "enum": ["page", "post"]
                    },
                    "post_id": {
                        "type": "string",
                        "description": "Post ID (required if insights_type='post')"
                    },
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific metrics to fetch (e.g. page_impressions, page_engaged_users)"
                    },
                    "period": {
                        "type": "string",
                        "description": "Aggregation period: day, week, days_28 (default: day)",
                        "enum": ["day", "week", "days_28"]
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Facebook account to use"
                    },
                },
                "required": ["insights_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        page_id = credentials.get("platform_page_id", "me")
        insights_type = params.get("insights_type", "page")

        if insights_type == "post":
            post_id = params.get("post_id", "")
            if not post_id:
                return {"error": "post_id is required for post insights"}

            query_params = {
                "access_token": access_token,
                "metric": ",".join(params.get("metrics", [
                    "post_impressions", "post_engaged_users",
                    "post_reactions_by_type_total", "post_clicks",
                ])),
            }
            resp = await self._api_request(
                "GET", f"{FB_GRAPH_BASE}/{post_id}/insights",
                params=query_params,
            )
            return {"insights_type": "post", "post_id": post_id, "data": resp.json().get("data", [])}

        else:
            default_metrics = [
                "page_impressions", "page_engaged_users",
                "page_fans", "page_views_total",
            ]
            query_params = {
                "access_token": access_token,
                "metric": ",".join(params.get("metrics", default_metrics)),
                "period": params.get("period", "day"),
            }
            resp = await self._api_request(
                "GET", f"{FB_GRAPH_BASE}/{page_id}/insights",
                params=query_params,
            )
            return {"insights_type": "page", "page_id": page_id, "data": resp.json().get("data", [])}


class FacebookManageCommentsTool(SocialMediaTool):
    """Manage comments on Facebook Page posts."""

    name = "facebook_manage_comments"
    platform = "facebook"
    description = (
        "Manage comments on Facebook Page posts. Actions: 'list' to retrieve comments, "
        "'create' to post a reply, 'delete' to remove a comment, 'hide' to hide a comment."
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
                    "post_id": {
                        "type": "string",
                        "description": "Facebook post ID"
                    },
                    "comment_text": {
                        "type": "string",
                        "description": "Comment text (required for 'create' action)"
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "Comment ID (required for 'delete' and 'hide' actions)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Facebook account to use"
                    },
                },
                "required": ["action", "post_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        action = params["action"]
        post_id = params["post_id"]

        if action == "list":
            query_params = {
                "access_token": access_token,
                "fields": "id,message,from,created_time,like_count,comment_count",
                "limit": 25,
            }
            resp = await self._api_request(
                "GET", f"{FB_GRAPH_BASE}/{post_id}/comments",
                params=query_params,
            )
            data = resp.json()
            return {
                "action": "list",
                "post_id": post_id,
                "comments": data.get("data", []),
                "total": len(data.get("data", [])),
            }

        elif action == "create":
            comment_text = params.get("comment_text", "")
            if not comment_text:
                return {"error": "comment_text is required for 'create' action"}

            resp = await self._api_request(
                "POST", f"{FB_GRAPH_BASE}/{post_id}/comments",
                data={"message": comment_text, "access_token": access_token},
            )
            return {
                "action": "create",
                "success": True,
                "comment_id": resp.json().get("id"),
                "post_id": post_id,
            }

        elif action == "delete":
            comment_id = params.get("comment_id", "")
            if not comment_id:
                return {"error": "comment_id is required for 'delete' action"}

            await self._api_request(
                "DELETE", f"{FB_GRAPH_BASE}/{comment_id}",
                params={"access_token": access_token},
            )
            return {"action": "delete", "success": True, "comment_id": comment_id}

        elif action == "hide":
            comment_id = params.get("comment_id", "")
            if not comment_id:
                return {"error": "comment_id is required for 'hide' action"}

            await self._api_request(
                "POST", f"{FB_GRAPH_BASE}/{comment_id}",
                data={"is_hidden": True, "access_token": access_token},
            )
            return {"action": "hide", "success": True, "comment_id": comment_id}

        return {"error": f"Unknown action: {action}"}


class FacebookSendMessageTool(SocialMediaTool):
    """Send messages via Facebook Messenger as a Page."""

    name = "facebook_send_message"
    platform = "facebook"
    description = (
        "Send a message via Facebook Messenger as your Page. Supports text messages "
        "and structured messages (buttons, quick replies)."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_id": {
                        "type": "string",
                        "description": "Page-scoped user ID (PSID) of the message recipient"
                    },
                    "message_text": {
                        "type": "string",
                        "description": "Text message to send"
                    },
                    "quick_replies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of quick reply button labels"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Facebook account to use"
                    },
                },
                "required": ["recipient_id", "message_text"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        page_id = credentials.get("platform_page_id", "me")
        # Messenger's standard window (META-E4): an automated reply only within
        # 24 hours of the person's last message to the Page.
        last = await last_message_at((context or {}).get("company_id"), str(params["recipient_id"]))
        if last is None or datetime.utcnow() - last > MESSAGING_WINDOW:
            return {"error": "Messenger allows a reply only within 24 hours of the person's last message to the "
                             "Page, and theirs is older (or none was received). Wait for them to write again; a "
                             "person on the team may still answer from the Page's inbox."}
        # A person may have taken the conversation over; the assistant says it is
        # one first in a conversation, after a long gap, after a hand-back (META-E4).
        from src.messaging import rules

        company_id = (context or {}).get("company_id")
        recipient = str(params["recipient_id"])
        reply = await rules.before_reply(company_id, "messenger", str(page_id), recipient, params["message_text"])
        if reply.refusal:
            return {"error": reply.refusal}

        message_body: Dict[str, Any] = {
            "text": reply.text,
        }

        # Quick replies
        quick_replies = params.get("quick_replies")
        if quick_replies:
            message_body["quick_replies"] = [
                {"content_type": "text", "title": qr, "payload": qr}
                for qr in quick_replies[:13]  # Messenger limit is 13
            ]

        request_body = {
            "recipient": {"id": params["recipient_id"]},
            "message": message_body,
            "messaging_type": "RESPONSE",
        }

        resp = await self._api_request(
            "POST", f"{FB_GRAPH_BASE}/{page_id}/messages",
            headers=self._bearer_headers(access_token),
            json_body=request_body,
        )
        data = resp.json()
        await rules.replied(company_id, "messenger", str(page_id), recipient, disclosed=reply.disclosed)
        return {
            "success": True,
            "recipient_id": data.get("recipient_id"),
            "message_id": data.get("message_id"),
            "disclosed_ai": reply.disclosed,
        }
