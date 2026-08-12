"""
Reddit AI Agent Tools.

Provides tools for Reddit content management via the Reddit API:
- RedditCreatePostTool: Submit text/link/image posts to subreddits
- RedditSearchTool: Search posts across Reddit or within subreddits
- RedditManageCommentsTool: Reply, edit, delete comments
- RedditGetAnalyticsTool: Get karma, post scores, engagement metrics
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

REDDIT_API_BASE = "https://oauth.reddit.com"


class RedditCreatePostTool(SocialMediaTool):
    """Submit posts to Reddit subreddits."""

    name = "reddit_create_post"
    platform = "reddit"
    description = (
        "Create a post on Reddit. Supports text posts, link posts, and image/video posts. "
        "Requires a Reddit connection with 'submit' scope."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "subreddit": {"type": "string", "description": "Subreddit name (without r/ prefix)"},
                    "title": {"type": "string", "description": "Post title (required)"},
                    "post_type": {
                        "type": "string",
                        "enum": ["self", "link", "image"],
                        "description": "Type of post: 'self' (text), 'link' (URL), 'image'",
                    },
                    "text": {"type": "string", "description": "Post body text (for 'self' type)"},
                    "url": {"type": "string", "description": "URL to share (for 'link' type)"},
                    "flair_id": {"type": "string", "description": "Post flair ID (if required by subreddit)"},
                    "nsfw": {"type": "boolean", "description": "Mark as NSFW"},
                    "spoiler": {"type": "boolean", "description": "Mark as spoiler"},
                    "account_name": {"type": "string", "description": "Optional: specific Reddit account"},
                },
                "required": ["subreddit", "title"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        user_agent = credentials.get("oauth_metadata", {}).get("user_agent", "HireBuddha:v1.0")
        headers = self._bearer_headers(access_token, {"User-Agent": user_agent})

        post_type = params.get("post_type", "self")
        data = {
            "sr": params["subreddit"],
            "title": params["title"],
            "kind": post_type,
            "api_type": "json",
        }

        if post_type == "self":
            data["text"] = params.get("text", "")
        elif post_type == "link":
            data["url"] = params.get("url", "")

        if params.get("flair_id"):
            data["flair_id"] = params["flair_id"]
        if params.get("nsfw"):
            data["nsfw"] = True
        if params.get("spoiler"):
            data["spoiler"] = True

        resp = await self._api_request(
            "POST", f"{REDDIT_API_BASE}/api/submit",
            headers=headers, data=data,
        )

        result = resp.json()
        post_data = result.get("json", {}).get("data", {})
        return {
            "success": True,
            "post_id": post_data.get("id", ""),
            "post_url": post_data.get("url", ""),
            "subreddit": params["subreddit"],
            "message": f"Post created in r/{params['subreddit']}",
        }


class RedditSearchTool(SocialMediaTool):
    """Search posts across Reddit or within specific subreddits."""

    name = "reddit_search"
    platform = "reddit"
    description = (
        "Search posts on Reddit. Can search across all of Reddit or within a specific subreddit. "
        "Returns titles, scores, comment counts, and URLs."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "subreddit": {"type": "string", "description": "Optional: limit search to this subreddit"},
                    "sort": {
                        "type": "string",
                        "enum": ["relevance", "hot", "top", "new", "comments"],
                        "description": "Sort order (default: relevance)",
                    },
                    "time_filter": {
                        "type": "string",
                        "enum": ["hour", "day", "week", "month", "year", "all"],
                        "description": "Time filter (default: all)",
                    },
                    "limit": {"type": "integer", "description": "Max results (default: 25, max: 100)"},
                    "account_name": {"type": "string", "description": "Optional: specific Reddit account"},
                },
                "required": ["query"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        user_agent = credentials.get("oauth_metadata", {}).get("user_agent", "HireBuddha:v1.0")
        headers = self._bearer_headers(access_token, {"User-Agent": user_agent})

        subreddit = params.get("subreddit")
        base_url = f"{REDDIT_API_BASE}/r/{subreddit}/search" if subreddit else f"{REDDIT_API_BASE}/search"

        query_params = {
            "q": params["query"],
            "sort": params.get("sort", "relevance"),
            "t": params.get("time_filter", "all"),
            "limit": str(params.get("limit", 25)),
            "type": "link",
        }
        if subreddit:
            query_params["restrict_sr"] = "true"

        resp = await self._api_request("GET", base_url, headers=headers, params=query_params)

        data = resp.json()
        posts = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            posts.append({
                "title": post.get("title"),
                "subreddit": post.get("subreddit"),
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
                "url": post.get("url"),
                "permalink": f"https://reddit.com{post.get('permalink', '')}",
                "created_utc": post.get("created_utc"),
            })

        return {"query": params["query"], "results": posts, "total": len(posts)}


class RedditManageCommentsTool(SocialMediaTool):
    """Reply to posts/comments, edit, and delete own comments on Reddit."""

    name = "reddit_manage_comments"
    platform = "reddit"
    description = (
        "Manage comments on Reddit. Actions: 'reply' to a post or comment, "
        "'edit' an existing comment, 'delete' a comment."
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
                        "enum": ["reply", "edit", "delete"],
                        "description": "Action to perform",
                    },
                    "thing_id": {
                        "type": "string",
                        "description": "Reddit fullname (e.g. t3_abc for post, t1_def for comment)",
                    },
                    "text": {"type": "string", "description": "Comment text (for reply/edit)"},
                    "account_name": {"type": "string", "description": "Optional: specific Reddit account"},
                },
                "required": ["action", "thing_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        user_agent = credentials.get("oauth_metadata", {}).get("user_agent", "HireBuddha:v1.0")
        headers = self._bearer_headers(access_token, {"User-Agent": user_agent})
        action = params["action"]
        thing_id = params["thing_id"]

        if action == "reply":
            text = params.get("text", "")
            if not text:
                return {"error": "text is required for reply"}
            resp = await self._api_request(
                "POST", f"{REDDIT_API_BASE}/api/comment",
                headers=headers, data={"thing_id": thing_id, "text": text, "api_type": "json"},
            )
            data = resp.json()
            return {"action": "reply", "success": True, "data": data.get("json", {}).get("data", {})}

        elif action == "edit":
            text = params.get("text", "")
            if not text:
                return {"error": "text is required for edit"}
            resp = await self._api_request(
                "POST", f"{REDDIT_API_BASE}/api/editusertext",
                headers=headers, data={"thing_id": thing_id, "text": text, "api_type": "json"},
            )
            return {"action": "edit", "success": True}

        elif action == "delete":
            await self._api_request(
                "POST", f"{REDDIT_API_BASE}/api/del",
                headers=headers, data={"id": thing_id},
            )
            return {"action": "delete", "success": True, "thing_id": thing_id}

        return {"error": f"Unknown action: {action}"}


class RedditGetAnalyticsTool(SocialMediaTool):
    """Get karma, post scores, and engagement metrics from Reddit."""

    name = "reddit_get_analytics"
    platform = "reddit"
    description = (
        "Get analytics for a Reddit account. Returns karma breakdown, "
        "post scores, upvote ratios, and comment counts."
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
                        "enum": ["account", "post"],
                        "description": "Type: 'account' for user stats, 'post' for specific post stats",
                    },
                    "post_id": {"type": "string", "description": "Post fullname (t3_xxx) for post analytics"},
                    "account_name": {"type": "string", "description": "Optional: specific Reddit account"},
                },
                "required": ["analytics_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        user_agent = credentials.get("oauth_metadata", {}).get("user_agent", "HireBuddha:v1.0")
        headers = self._bearer_headers(access_token, {"User-Agent": user_agent})
        analytics_type = params.get("analytics_type", "account")

        if analytics_type == "account":
            resp = await self._api_request("GET", f"{REDDIT_API_BASE}/api/v1/me", headers=headers)
            data = resp.json()
            return {
                "analytics_type": "account",
                "username": data.get("name"),
                "link_karma": data.get("link_karma"),
                "comment_karma": data.get("comment_karma"),
                "total_karma": data.get("total_karma"),
                "created_utc": data.get("created_utc"),
                "has_verified_email": data.get("has_verified_email"),
            }

        elif analytics_type == "post":
            post_id = params.get("post_id", "")
            if not post_id:
                return {"error": "post_id required for post analytics"}
            resp = await self._api_request(
                "GET", f"{REDDIT_API_BASE}/api/info",
                headers=headers, params={"id": post_id},
            )
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            if children:
                post = children[0].get("data", {})
                return {
                    "analytics_type": "post",
                    "post_id": post_id,
                    "score": post.get("score"),
                    "upvote_ratio": post.get("upvote_ratio"),
                    "num_comments": post.get("num_comments"),
                    "num_crossposts": post.get("num_crossposts"),
                    "view_count": post.get("view_count"),
                }
            return {"error": "Post not found"}

        return {"error": f"Unknown analytics_type: {analytics_type}"}
