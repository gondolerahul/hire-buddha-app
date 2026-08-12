"""
Meta Ads AI Agent Tools.

Provides tools for Meta (Facebook/Instagram) advertising via Marketing API v22.0:
- MetaAdsCreateCampaignTool: Create campaigns with objectives
- MetaAdsManageAdsetsTool: Create/update ad sets with targeting
- MetaAdsReportTool: Fetch performance metrics with breakdowns
- MetaAdsManageAudiencesTool: Create/update Custom and Lookalike audiences
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

META_ADS_API_BASE = "https://graph.facebook.com/v22.0"


class MetaAdsCreateCampaignTool(SocialMediaTool):
    """Create Meta advertising campaigns."""

    name = "meta_ads_create_campaign"
    platform = "meta_ads"
    description = (
        "Create a Meta Ads campaign with objective (AWARENESS, TRAFFIC, CONVERSIONS, etc.). "
        "Requires a Meta connection with ads_management scope."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string", "description": "Ad account ID (act_xxxx)"},
                    "name": {"type": "string", "description": "Campaign name"},
                    "objective": {
                        "type": "string",
                        "enum": [
                            "OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT",
                            "OUTCOME_LEADS", "OUTCOME_APP_PROMOTION", "OUTCOME_SALES",
                        ],
                        "description": "Campaign objective",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["ACTIVE", "PAUSED"],
                        "description": "Campaign status (default: PAUSED)",
                    },
                    "special_ad_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Special ad categories (CREDIT, EMPLOYMENT, HOUSING, etc.)",
                    },
                    "daily_budget": {"type": "integer", "description": "Daily budget in cents"},
                    "lifetime_budget": {"type": "integer", "description": "Lifetime budget in cents"},
                    "account_name": {"type": "string", "description": "Optional: specific Meta account"},
                },
                "required": ["name", "objective"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        if not ad_account_id:
            return {"error": "ad_account_id is required"}

        headers = self._bearer_headers(access_token)
        body = {
            "name": params["name"],
            "objective": params["objective"],
            "status": params.get("status", "PAUSED"),
            "special_ad_categories": params.get("special_ad_categories", []),
        }
        if params.get("daily_budget"):
            body["daily_budget"] = params["daily_budget"]
        if params.get("lifetime_budget"):
            body["lifetime_budget"] = params["lifetime_budget"]

        resp = await self._api_request(
            "POST", f"{META_ADS_API_BASE}/act_{ad_account_id}/campaigns",
            headers=headers, json_body=body,
        )
        data = resp.json()
        return {
            "success": True,
            "campaign_id": data.get("id", ""),
            "name": params["name"],
            "objective": params["objective"],
            "message": "Campaign created on Meta Ads",
        }


class MetaAdsManageAdsetsTool(SocialMediaTool):
    """Create and update Meta ad sets with targeting, budget, and schedule."""

    name = "meta_ads_manage_adsets"
    platform = "meta_ads"
    description = (
        "Manage Meta Ads ad sets. Actions: 'create' a new ad set, "
        "'update' an existing ad set, 'list' ad sets in a campaign."
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
                        "enum": ["create", "update", "list"],
                        "description": "Action to perform",
                    },
                    "ad_account_id": {"type": "string", "description": "Ad account ID"},
                    "campaign_id": {"type": "string", "description": "Campaign ID"},
                    "adset_id": {"type": "string", "description": "Ad set ID (for update)"},
                    "name": {"type": "string", "description": "Ad set name"},
                    "daily_budget": {"type": "integer", "description": "Daily budget in cents"},
                    "lifetime_budget": {"type": "integer", "description": "Lifetime budget in cents"},
                    "bid_amount": {"type": "integer", "description": "Bid amount in cents"},
                    "billing_event": {
                        "type": "string",
                        "enum": ["IMPRESSIONS", "LINK_CLICKS", "APP_INSTALLS"],
                        "description": "Billing event",
                    },
                    "optimization_goal": {
                        "type": "string",
                        "enum": ["REACH", "IMPRESSIONS", "LINK_CLICKS", "LANDING_PAGE_VIEWS", "CONVERSIONS"],
                        "description": "Optimization goal",
                    },
                    "targeting": {
                        "type": "object",
                        "description": "Targeting spec (geo, demographics, interests)",
                    },
                    "start_time": {"type": "string", "description": "Start time ISO 8601"},
                    "end_time": {"type": "string", "description": "End time ISO 8601"},
                    "status": {"type": "string", "enum": ["ACTIVE", "PAUSED"], "description": "Status"},
                    "account_name": {"type": "string", "description": "Optional: specific Meta account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        headers = self._bearer_headers(access_token)
        action = params["action"]

        if action == "create":
            body = {
                "name": params.get("name", "Ad Set"),
                "campaign_id": params.get("campaign_id", ""),
                "status": params.get("status", "PAUSED"),
                "billing_event": params.get("billing_event", "IMPRESSIONS"),
                "optimization_goal": params.get("optimization_goal", "REACH"),
            }
            if params.get("daily_budget"):
                body["daily_budget"] = params["daily_budget"]
            if params.get("lifetime_budget"):
                body["lifetime_budget"] = params["lifetime_budget"]
            if params.get("targeting"):
                body["targeting"] = params["targeting"]
            if params.get("start_time"):
                body["start_time"] = params["start_time"]
            if params.get("end_time"):
                body["end_time"] = params["end_time"]
            if params.get("bid_amount"):
                body["bid_amount"] = params["bid_amount"]

            resp = await self._api_request(
                "POST", f"{META_ADS_API_BASE}/act_{ad_account_id}/adsets",
                headers=headers, json_body=body,
            )
            return {"action": "create", "success": True, "adset_id": resp.json().get("id", "")}

        elif action == "update":
            adset_id = params.get("adset_id", "")
            if not adset_id:
                return {"error": "adset_id required for update"}
            body = {}
            for key in ["name", "status", "daily_budget", "lifetime_budget", "targeting", "bid_amount"]:
                if params.get(key):
                    body[key] = params[key]
            resp = await self._api_request(
                "POST", f"{META_ADS_API_BASE}/{adset_id}",
                headers=headers, json_body=body,
            )
            return {"action": "update", "success": True, "adset_id": adset_id}

        elif action == "list":
            campaign_id = params.get("campaign_id", "")
            url = f"{META_ADS_API_BASE}/act_{ad_account_id}/adsets"
            if campaign_id:
                url = f"{META_ADS_API_BASE}/{campaign_id}/adsets"
            resp = await self._api_request(
                "GET", url, headers=headers,
                params={"fields": "name,status,daily_budget,targeting,optimization_goal"},
            )
            return {"action": "list", "adsets": resp.json().get("data", [])}

        return {"error": f"Unknown action: {action}"}


class MetaAdsReportTool(SocialMediaTool):
    """Fetch Meta Ads campaign performance metrics."""

    name = "meta_ads_report"
    platform = "meta_ads"
    description = (
        "Get performance reports for Meta Ads campaigns, ad sets, and ads. "
        "Returns metrics like impressions, clicks, spend, CTR, CPC, ROAS with breakdowns."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string", "description": "Ad account ID"},
                    "level": {
                        "type": "string",
                        "enum": ["campaign", "adset", "ad"],
                        "description": "Reporting level (default: campaign)",
                    },
                    "campaign_id": {"type": "string", "description": "Filter by campaign ID"},
                    "date_preset": {
                        "type": "string",
                        "enum": ["today", "yesterday", "last_7d", "last_30d", "this_month", "last_month"],
                        "description": "Date preset (default: last_30d)",
                    },
                    "time_range": {
                        "type": "object",
                        "description": "Custom time range: {since: YYYY-MM-DD, until: YYYY-MM-DD}",
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to fetch (default: impressions,clicks,spend,ctr,cpc)",
                    },
                    "breakdowns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Breakdowns: age, gender, country, platform_position, etc.",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific Meta account"},
                },
                "required": [],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        headers = self._bearer_headers(access_token)

        fields = params.get("fields", ["impressions", "clicks", "spend", "ctr", "cpc", "actions"])
        query_params = {
            "fields": ",".join(fields),
            "level": params.get("level", "campaign"),
        }

        if params.get("date_preset"):
            query_params["date_preset"] = params["date_preset"]
        elif params.get("time_range"):
            query_params["time_range"] = json.dumps(params["time_range"])
        else:
            query_params["date_preset"] = "last_30d"

        if params.get("breakdowns"):
            query_params["breakdowns"] = ",".join(params["breakdowns"])

        url = f"{META_ADS_API_BASE}/act_{ad_account_id}/insights"
        if params.get("campaign_id"):
            url = f"{META_ADS_API_BASE}/{params['campaign_id']}/insights"

        resp = await self._api_request("GET", url, headers=headers, params=query_params)
        return {"report": resp.json().get("data", []), "level": query_params["level"]}


class MetaAdsManageAudiencesTool(SocialMediaTool):
    """Create and update Meta Ads Custom and Lookalike audiences."""

    name = "meta_ads_manage_audiences"
    platform = "meta_ads"
    description = (
        "Manage Meta Ads audiences. Actions: 'create_custom' audience, "
        "'create_lookalike' audience, 'list' audiences, 'delete' an audience."
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
                        "enum": ["create_custom", "create_lookalike", "list", "delete"],
                        "description": "Action to perform",
                    },
                    "ad_account_id": {"type": "string", "description": "Ad account ID"},
                    "name": {"type": "string", "description": "Audience name"},
                    "description": {"type": "string", "description": "Audience description"},
                    "subtype": {
                        "type": "string",
                        "enum": ["CUSTOM", "WEBSITE", "APP", "ENGAGEMENT", "LOOKALIKE"],
                        "description": "Audience subtype",
                    },
                    "rule": {"type": "object", "description": "Audience rule definition"},
                    "source_audience_id": {"type": "string", "description": "Source audience for lookalike"},
                    "country": {"type": "string", "description": "Target country code for lookalike"},
                    "ratio": {"type": "number", "description": "Lookalike ratio 0.01-0.20"},
                    "audience_id": {"type": "string", "description": "Audience ID (for delete)"},
                    "account_name": {"type": "string", "description": "Optional: specific Meta account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        headers = self._bearer_headers(access_token)
        action = params["action"]

        if action == "create_custom":
            body = {
                "name": params.get("name", "Custom Audience"),
                "subtype": params.get("subtype", "CUSTOM"),
                "description": params.get("description", ""),
            }
            if params.get("rule"):
                body["rule"] = json.dumps(params["rule"])
            resp = await self._api_request(
                "POST", f"{META_ADS_API_BASE}/act_{ad_account_id}/customaudiences",
                headers=headers, json_body=body,
            )
            return {"action": "create_custom", "success": True, "audience_id": resp.json().get("id", "")}

        elif action == "create_lookalike":
            body = {
                "name": params.get("name", "Lookalike Audience"),
                "subtype": "LOOKALIKE",
                "origin_audience_id": params.get("source_audience_id", ""),
                "lookalike_spec": json.dumps({
                    "type": "similarity",
                    "country": params.get("country", "US"),
                    "ratio": params.get("ratio", 0.01),
                }),
            }
            resp = await self._api_request(
                "POST", f"{META_ADS_API_BASE}/act_{ad_account_id}/customaudiences",
                headers=headers, json_body=body,
            )
            return {"action": "create_lookalike", "success": True, "audience_id": resp.json().get("id", "")}

        elif action == "list":
            resp = await self._api_request(
                "GET", f"{META_ADS_API_BASE}/act_{ad_account_id}/customaudiences",
                headers=headers, params={"fields": "name,subtype,approximate_count,delivery_status"},
            )
            return {"action": "list", "audiences": resp.json().get("data", [])}

        elif action == "delete":
            audience_id = params.get("audience_id", "")
            await self._api_request(
                "DELETE", f"{META_ADS_API_BASE}/{audience_id}", headers=headers,
            )
            return {"action": "delete", "success": True, "audience_id": audience_id}

        return {"error": f"Unknown action: {action}"}
