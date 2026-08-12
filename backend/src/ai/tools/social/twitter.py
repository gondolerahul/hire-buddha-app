"""
X (Twitter) AI Agent Tools.

Provides tools for Twitter/X content management via the X API v2:
- TwitterCreatePostTool: Create tweets and threads
- TwitterSearchTool: Search recent posts by keyword/hashtag
- TwitterGetMentionsTool: Monitor mentions timeline
- TwitterGetAnalyticsTool: Get public metrics for own tweets
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.x.com/2"


class TwitterCreatePostTool(SocialMediaTool):
    """Create tweets or threads on X (Twitter)."""

    name = "twitter_create_post"
    platform = "twitter"
    description = (
        "Create a tweet or thread on X (Twitter). Supports text posts (up to 280 characters), "
        "reply chains for threads, and quote tweets."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Tweet text content (max 280 characters for standard, 25000 for Premium)"
                    },
                    "reply_to_tweet_id": {
                        "type": "string",
                        "description": "Optional tweet ID to reply to (for threads)"
                    },
                    "quote_tweet_id": {
                        "type": "string",
                        "description": "Optional tweet ID to quote-retweet"
                    },
                    "poll_options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional poll options (2-4 choices, creates a poll)"
                    },
                    "poll_duration_minutes": {
                        "type": "integer",
                        "description": "Poll duration in minutes (5 to 10080, default: 1440 = 24h)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Twitter account to use"
                    },
                },
                "required": ["text"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        tweet_body: Dict[str, Any] = {"text": params["text"]}

        # Reply threading
        reply_to = params.get("reply_to_tweet_id")
        if reply_to:
            tweet_body["reply"] = {"in_reply_to_tweet_id": reply_to}

        # Quote tweet
        quote_id = params.get("quote_tweet_id")
        if quote_id:
            tweet_body["quote_tweet_id"] = quote_id

        # Poll
        poll_options = params.get("poll_options")
        if poll_options and len(poll_options) >= 2:
            duration = params.get("poll_duration_minutes", 1440)
            tweet_body["poll"] = {
                "options": [{"label": opt} for opt in poll_options[:4]],
                "duration_minutes": min(max(duration, 5), 10080),
            }

        resp = await self._api_request(
            "POST", f"{TWITTER_API_BASE}/tweets",
            headers=headers, json_body=tweet_body,
        )
        data = resp.json()
        tweet_data = data.get("data", {})
        return {
            "success": True,
            "tweet_id": tweet_data.get("id"),
            "text": tweet_data.get("text"),
            "message": "Tweet posted successfully",
        }


class TwitterSearchTool(SocialMediaTool):
    """Search recent tweets on X by keyword, hashtag, or user."""

    name = "twitter_search"
    platform = "twitter"
    description = (
        "Search recent tweets on X (Twitter) by keyword, hashtag, or advanced query operators. "
        "Returns up to 10 recent matching tweets with public metrics."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (supports X search operators like #hashtag, from:user, etc.)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (10-100, default: 10)"
                    },
                    "sort_order": {
                        "type": "string",
                        "description": "Sort order: recency or relevancy",
                        "enum": ["recency", "relevancy"]
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Twitter account to use"
                    },
                },
                "required": ["query"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        query_params = {
            "query": params["query"],
            "max_results": min(max(params.get("max_results", 10), 10), 100),
            "sort_order": params.get("sort_order", "recency"),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
            "expansions": "author_id",
            "user.fields": "name,username,verified",
        }

        resp = await self._api_request(
            "GET", f"{TWITTER_API_BASE}/tweets/search/recent",
            headers=headers, params=query_params,
        )
        data = resp.json()

        # Build user lookup map
        includes = data.get("includes", {})
        users_map = {u["id"]: u for u in includes.get("users", [])}

        tweets = []
        for tweet in data.get("data", []):
            author = users_map.get(tweet.get("author_id"), {})
            tweets.append({
                "id": tweet["id"],
                "text": tweet["text"],
                "created_at": tweet.get("created_at"),
                "author_name": author.get("name"),
                "author_username": author.get("username"),
                "metrics": tweet.get("public_metrics", {}),
            })

        return {
            "query": params["query"],
            "result_count": len(tweets),
            "tweets": tweets,
        }


class TwitterGetMentionsTool(SocialMediaTool):
    """Get recent mentions of the authenticated user on X."""

    name = "twitter_get_mentions"
    platform = "twitter"
    description = (
        "Get recent mentions of the authenticated Twitter/X user. "
        "Returns tweets that @mention the connected account."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Number of mentions to fetch (5-100, default: 10)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Twitter account to use"
                    },
                },
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        platform_user_id = credentials.get("platform_user_id", "")
        headers = self._bearer_headers(access_token)

        if not platform_user_id:
            return {"error": "No platform_user_id configured. Cannot fetch mentions."}

        query_params = {
            "max_results": min(max(params.get("max_results", 10), 5), 100),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "name,username",
        }

        resp = await self._api_request(
            "GET", f"{TWITTER_API_BASE}/users/{platform_user_id}/mentions",
            headers=headers, params=query_params,
        )
        data = resp.json()

        includes = data.get("includes", {})
        users_map = {u["id"]: u for u in includes.get("users", [])}

        mentions = []
        for tweet in data.get("data", []):
            author = users_map.get(tweet.get("author_id"), {})
            mentions.append({
                "id": tweet["id"],
                "text": tweet["text"],
                "created_at": tweet.get("created_at"),
                "author_name": author.get("name"),
                "author_username": author.get("username"),
                "metrics": tweet.get("public_metrics", {}),
            })

        return {"mention_count": len(mentions), "mentions": mentions}


class TwitterGetAnalyticsTool(SocialMediaTool):
    """Get public engagement metrics for own tweets on X."""

    name = "twitter_get_analytics"
    platform = "twitter"
    description = (
        "Get public engagement metrics for tweets posted by the authenticated account. "
        "Returns like count, retweet count, reply count, quote count, and impression count."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "tweet_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tweet IDs to get metrics for (max 100)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Twitter account to use"
                    },
                },
                "required": ["tweet_ids"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        tweet_ids = params.get("tweet_ids", [])
        if not tweet_ids:
            return {"error": "tweet_ids is required"}

        # Batch lookup (max 100 per request)
        ids_str = ",".join(tweet_ids[:100])
        query_params = {
            "ids": ids_str,
            "tweet.fields": "created_at,public_metrics,non_public_metrics,organic_metrics",
        }

        resp = await self._api_request(
            "GET", f"{TWITTER_API_BASE}/tweets",
            headers=headers, params=query_params,
        )
        data = resp.json()

        analytics = []
        for tweet in data.get("data", []):
            analytics.append({
                "tweet_id": tweet["id"],
                "text": tweet.get("text", "")[:100],
                "created_at": tweet.get("created_at"),
                "public_metrics": tweet.get("public_metrics", {}),
                "non_public_metrics": tweet.get("non_public_metrics", {}),
                "organic_metrics": tweet.get("organic_metrics", {}),
            })

        return {"tweet_count": len(analytics), "analytics": analytics}
