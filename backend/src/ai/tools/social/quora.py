"""
Quora AI Agent Tools.

Provides tools for Quora content management via limited APIs:
- QuoraSearchQuestionsTool: Search questions by topic/keyword
- QuoraPostAnswerTool: Draft and post answers
- QuoraGetSpacesTool: Manage Quora Spaces
- QuoraGetAnalyticsTool: View counts, upvotes, shares
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

QUORA_API_BASE = "https://api.quora.com/v1"


class QuoraSearchQuestionsTool(SocialMediaTool):
    """Search questions on Quora by topic or keyword."""

    name = "quora_search_questions"
    platform = "quora"
    description = (
        "Search Quora questions by topic or keyword for content ideation and discovery. "
        "Returns question titles, follower counts, and answer counts."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or topic"},
                    "limit": {"type": "integer", "description": "Max results (default: 20)"},
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "recent", "popular"],
                        "description": "Sort order (default: relevance)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific Quora account"},
                },
                "required": ["query"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = credentials.get("access_token") or credentials.get("oauth_metadata", {}).get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        query_params = {
            "q": params["query"],
            "limit": str(params.get("limit", 20)),
            "sort": params.get("sort_by", "relevance"),
        }

        resp = await self._api_request(
            "GET", f"{QUORA_API_BASE}/search/questions",
            headers=headers, params=query_params,
        )

        data = resp.json()
        return {
            "query": params["query"],
            "questions": data.get("questions", []),
            "total": data.get("total", 0),
        }


class QuoraPostAnswerTool(SocialMediaTool):
    """Post answers to questions on Quora."""

    name = "quora_post_answer"
    platform = "quora"
    description = (
        "Draft and post an answer to a specific Quora question. "
        "Requires Quora API access with write permissions."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string", "description": "Quora question ID to answer"},
                    "answer_text": {"type": "string", "description": "Answer content (supports markdown)"},
                    "is_anonymous": {"type": "boolean", "description": "Post anonymously (default: false)"},
                    "account_name": {"type": "string", "description": "Optional: specific Quora account"},
                },
                "required": ["question_id", "answer_text"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = credentials.get("access_token") or credentials.get("oauth_metadata", {}).get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        body = {
            "question_id": params["question_id"],
            "content": params["answer_text"],
            "is_anonymous": params.get("is_anonymous", False),
        }

        resp = await self._api_request(
            "POST", f"{QUORA_API_BASE}/answers",
            headers=headers, json_body=body,
        )

        data = resp.json()
        return {
            "success": True,
            "answer_id": data.get("id", ""),
            "question_id": params["question_id"],
            "message": "Answer posted successfully on Quora",
        }


class QuoraGetSpacesTool(SocialMediaTool):
    """List and manage Quora Spaces for content distribution."""

    name = "quora_get_spaces"
    platform = "quora"
    description = (
        "List and manage Quora Spaces. Actions: 'list' to get your Spaces, "
        "'get' to retrieve Space details, 'post' to publish content to a Space."
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
                        "enum": ["list", "get", "post"],
                        "description": "Action to perform",
                    },
                    "space_id": {"type": "string", "description": "Space ID (for 'get' or 'post')"},
                    "content": {"type": "string", "description": "Content to post to the Space"},
                    "title": {"type": "string", "description": "Title for Space post"},
                    "account_name": {"type": "string", "description": "Optional: specific Quora account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = credentials.get("access_token") or credentials.get("oauth_metadata", {}).get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        action = params["action"]

        if action == "list":
            resp = await self._api_request("GET", f"{QUORA_API_BASE}/spaces", headers=headers)
            return {"action": "list", "spaces": resp.json().get("spaces", [])}

        elif action == "get":
            space_id = params.get("space_id", "")
            if not space_id:
                return {"error": "space_id required"}
            resp = await self._api_request("GET", f"{QUORA_API_BASE}/spaces/{space_id}", headers=headers)
            return {"action": "get", "space": resp.json()}

        elif action == "post":
            space_id = params.get("space_id", "")
            body = {
                "space_id": space_id,
                "title": params.get("title", ""),
                "content": params.get("content", ""),
            }
            resp = await self._api_request(
                "POST", f"{QUORA_API_BASE}/spaces/{space_id}/posts",
                headers=headers, json_body=body,
            )
            return {"action": "post", "success": True, "data": resp.json()}

        return {"error": f"Unknown action: {action}"}


class QuoraGetAnalyticsTool(SocialMediaTool):
    """Get analytics for Quora answers and Spaces."""

    name = "quora_get_analytics"
    platform = "quora"
    description = (
        "Get analytics for Quora content. Returns view counts, upvotes, "
        "shares, and engagement metrics for answers and Spaces."
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
                        "enum": ["profile", "answer", "space"],
                        "description": "Type of analytics to fetch",
                    },
                    "answer_id": {"type": "string", "description": "Answer ID (for 'answer' type)"},
                    "space_id": {"type": "string", "description": "Space ID (for 'space' type)"},
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "week", "month", "all"],
                        "description": "Time range (default: month)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific Quora account"},
                },
                "required": ["analytics_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = credentials.get("access_token") or credentials.get("oauth_metadata", {}).get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        analytics_type = params.get("analytics_type", "profile")
        time_range = params.get("time_range", "month")

        if analytics_type == "profile":
            resp = await self._api_request(
                "GET", f"{QUORA_API_BASE}/analytics/profile",
                headers=headers, params={"time_range": time_range},
            )
            return {"analytics_type": "profile", "data": resp.json()}

        elif analytics_type == "answer":
            answer_id = params.get("answer_id", "")
            if not answer_id:
                return {"error": "answer_id required for answer analytics"}
            resp = await self._api_request(
                "GET", f"{QUORA_API_BASE}/analytics/answers/{answer_id}",
                headers=headers, params={"time_range": time_range},
            )
            return {"analytics_type": "answer", "answer_id": answer_id, "data": resp.json()}

        elif analytics_type == "space":
            space_id = params.get("space_id", "")
            if not space_id:
                return {"error": "space_id required for space analytics"}
            resp = await self._api_request(
                "GET", f"{QUORA_API_BASE}/analytics/spaces/{space_id}",
                headers=headers, params={"time_range": time_range},
            )
            return {"analytics_type": "space", "space_id": space_id, "data": resp.json()}

        return {"error": f"Unknown analytics_type: {analytics_type}"}
