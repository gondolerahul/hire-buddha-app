"""
LinkedIn AI Agent Tools.

Provides tools for LinkedIn content management via the LinkedIn API:
- LinkedInCreatePostTool: Create text/image/video/article posts
- LinkedInGetAnalyticsTool: Fetch post or page analytics
- LinkedInManageCommentsTool: Retrieve/post/delete comments
- LinkedInGetProfileTool: Fetch user profile or company page info
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com/rest"


class LinkedInCreatePostTool(SocialMediaTool):
    """Create posts on LinkedIn (text, image, video, article, document)."""

    name = "linkedin_create_post"
    platform = "linkedin"
    description = (
        "Create a post on LinkedIn. Supports text posts, link shares, image posts, "
        "and article posts. Requires a LinkedIn connection with w_member_social or "
        "w_organization_social scope."
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
                        "description": "Post text content (required)"
                    },
                    "visibility": {
                        "type": "string",
                        "description": "Post visibility: PUBLIC, CONNECTIONS, or LOGGED_IN (default: PUBLIC)",
                        "enum": ["PUBLIC", "CONNECTIONS", "LOGGED_IN"]
                    },
                    "link_url": {
                        "type": "string",
                        "description": "Optional URL to share as a link post with preview"
                    },
                    "image_url": {
                        "type": "string",
                        "description": "Optional image URL to attach to the post"
                    },
                    "post_as_organization": {
                        "type": "boolean",
                        "description": "If true, post as the connected company page instead of personal profile"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific LinkedIn account to use"
                    },
                },
                "required": ["text"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        platform_user_id = credentials.get("platform_user_id", "")
        platform_page_id = credentials.get("platform_page_id")

        # Determine author URN
        post_as_org = params.get("post_as_organization", False)
        if post_as_org and platform_page_id:
            author = f"urn:li:organization:{platform_page_id}"
        else:
            author = f"urn:li:person:{platform_user_id}"

        visibility = params.get("visibility", "PUBLIC")

        # Build post body per LinkedIn REST API
        post_body: Dict[str, Any] = {
            "author": author,
            "commentary": params["text"],
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
        }

        # Link attachment
        link_url = params.get("link_url")
        if link_url:
            post_body["content"] = {
                "article": {
                    "source": link_url,
                    "title": params.get("link_title", ""),
                    "description": params.get("link_description", ""),
                }
            }

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        resp = await self._api_request(
            "POST", f"{LINKEDIN_API_BASE}/posts", headers=headers, json_body=post_body
        )

        # LinkedIn returns 201 with x-restli-id header containing the post URN
        post_id = resp.headers.get("x-restli-id", "")
        return {
            "success": True,
            "post_id": post_id,
            "author": author,
            "visibility": visibility,
            "message": "Post created successfully on LinkedIn",
        }


class LinkedInGetAnalyticsTool(SocialMediaTool):
    """Fetch analytics for LinkedIn posts or company pages."""

    name = "linkedin_get_analytics"
    platform = "linkedin"
    description = (
        "Get analytics for LinkedIn posts or company pages. Returns metrics like "
        "impressions, clicks, reactions, comments, and shares."
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
                        "description": "Type of analytics: 'post' for individual post, 'page' for company page",
                        "enum": ["post", "page"]
                    },
                    "post_id": {
                        "type": "string",
                        "description": "LinkedIn post URN (required if analytics_type='post')"
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time range: 'day', 'week', 'month' (default: 'month')",
                        "enum": ["day", "week", "month"]
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific LinkedIn account to use"
                    },
                },
                "required": ["analytics_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        platform_page_id = credentials.get("platform_page_id")
        analytics_type = params.get("analytics_type", "page")

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        if analytics_type == "post":
            post_id = params.get("post_id", "")
            if not post_id:
                return {"error": "post_id is required for post analytics"}

            # Fetch post statistics
            query_params = {
                "q": "statistics",
                "posts[0]": post_id,
            }
            resp = await self._api_request(
                "GET", f"{LINKEDIN_API_BASE}/postStatistics",
                headers=headers,
                params=query_params,
            )
            return {"analytics_type": "post", "post_id": post_id, "data": resp.json()}

        else:
            # Page/organization analytics
            if not platform_page_id:
                return {"error": "No platform_page_id configured for company page analytics"}

            org_urn = f"urn:li:organization:{platform_page_id}"
            query_params = {
                "q": "organizationalEntity",
                "organizationalEntity": org_urn,
            }
            resp = await self._api_request(
                "GET",
                f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics",
                headers=headers,
                params=query_params,
            )
            return {"analytics_type": "page", "organization": org_urn, "data": resp.json()}


class LinkedInManageCommentsTool(SocialMediaTool):
    """Manage comments on LinkedIn posts."""

    name = "linkedin_manage_comments"
    platform = "linkedin"
    description = (
        "Manage comments on LinkedIn posts. Actions: 'list' to retrieve comments, "
        "'create' to post a comment, 'delete' to remove a comment."
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
                        "description": "Action to perform: list, create, delete",
                        "enum": ["list", "create", "delete"]
                    },
                    "post_id": {
                        "type": "string",
                        "description": "LinkedIn post URN to manage comments on"
                    },
                    "comment_text": {
                        "type": "string",
                        "description": "Text of the comment (required for 'create' action)"
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "Comment URN to delete (required for 'delete' action)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific LinkedIn account to use"
                    },
                },
                "required": ["action", "post_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        platform_user_id = credentials.get("platform_user_id", "")
        action = params["action"]
        post_id = params["post_id"]

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        if action == "list":
            resp = await self._api_request(
                "GET",
                f"{LINKEDIN_API_BASE}/socialActions/{post_id}/comments",
                headers=headers,
            )
            data = resp.json()
            comments = data.get("elements", [])
            return {
                "action": "list",
                "post_id": post_id,
                "comments": comments[:20],  # Limit for LLM context
                "total": len(comments),
            }

        elif action == "create":
            comment_text = params.get("comment_text", "")
            if not comment_text:
                return {"error": "comment_text is required for 'create' action"}

            body = {
                "actor": f"urn:li:person:{platform_user_id}",
                "message": {"text": comment_text},
            }
            resp = await self._api_request(
                "POST",
                f"{LINKEDIN_API_BASE}/socialActions/{post_id}/comments",
                headers=headers,
                json_body=body,
            )
            return {
                "action": "create",
                "success": True,
                "post_id": post_id,
                "comment_text": comment_text,
            }

        elif action == "delete":
            comment_id = params.get("comment_id", "")
            if not comment_id:
                return {"error": "comment_id is required for 'delete' action"}

            await self._api_request(
                "DELETE",
                f"{LINKEDIN_API_BASE}/socialActions/{post_id}/comments/{comment_id}",
                headers=headers,
            )
            return {"action": "delete", "success": True, "comment_id": comment_id}

        return {"error": f"Unknown action: {action}"}


class LinkedInGetProfileTool(SocialMediaTool):
    """Fetch LinkedIn profile or company page information."""

    name = "linkedin_get_profile"
    platform = "linkedin"
    description = (
        "Fetch profile information from LinkedIn. Can retrieve the authenticated "
        "user's profile or a connected company page's details."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_type": {
                        "type": "string",
                        "description": "Type of profile: 'user' for personal, 'organization' for company page",
                        "enum": ["user", "organization"]
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific LinkedIn account to use"
                    },
                },
                "required": ["profile_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        profile_type = params.get("profile_type", "user")

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        if profile_type == "user":
            resp = await self._api_request(
                "GET", f"{LINKEDIN_API_BASE}/me", headers=headers
            )
            return {"profile_type": "user", "profile": resp.json()}
        else:
            platform_page_id = credentials.get("platform_page_id")
            if not platform_page_id:
                return {"error": "No platform_page_id configured for organization profile"}

            resp = await self._api_request(
                "GET",
                f"{LINKEDIN_API_BASE}/organizations/{platform_page_id}",
                headers=headers,
            )
            return {"profile_type": "organization", "organization": resp.json()}
