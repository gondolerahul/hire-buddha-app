"""
Pinterest AI Agent Tools.

Provides tools for Pinterest content management via Pinterest API v5:
- PinterestCreatePinTool: Create image/video pins
- PinterestManageBoardsTool: Create/update/delete boards and sections
- PinterestGetAnalyticsTool: Pin and account analytics
- PinterestSearchPinsTool: Search public pins
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

PINTEREST_API_BASE = "https://api.pinterest.com/v5"


class PinterestCreatePinTool(SocialMediaTool):
    """Create image or video pins on Pinterest."""

    name = "pinterest_create_pin"
    platform = "pinterest"
    description = (
        "Create a pin on Pinterest with title, description, image/video, "
        "destination link, and board assignment."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "string", "description": "Board ID to pin to (required)"},
                    "title": {"type": "string", "description": "Pin title"},
                    "description": {"type": "string", "description": "Pin description"},
                    "link": {"type": "string", "description": "Destination URL when pin is clicked"},
                    "media_source_url": {"type": "string", "description": "URL of the image or video"},
                    "alt_text": {"type": "string", "description": "Alt text for accessibility"},
                    "board_section_id": {"type": "string", "description": "Optional board section ID"},
                    "account_name": {"type": "string", "description": "Optional: specific Pinterest account"},
                },
                "required": ["board_id", "media_source_url"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)

        body = {
            "board_id": params["board_id"],
            "media_source": {"source_type": "image_url", "url": params["media_source_url"]},
        }
        if params.get("title"):
            body["title"] = params["title"]
        if params.get("description"):
            body["description"] = params["description"]
        if params.get("link"):
            body["link"] = params["link"]
        if params.get("alt_text"):
            body["alt_text"] = params["alt_text"]
        if params.get("board_section_id"):
            body["board_section_id"] = params["board_section_id"]

        resp = await self._api_request(
            "POST", f"{PINTEREST_API_BASE}/pins", headers=headers, json_body=body,
        )
        data = resp.json()
        return {
            "success": True,
            "pin_id": data.get("id", ""),
            "board_id": params["board_id"],
            "message": "Pin created successfully on Pinterest",
        }


class PinterestManageBoardsTool(SocialMediaTool):
    """Create, update, and delete Pinterest boards and sections."""

    name = "pinterest_manage_boards"
    platform = "pinterest"
    description = (
        "Manage Pinterest boards. Actions: 'create', 'update', 'delete' boards, "
        "'list' all boards, 'create_section', 'list_sections'."
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
                        "enum": ["create", "update", "delete", "list", "create_section", "list_sections"],
                        "description": "Action to perform",
                    },
                    "board_id": {"type": "string", "description": "Board ID (for update/delete/sections)"},
                    "name": {"type": "string", "description": "Board name (for create/update)"},
                    "description": {"type": "string", "description": "Board description"},
                    "privacy": {
                        "type": "string",
                        "enum": ["PUBLIC", "PROTECTED", "SECRET"],
                        "description": "Board privacy (default: PUBLIC)",
                    },
                    "section_name": {"type": "string", "description": "Section name (for create_section)"},
                    "account_name": {"type": "string", "description": "Optional: specific Pinterest account"},
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
                "name": params.get("name", "Untitled Board"),
                "description": params.get("description", ""),
                "privacy": params.get("privacy", "PUBLIC"),
            }
            resp = await self._api_request(
                "POST", f"{PINTEREST_API_BASE}/boards", headers=headers, json_body=body,
            )
            return {"action": "create", "success": True, "board": resp.json()}

        elif action == "update":
            board_id = params.get("board_id", "")
            body = {}
            if params.get("name"):
                body["name"] = params["name"]
            if params.get("description"):
                body["description"] = params["description"]
            resp = await self._api_request(
                "PATCH", f"{PINTEREST_API_BASE}/boards/{board_id}", headers=headers, json_body=body,
            )
            return {"action": "update", "success": True, "board": resp.json()}

        elif action == "delete":
            board_id = params.get("board_id", "")
            await self._api_request("DELETE", f"{PINTEREST_API_BASE}/boards/{board_id}", headers=headers)
            return {"action": "delete", "success": True, "board_id": board_id}

        elif action == "list":
            resp = await self._api_request("GET", f"{PINTEREST_API_BASE}/boards", headers=headers)
            return {"action": "list", "boards": resp.json().get("items", [])}

        elif action == "create_section":
            board_id = params.get("board_id", "")
            body = {"name": params.get("section_name", "New Section")}
            resp = await self._api_request(
                "POST", f"{PINTEREST_API_BASE}/boards/{board_id}/sections",
                headers=headers, json_body=body,
            )
            return {"action": "create_section", "success": True, "section": resp.json()}

        elif action == "list_sections":
            board_id = params.get("board_id", "")
            resp = await self._api_request(
                "GET", f"{PINTEREST_API_BASE}/boards/{board_id}/sections", headers=headers,
            )
            return {"action": "list_sections", "sections": resp.json().get("items", [])}

        return {"error": f"Unknown action: {action}"}


class PinterestGetAnalyticsTool(SocialMediaTool):
    """Get Pinterest pin and account-level analytics."""

    name = "pinterest_get_analytics"
    platform = "pinterest"
    description = (
        "Get analytics for Pinterest pins or account. Returns impressions, "
        "saves, clicks, and engagement metrics."
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
                        "enum": ["account", "pin"],
                        "description": "Type of analytics",
                    },
                    "pin_id": {"type": "string", "description": "Pin ID (for 'pin' analytics)"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "metric_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics: IMPRESSION, SAVE, PIN_CLICK, OUTBOUND_CLICK, etc.",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific Pinterest account"},
                },
                "required": ["analytics_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        analytics_type = params.get("analytics_type", "account")

        metric_types = params.get("metric_types", ["IMPRESSION", "SAVE", "PIN_CLICK", "OUTBOUND_CLICK"])
        start_date = params.get("start_date", "2024-01-01")
        end_date = params.get("end_date", "2024-12-31")

        if analytics_type == "account":
            resp = await self._api_request(
                "GET", f"{PINTEREST_API_BASE}/user_account/analytics",
                headers=headers,
                params={
                    "start_date": start_date,
                    "end_date": end_date,
                    "metric_types": ",".join(metric_types),
                },
            )
            return {"analytics_type": "account", "data": resp.json()}

        elif analytics_type == "pin":
            pin_id = params.get("pin_id", "")
            if not pin_id:
                return {"error": "pin_id required for pin analytics"}
            resp = await self._api_request(
                "GET", f"{PINTEREST_API_BASE}/pins/{pin_id}/analytics",
                headers=headers,
                params={
                    "start_date": start_date,
                    "end_date": end_date,
                    "metric_types": ",".join(metric_types),
                },
            )
            return {"analytics_type": "pin", "pin_id": pin_id, "data": resp.json()}

        return {"error": f"Unknown analytics_type: {analytics_type}"}


class PinterestSearchPinsTool(SocialMediaTool):
    """Search public pins on Pinterest."""

    name = "pinterest_search_pins"
    platform = "pinterest"
    description = (
        "Search public pins on Pinterest by keyword for content inspiration. "
        "Returns pin titles, images, links, and engagement data."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default: 25)"},
                    "bookmark": {"type": "string", "description": "Pagination bookmark from previous search"},
                    "account_name": {"type": "string", "description": "Optional: specific Pinterest account"},
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
            "page_size": str(params.get("limit", 25)),
        }
        bookmark = params.get("bookmark")
        if bookmark:
            query_params["bookmark"] = bookmark

        resp = await self._api_request(
            "GET", f"{PINTEREST_API_BASE}/search/pins",
            headers=headers, params=query_params,
        )

        data = resp.json()
        return {
            "query": params["query"],
            "pins": data.get("items", []),
            "bookmark": data.get("bookmark"),
            "total": len(data.get("items", [])),
        }
