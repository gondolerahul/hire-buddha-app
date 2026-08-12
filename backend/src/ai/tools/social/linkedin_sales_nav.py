"""
LinkedIn Sales Navigator AI Agent Tools.

Provides advanced prospecting and lead management:
- LinkedInSalesSearchLeadsTool: Search for leads with advanced filters
- LinkedInSalesGetLeadTool: Get detailed lead profile information
- LinkedInSalesSaveLeadTool: Save leads to lists
- LinkedInSalesGetListsTool: Get and manage lead lists
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

SALES_NAV_API_BASE = "https://api.linkedin.com/rest/salesNavigator"


class LinkedInSalesSearchLeadsTool(SocialMediaTool):
    """Search for leads on LinkedIn Sales Navigator with advanced filters."""

    name = "linkedin_sales_search_leads"
    platform = "linkedin_sales_navigator"
    description = (
        "Search for leads on LinkedIn Sales Navigator with advanced filters such as "
        "title, company, industry, geography, seniority, and company size."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "Search keywords"},
                    "title": {"type": "string", "description": "Job title filter"},
                    "company": {"type": "string", "description": "Company name filter"},
                    "industry": {"type": "string", "description": "Industry filter"},
                    "geography": {"type": "string", "description": "Geography/location filter"},
                    "seniority_level": {
                        "type": "string",
                        "enum": ["ENTRY", "SENIOR", "MANAGER", "DIRECTOR", "VP", "CXO", "PARTNER", "OWNER"],
                        "description": "Seniority level filter",
                    },
                    "company_size": {
                        "type": "string",
                        "enum": ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"],
                        "description": "Company size filter",
                    },
                    "limit": {"type": "integer", "description": "Max results (default: 25)"},
                    "offset": {"type": "integer", "description": "Results offset for pagination"},
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": [],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        query_params = {
            "q": "search",
            "count": str(params.get("limit", 25)),
            "start": str(params.get("offset", 0)),
        }
        if params.get("keywords"):
            query_params["keywords"] = params["keywords"]
        if params.get("title"):
            query_params["titleFilter"] = params["title"]
        if params.get("company"):
            query_params["companyFilter"] = params["company"]
        if params.get("industry"):
            query_params["industryFilter"] = params["industry"]
        if params.get("geography"):
            query_params["geographyFilter"] = params["geography"]
        if params.get("seniority_level"):
            query_params["seniorityFilter"] = params["seniority_level"]

        resp = await self._api_request(
            "GET", f"{SALES_NAV_API_BASE}/leads",
            headers=headers, params=query_params,
        )
        data = resp.json()
        return {
            "leads": data.get("elements", []),
            "total": data.get("paging", {}).get("total", 0),
            "count": data.get("paging", {}).get("count", 0),
        }


class LinkedInSalesGetLeadTool(SocialMediaTool):
    """Get detailed lead profile information from Sales Navigator."""

    name = "linkedin_sales_get_lead"
    platform = "linkedin_sales_navigator"
    description = (
        "Get detailed profile information for a specific lead from LinkedIn Sales Navigator. "
        "Returns full profile, current position, and contact information."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string", "description": "Sales Navigator lead ID"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to retrieve (e.g. firstName, lastName, currentPositions)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": ["lead_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })
        lead_id = params["lead_id"]

        query_params = {}
        fields = params.get("fields")
        if fields:
            query_params["fields"] = ",".join(fields)

        resp = await self._api_request(
            "GET", f"{SALES_NAV_API_BASE}/leads/{lead_id}",
            headers=headers, params=query_params,
        )
        return {"lead": resp.json()}


class LinkedInSalesSaveLeadTool(SocialMediaTool):
    """Save leads to Sales Navigator lists."""

    name = "linkedin_sales_save_lead"
    platform = "linkedin_sales_navigator"
    description = (
        "Save a lead to a LinkedIn Sales Navigator list. "
        "Can add to existing lists or create new lists."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string", "description": "Lead ID to save"},
                    "list_id": {"type": "string", "description": "Target list ID"},
                    "notes": {"type": "string", "description": "Notes to attach to the saved lead"},
                    "tags": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Tags to apply to the lead",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": ["lead_id", "list_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        body = {
            "lead": f"urn:li:salesNavigatorLead:{params['lead_id']}",
            "list": f"urn:li:salesNavigatorList:{params['list_id']}",
        }
        if params.get("notes"):
            body["notes"] = params["notes"]
        if params.get("tags"):
            body["tags"] = params["tags"]

        resp = await self._api_request(
            "POST", f"{SALES_NAV_API_BASE}/savedLeads",
            headers=headers, json_body=body,
        )
        return {
            "success": True,
            "lead_id": params["lead_id"],
            "list_id": params["list_id"],
            "message": "Lead saved to list",
        }


class LinkedInSalesGetListsTool(SocialMediaTool):
    """Get and manage Sales Navigator lead lists."""

    name = "linkedin_sales_get_lists"
    platform = "linkedin_sales_navigator"
    description = (
        "Get and manage LinkedIn Sales Navigator lead lists. "
        "Actions: 'list' all lists, 'get' a specific list with leads, 'create' a new list."
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
                        "enum": ["list", "get", "create"],
                        "description": "Action to perform",
                    },
                    "list_id": {"type": "string", "description": "List ID (for 'get')"},
                    "name": {"type": "string", "description": "List name (for 'create')"},
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })
        action = params["action"]

        if action == "list":
            resp = await self._api_request(
                "GET", f"{SALES_NAV_API_BASE}/lists",
                headers=headers,
            )
            return {"action": "list", "lists": resp.json().get("elements", [])}

        elif action == "get":
            list_id = params.get("list_id", "")
            if not list_id:
                return {"error": "list_id required"}
            resp = await self._api_request(
                "GET", f"{SALES_NAV_API_BASE}/lists/{list_id}",
                headers=headers,
            )
            return {"action": "get", "list": resp.json()}

        elif action == "create":
            body = {"name": params.get("name", "New Lead List")}
            resp = await self._api_request(
                "POST", f"{SALES_NAV_API_BASE}/lists",
                headers=headers, json_body=body,
            )
            list_id = resp.headers.get("x-restli-id", "")
            return {"action": "create", "success": True, "list_id": list_id}

        return {"error": f"Unknown action: {action}"}
