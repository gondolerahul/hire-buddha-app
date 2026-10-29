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
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com/rest"
NO_PAGE = "This LinkedIn connection names no Page: reconnect LinkedIn and choose the Page HireBuddha acts for."



def _linkedin_version() -> str:
    """The ``LinkedIn-Version`` header: the connector's setting, ``LINKEDIN_API_VERSION`` (TL-48, LI-E1)."""
    from src.connections.api_versions import linkedin_version
    return linkedin_version()


def _organization(credentials: Dict[str, Any]) -> Optional[str]:
    """The Page the connection acts as, ``urn:li:organization:<id>`` (LI-E4).

    ``linkedin_org`` is a Page connection: its token is a Page administrator's,
    and every post, comment reply and statistic is the Page's, never the member's.
    """
    meta = credentials.get("oauth_metadata") or {}
    urn = str(meta.get("organization_urn") or credentials.get("platform_user_id") or "")
    if urn.startswith("urn:li:organization:"):
        return urn
    page = credentials.get("platform_page_id")
    return f"urn:li:organization:{page}" if page else None


def _comment(element: Dict[str, Any]) -> Dict[str, Any]:
    """A comment with the least member data LinkedIn's terms allow to be shown
    (LI-E3, LI-E4): who (the member's URN, no profile fields), what and when."""
    created = element.get("created") or {}
    likes = element.get("likesSummary") or {}
    return {"comment_urn": element.get("$URN") or element.get("commentUrn") or element.get("id"),
            "author": element.get("actor"), "text": (element.get("message") or {}).get("text", ""),
            "created_at_ms": created.get("time"), "likes": likes.get("totalLikes")}


def _statistics_url(organization: str, posts: List[str]) -> str:
    """``organizationalEntityShareStatistics`` for the Page, or for some of its
    posts (Rest.li 2.0 lists: the URNs inside are encoded once, by hand)."""
    url = (f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics?q=organizationalEntity"
           f"&organizationalEntity={quote(organization, safe='')}")
    shares = [p for p in posts if p.startswith("urn:li:share:")]
    ugc = [p for p in posts if p.startswith("urn:li:ugcPost:")]
    if shares:
        url += "&shares=List(" + ",".join(quote(p, safe="") for p in shares) + ")"
    if ugc:
        url += "&ugcPosts=List(" + ",".join(quote(p, safe="") for p in ugc) + ")"
    return url


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
        author = _organization(credentials)   # always the Page (LI-E4)
        if not author:
            return {"error": NO_PAGE}

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
            "LinkedIn-Version": _linkedin_version(),
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
        org_urn = _organization(credentials)
        if not org_urn:
            return {"error": NO_PAGE}
        analytics_type = params.get("analytics_type", "page")

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": _linkedin_version(),
            "X-Restli-Protocol-Version": "2.0.0",
        })

        if analytics_type == "post":
            post_id = params.get("post_id", "")
            if not post_id:
                return {"error": "post_id is required for post analytics"}
            if not post_id.startswith(("urn:li:share:", "urn:li:ugcPost:")):
                return {"error": "post_id is the post's URN: urn:li:share:… or urn:li:ugcPost:…"}
            # One of the Page's posts: the share statistics filtered to it (LI-E4).
            resp = await self._api_request("GET", _statistics_url(org_urn, [post_id]), headers=headers)
            return {"analytics_type": "post", "post_id": post_id, "organization": org_urn,
                    "source": "LinkedIn", "data": resp.json()}

        # The Page's lifetime share statistics.
        resp = await self._api_request("GET", _statistics_url(org_urn, []), headers=headers)
        return {"analytics_type": "page", "organization": org_urn, "source": "LinkedIn", "data": resp.json()}


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
        org_urn = _organization(credentials)
        action = params["action"]
        post_id = params["post_id"]

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": _linkedin_version(),
            "X-Restli-Protocol-Version": "2.0.0",
        })

        if action == "list":
            resp = await self._api_request(
                "GET",
                f"{LINKEDIN_API_BASE}/socialActions/{quote(post_id, safe='')}/comments",
                headers=headers,
            )
            data = resp.json()
            comments = data.get("elements", [])
            # Members' activity: shown to this business only, kept 24 hours,
            # never saved to records or memory (LI-E2, LI-E3; the run is marked).
            return {
                "action": "list",
                "post_id": post_id,
                "comments": [_comment(c) for c in comments[:20]],  # Limit for LLM context
                "total": len(comments),
                "note": "Members' comments: use them in this run only; LinkedIn's terms forbid saving them.",
            }

        elif action == "create":
            comment_text = params.get("comment_text", "")
            if not comment_text:
                return {"error": "comment_text is required for 'create' action"}
            if not org_urn:
                return {"error": NO_PAGE}

            body = {
                "actor": org_urn,   # the Page replies, not the member who connected it
                "message": {"text": comment_text},
            }
            resp = await self._api_request(
                "POST",
                f"{LINKEDIN_API_BASE}/socialActions/{quote(post_id, safe='')}/comments",
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
                f"{LINKEDIN_API_BASE}/socialActions/{quote(post_id, safe='')}/comments/{quote(comment_id, safe='')}",
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
                        "description": "'organization': the connected Page (members' profiles are not read)",
                        "enum": ["organization", "user"]
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
        if params.get("profile_type", "organization") == "user":
            # A member's profile is member data the Page connection neither asks for nor keeps (LI-E3).
            return {"error": "HireBuddha reads the connected Page's profile only, not members' profiles"}
        org_urn = _organization(credentials)
        if not org_urn:
            return {"error": NO_PAGE}

        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": _linkedin_version(),
            "X-Restli-Protocol-Version": "2.0.0",
        })
        resp = await self._api_request(
            "GET",
            f"{LINKEDIN_API_BASE}/organizations/{org_urn.rsplit(':', 1)[-1]}",
            headers=headers,
        )
        return {"profile_type": "organization", "organization": resp.json()}
