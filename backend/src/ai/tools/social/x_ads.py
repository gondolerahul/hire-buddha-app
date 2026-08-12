"""
X (Twitter) Ads AI Agent Tools.

- XAdsCreateCampaignTool: Create advertising campaigns
- XAdsManageLineItemsTool: Manage line items with targeting
- XAdsReportTool: Fetch campaign performance analytics
- XAdsManageAudiencesTool: Create/manage tailored audiences
"""
import json
import logging
from typing import Any, Dict, Optional
from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)
X_ADS_API_BASE = "https://ads-api.x.com/12"


class XAdsCreateCampaignTool(SocialMediaTool):
    name = "x_ads_create_campaign"
    platform = "x_ads"
    description = "Create an advertising campaign on X (Twitter) with objectives like awareness, reach, engagement."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "X Ads account ID"},
                    "name": {"type": "string", "description": "Campaign name"},
                    "objective": {"type": "string", "enum": ["AWARENESS","REACH","ENGAGEMENTS","VIDEO_VIEWS","WEBSITE_CLICKS","APP_INSTALLS","FOLLOWERS"]},
                    "daily_budget_amount_local_micro": {"type": "integer", "description": "Daily budget in micro units"},
                    "total_budget_amount_local_micro": {"type": "integer"},
                    "start_time": {"type": "string"}, "end_time": {"type": "string"},
                    "entity_status": {"type": "string", "enum": ["ACTIVE","PAUSED","DRAFT"]},
                    "account_name": {"type": "string"},
                }, "required": ["account_id", "name", "objective"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        account_id = params["account_id"]
        headers = self._bearer_headers(access_token)
        body = {"name": params["name"], "objective": params["objective"], "entity_status": params.get("entity_status", "DRAFT")}
        for k in ["daily_budget_amount_local_micro","total_budget_amount_local_micro","start_time","end_time"]:
            if params.get(k): body[k] = params[k]
        resp = await self._api_request("POST", f"{X_ADS_API_BASE}/accounts/{account_id}/campaigns", headers=headers, json_body=body)
        data = resp.json().get("data", {})
        return {"success": True, "campaign_id": data.get("id",""), "name": params["name"], "message": "Campaign created on X Ads"}


class XAdsManageLineItemsTool(SocialMediaTool):
    name = "x_ads_manage_line_items"
    platform = "x_ads"
    description = "Manage X Ads line items (ad groups). Actions: create, update, list."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create","update","list"]},
                    "account_id": {"type": "string"}, "campaign_id": {"type": "string"},
                    "line_item_id": {"type": "string"}, "name": {"type": "string"},
                    "product_type": {"type": "string", "enum": ["PROMOTED_TWEETS","PROMOTED_ACCOUNT"]},
                    "placements": {"type": "array", "items": {"type": "string"}},
                    "bid_amount_local_micro": {"type": "integer"},
                    "bid_type": {"type": "string", "enum": ["AUTO","MAX","TARGET"]},
                    "entity_status": {"type": "string", "enum": ["ACTIVE","PAUSED","DRAFT"]},
                    "account_name": {"type": "string"},
                }, "required": ["action", "account_id"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        account_id = params["account_id"]
        headers = self._bearer_headers(access_token)
        action = params["action"]
        if action == "create":
            body = {"campaign_id": params.get("campaign_id",""), "name": params.get("name","Line Item"), "product_type": params.get("product_type","PROMOTED_TWEETS"), "placements": params.get("placements",["ALL_ON_TWITTER"]), "entity_status": params.get("entity_status","DRAFT")}
            for k in ["bid_amount_local_micro","bid_type"]:
                if params.get(k): body[k] = params[k]
            resp = await self._api_request("POST", f"{X_ADS_API_BASE}/accounts/{account_id}/line_items", headers=headers, json_body=body)
            return {"action": "create", "success": True, "line_item_id": resp.json().get("data",{}).get("id","")}
        elif action == "update":
            lid = params.get("line_item_id","")
            body = {k: params[k] for k in ["name","entity_status","bid_amount_local_micro","bid_type"] if params.get(k)}
            await self._api_request("PUT", f"{X_ADS_API_BASE}/accounts/{account_id}/line_items/{lid}", headers=headers, json_body=body)
            return {"action": "update", "success": True, "line_item_id": lid}
        elif action == "list":
            qp = {}
            if params.get("campaign_id"): qp["campaign_ids"] = params["campaign_id"]
            resp = await self._api_request("GET", f"{X_ADS_API_BASE}/accounts/{account_id}/line_items", headers=headers, params=qp)
            return {"action": "list", "line_items": resp.json().get("data",[])}
        return {"error": f"Unknown action: {action}"}


class XAdsReportTool(SocialMediaTool):
    name = "x_ads_report"
    platform = "x_ads"
    description = "Get performance reports for X Ads campaigns with segmentation options."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"}, "entity": {"type": "string", "enum": ["CAMPAIGN","LINE_ITEM","PROMOTED_TWEET"]},
                    "entity_ids": {"type": "array", "items": {"type": "string"}},
                    "start_time": {"type": "string"}, "end_time": {"type": "string"},
                    "granularity": {"type": "string", "enum": ["HOUR","DAY","TOTAL"]},
                    "metric_groups": {"type": "array", "items": {"type": "string"}},
                    "segmentation_type": {"type": "string", "enum": ["AGE","GENDER","LOCATIONS","PLATFORMS"]},
                    "account_name": {"type": "string"},
                }, "required": ["account_id", "entity", "entity_ids"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        account_id = params["account_id"]
        headers = self._bearer_headers(access_token)
        qp = {"entity": params["entity"], "entity_ids": ",".join(params["entity_ids"]), "granularity": params.get("granularity","TOTAL"), "metric_groups": ",".join(params.get("metric_groups",["ENGAGEMENT","BILLING"]))}
        for k in ["start_time","end_time","segmentation_type"]:
            if params.get(k): qp[k] = params[k]
        resp = await self._api_request("GET", f"{X_ADS_API_BASE}/stats/accounts/{account_id}", headers=headers, params=qp)
        return {"report": resp.json().get("data",[]), "entity": params["entity"]}


class XAdsManageAudiencesTool(SocialMediaTool):
    name = "x_ads_manage_audiences"
    platform = "x_ads"
    description = "Manage X Ads tailored audiences. Actions: create, list, delete."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create","list","delete"]},
                    "account_id": {"type": "string"}, "name": {"type": "string"},
                    "audience_type": {"type": "string", "enum": ["TAILORED_LIST","WEBSITE","APP_EVENT","FLEXIBLE"]},
                    "audience_id": {"type": "string"}, "account_name": {"type": "string"},
                }, "required": ["action", "account_id"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        account_id = params["account_id"]
        headers = self._bearer_headers(access_token)
        action = params["action"]
        if action == "create":
            body = {"name": params.get("name","Tailored Audience"), "audience_type": params.get("audience_type","TAILORED_LIST")}
            resp = await self._api_request("POST", f"{X_ADS_API_BASE}/accounts/{account_id}/tailored_audiences", headers=headers, json_body=body)
            return {"action": "create", "success": True, "audience_id": resp.json().get("data",{}).get("id","")}
        elif action == "list":
            resp = await self._api_request("GET", f"{X_ADS_API_BASE}/accounts/{account_id}/tailored_audiences", headers=headers)
            return {"action": "list", "audiences": resp.json().get("data",[])}
        elif action == "delete":
            aid = params.get("audience_id","")
            await self._api_request("DELETE", f"{X_ADS_API_BASE}/accounts/{account_id}/tailored_audiences/{aid}", headers=headers)
            return {"action": "delete", "success": True, "audience_id": aid}
        return {"error": f"Unknown action: {action}"}
