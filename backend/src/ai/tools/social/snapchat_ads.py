"""
Snapchat Ads AI Agent Tools.

- SnapchatAdsCreateCampaignTool: Create campaigns
- SnapchatAdsManageAdSquadsTool: Manage ad squads with targeting
- SnapchatAdsReportTool: Fetch campaign performance metrics
- SnapchatAdsManageAudiencesTool: Create/manage SAM audiences
"""
import json
import logging
from typing import Any, Dict, Optional
from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)
SNAP_API_BASE = "https://adsapi.snapchat.com/v1"


class SnapchatAdsCreateCampaignTool(SocialMediaTool):
    name = "snapchat_ads_create_campaign"
    platform = "snapchat_ads"
    description = "Create a Snapchat Ads campaign with objectives: awareness, app installs, conversions, etc."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string", "description": "Snapchat ad account ID"},
                    "name": {"type": "string", "description": "Campaign name"},
                    "objective": {"type": "string", "enum": ["AWARENESS","APP_INSTALLS","DRIVING_TRAFFIC_TO_WEBSITE","LEAD_GENERATION","VIDEO_VIEWS","WEB_CONVERSIONS"]},
                    "status": {"type": "string", "enum": ["ACTIVE","PAUSED"], "description": "Default: PAUSED"},
                    "daily_budget_micro": {"type": "integer", "description": "Daily budget in micro units"},
                    "lifetime_spend_cap_micro": {"type": "integer"},
                    "start_time": {"type": "string"}, "end_time": {"type": "string"},
                    "account_name": {"type": "string"},
                }, "required": ["ad_account_id", "name", "objective"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params["ad_account_id"]
        headers = self._bearer_headers(access_token)
        campaign = {"name": params["name"], "ad_account_id": ad_account_id, "objective": params["objective"], "status": params.get("status","PAUSED")}
        for k in ["daily_budget_micro","lifetime_spend_cap_micro","start_time","end_time"]:
            if params.get(k): campaign[k] = params[k]
        resp = await self._api_request("POST", f"{SNAP_API_BASE}/adaccounts/{ad_account_id}/campaigns", headers=headers, json_body={"campaigns": [campaign]})
        data = resp.json()
        campaigns = data.get("campaigns", [{}])
        cid = campaigns[0].get("campaign", {}).get("id", "") if campaigns else ""
        return {"success": True, "campaign_id": cid, "name": params["name"], "message": "Campaign created on Snapchat Ads"}


class SnapchatAdsManageAdSquadsTool(SocialMediaTool):
    name = "snapchat_ads_manage_ad_squads"
    platform = "snapchat_ads"
    description = "Manage Snapchat ad squads. Actions: create, update, list ad squads with targeting and budget."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create","update","list"]},
                    "ad_account_id": {"type": "string"}, "campaign_id": {"type": "string"},
                    "ad_squad_id": {"type": "string"}, "name": {"type": "string"},
                    "billing_event": {"type": "string", "enum": ["IMPRESSION","SWIPE_UP"]},
                    "bid_micro": {"type": "integer"}, "daily_budget_micro": {"type": "integer"},
                    "optimization_goal": {"type": "string", "enum": ["IMPRESSIONS","SWIPES","APP_INSTALLS","PIXEL_PAGE_VIEW"]},
                    "placement": {"type": "string", "enum": ["SNAP_ADS","STORY_ADS","CONTENT","SPOTLIGHT"]},
                    "targeting": {"type": "object", "description": "Targeting spec (geo, demographics, interests)"},
                    "status": {"type": "string", "enum": ["ACTIVE","PAUSED"]},
                    "account_name": {"type": "string"},
                }, "required": ["action", "ad_account_id"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params["ad_account_id"]
        headers = self._bearer_headers(access_token)
        action = params["action"]
        if action == "create":
            squad = {"campaign_id": params.get("campaign_id",""), "name": params.get("name","Ad Squad"), "billing_event": params.get("billing_event","IMPRESSION"), "optimization_goal": params.get("optimization_goal","IMPRESSIONS"), "status": params.get("status","PAUSED")}
            for k in ["bid_micro","daily_budget_micro","placement","targeting"]:
                if params.get(k): squad[k] = params[k]
            resp = await self._api_request("POST", f"{SNAP_API_BASE}/campaigns/{params.get('campaign_id','')}/adsquads", headers=headers, json_body={"adsquads": [squad]})
            squads = resp.json().get("adsquads", [{}])
            sid = squads[0].get("adsquad", {}).get("id", "") if squads else ""
            return {"action": "create", "success": True, "ad_squad_id": sid}
        elif action == "update":
            sid = params.get("ad_squad_id","")
            body = {k: params[k] for k in ["name","status","bid_micro","daily_budget_micro","targeting"] if params.get(k)}
            body["id"] = sid
            await self._api_request("PUT", f"{SNAP_API_BASE}/adsquads/{sid}", headers=headers, json_body={"adsquads": [body]})
            return {"action": "update", "success": True, "ad_squad_id": sid}
        elif action == "list":
            cid = params.get("campaign_id","")
            resp = await self._api_request("GET", f"{SNAP_API_BASE}/campaigns/{cid}/adsquads", headers=headers)
            return {"action": "list", "ad_squads": resp.json().get("adsquads",[])}
        return {"error": f"Unknown action: {action}"}


class SnapchatAdsReportTool(SocialMediaTool):
    name = "snapchat_ads_report"
    platform = "snapchat_ads"
    description = "Get performance reports for Snapchat Ads campaigns, ad squads, and ads."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string"}, "entity": {"type": "string", "enum": ["campaigns","adsquads","ads"]},
                    "entity_id": {"type": "string"}, "granularity": {"type": "string", "enum": ["HOUR","DAY","TOTAL"]},
                    "start_time": {"type": "string"}, "end_time": {"type": "string"},
                    "fields": {"type": "array", "items": {"type": "string"}, "description": "Metrics: impressions, swipes, spend, etc."},
                    "account_name": {"type": "string"},
                }, "required": ["ad_account_id", "entity", "entity_id"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        headers = self._bearer_headers(access_token)
        entity = params["entity"]
        entity_id = params["entity_id"]
        qp = {"granularity": params.get("granularity","TOTAL"), "fields": ",".join(params.get("fields",["impressions","swipes","spend"]))}
        for k in ["start_time","end_time"]:
            if params.get(k): qp[k] = params[k]
        resp = await self._api_request("GET", f"{SNAP_API_BASE}/{entity}/{entity_id}/stats", headers=headers, params=qp)
        return {"report": resp.json(), "entity": entity}


class SnapchatAdsManageAudiencesTool(SocialMediaTool):
    name = "snapchat_ads_manage_audiences"
    platform = "snapchat_ads"
    description = "Manage Snapchat Ads SAM audiences. Actions: create, list, delete audiences."

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create","list","delete"]},
                    "ad_account_id": {"type": "string"}, "name": {"type": "string"},
                    "source_type": {"type": "string", "enum": ["FIRST_PARTY","ENGAGEMENT","PIXEL","LOOKALIKE"]},
                    "segment_id": {"type": "string"}, "retention_in_days": {"type": "integer"},
                    "account_name": {"type": "string"},
                }, "required": ["action", "ad_account_id"],
            },
        }

    async def _execute(self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params["ad_account_id"]
        headers = self._bearer_headers(access_token)
        action = params["action"]
        if action == "create":
            seg = {"name": params.get("name","Audience"), "source_type": params.get("source_type","FIRST_PARTY"), "ad_account_id": ad_account_id, "retention_in_days": params.get("retention_in_days",30)}
            resp = await self._api_request("POST", f"{SNAP_API_BASE}/adaccounts/{ad_account_id}/segments", headers=headers, json_body={"segments": [seg]})
            segs = resp.json().get("segments",[{}])
            sid = segs[0].get("segment",{}).get("id","") if segs else ""
            return {"action": "create", "success": True, "segment_id": sid}
        elif action == "list":
            resp = await self._api_request("GET", f"{SNAP_API_BASE}/adaccounts/{ad_account_id}/segments", headers=headers)
            return {"action": "list", "segments": resp.json().get("segments",[])}
        elif action == "delete":
            sid = params.get("segment_id","")
            await self._api_request("DELETE", f"{SNAP_API_BASE}/segments/{sid}", headers=headers)
            return {"action": "delete", "success": True, "segment_id": sid}
        return {"error": f"Unknown action: {action}"}
