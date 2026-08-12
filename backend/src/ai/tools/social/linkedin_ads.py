"""
LinkedIn Ads AI Agent Tools.

Provides tools for LinkedIn advertising via Campaign Manager API:
- LinkedInAdsCreateCampaignTool: Create Sponsored Content, Message Ads, Dynamic Ads
- LinkedInAdsManageCreativesTool: Create/update ad creatives
- LinkedInAdsReportTool: Fetch campaign analytics with breakdowns
- LinkedInAdsManageAudiencesTool: Create/update matched audiences
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

LINKEDIN_ADS_API_BASE = "https://api.linkedin.com/rest"


class LinkedInAdsCreateCampaignTool(SocialMediaTool):
    """Create LinkedIn advertising campaigns."""

    name = "linkedin_ads_create_campaign"
    platform = "linkedin_ads"
    description = (
        "Create a LinkedIn Ads campaign (Sponsored Content, Message Ads, or Dynamic Ads). "
        "Requires a LinkedIn connection with rw_ads scope."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string", "description": "LinkedIn ad account ID"},
                    "campaign_group_id": {"type": "string", "description": "Campaign group ID"},
                    "name": {"type": "string", "description": "Campaign name"},
                    "objective_type": {
                        "type": "string",
                        "enum": ["BRAND_AWARENESS", "WEBSITE_VISITS", "ENGAGEMENT",
                                 "VIDEO_VIEWS", "LEAD_GENERATION", "WEBSITE_CONVERSIONS",
                                 "JOB_APPLICANTS", "TALENT_LEADS"],
                        "description": "Campaign objective",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["SPONSORED_UPDATES", "SPONSORED_INMAILS", "TEXT_AD", "DYNAMIC"],
                        "description": "Campaign type (default: SPONSORED_UPDATES)",
                    },
                    "daily_budget": {"type": "object", "description": "{amount: string, currencyCode: string}"},
                    "total_budget": {"type": "object", "description": "{amount: string, currencyCode: string}"},
                    "status": {"type": "string", "enum": ["ACTIVE", "PAUSED", "DRAFT"], "description": "Status"},
                    "targeting": {"type": "object", "description": "Targeting criteria object"},
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": ["name", "objective_type"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        body = {
            "account": f"urn:li:sponsoredAccount:{ad_account_id}",
            "name": params["name"],
            "objectiveType": params["objective_type"],
            "type": params.get("type", "SPONSORED_UPDATES"),
            "status": params.get("status", "DRAFT"),
        }
        if params.get("campaign_group_id"):
            body["campaignGroup"] = f"urn:li:sponsoredCampaignGroup:{params['campaign_group_id']}"
        if params.get("daily_budget"):
            body["dailyBudget"] = params["daily_budget"]
        if params.get("total_budget"):
            body["totalBudget"] = params["total_budget"]
        if params.get("targeting"):
            body["targetingCriteria"] = params["targeting"]

        resp = await self._api_request(
            "POST", f"{LINKEDIN_ADS_API_BASE}/adCampaigns",
            headers=headers, json_body=body,
        )
        campaign_id = resp.headers.get("x-restli-id", "")
        return {
            "success": True,
            "campaign_id": campaign_id,
            "name": params["name"],
            "message": "Campaign created on LinkedIn Ads",
        }


class LinkedInAdsManageCreativesTool(SocialMediaTool):
    """Create and update LinkedIn ad creatives."""

    name = "linkedin_ads_manage_creatives"
    platform = "linkedin_ads"
    description = (
        "Manage LinkedIn ad creatives. Actions: 'create' a creative with copy/media/CTA, "
        "'update' an existing creative, 'list' creatives in a campaign."
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
                    "campaign_id": {"type": "string", "description": "Campaign ID"},
                    "creative_id": {"type": "string", "description": "Creative ID (for update)"},
                    "type": {
                        "type": "string",
                        "enum": ["SPONSORED_STATUS_UPDATE", "SPONSORED_VIDEO", "SPONSORED_INMAIL"],
                        "description": "Creative type",
                    },
                    "text": {"type": "string", "description": "Ad copy text"},
                    "headline": {"type": "string", "description": "Ad headline"},
                    "description": {"type": "string", "description": "Ad description"},
                    "landing_page_url": {"type": "string", "description": "Landing page URL"},
                    "call_to_action": {
                        "type": "string",
                        "enum": ["APPLY_NOW", "DOWNLOAD", "LEARN_MORE", "SIGN_UP", "SUBSCRIBE", "REGISTER", "REQUEST_DEMO"],
                        "description": "Call-to-action button",
                    },
                    "image_url": {"type": "string", "description": "Image URL for the creative"},
                    "status": {"type": "string", "enum": ["ACTIVE", "PAUSED", "DRAFT"], "description": "Status"},
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

        if action == "create":
            campaign_id = params.get("campaign_id", "")
            body = {
                "campaign": f"urn:li:sponsoredCampaign:{campaign_id}",
                "type": params.get("type", "SPONSORED_STATUS_UPDATE"),
                "status": params.get("status", "DRAFT"),
            }
            # Build creative variables based on type
            variables = {}
            if params.get("text"):
                variables["text"] = params["text"]
            if params.get("headline"):
                variables["headline"] = params["headline"]
            if params.get("landing_page_url"):
                variables["landingPageUrl"] = params["landing_page_url"]
            if params.get("call_to_action"):
                variables["callToAction"] = params["call_to_action"]
            if variables:
                body["variables"] = {"data": variables}

            resp = await self._api_request(
                "POST", f"{LINKEDIN_ADS_API_BASE}/adCreatives",
                headers=headers, json_body=body,
            )
            creative_id = resp.headers.get("x-restli-id", "")
            return {"action": "create", "success": True, "creative_id": creative_id}

        elif action == "update":
            creative_id = params.get("creative_id", "")
            if not creative_id:
                return {"error": "creative_id required for update"}
            body = {}
            if params.get("status"):
                body["status"] = params["status"]
            resp = await self._api_request(
                "POST", f"{LINKEDIN_ADS_API_BASE}/adCreatives/{creative_id}",
                headers=headers, json_body=body,
            )
            return {"action": "update", "success": True, "creative_id": creative_id}

        elif action == "list":
            campaign_id = params.get("campaign_id", "")
            resp = await self._api_request(
                "GET", f"{LINKEDIN_ADS_API_BASE}/adCreatives",
                headers=headers,
                params={"q": "campaign", "campaign": f"urn:li:sponsoredCampaign:{campaign_id}"},
            )
            return {"action": "list", "creatives": resp.json().get("elements", [])}

        return {"error": f"Unknown action: {action}"}


class LinkedInAdsReportTool(SocialMediaTool):
    """Fetch LinkedIn Ads campaign analytics with breakdowns."""

    name = "linkedin_ads_report"
    platform = "linkedin_ads"
    description = (
        "Get LinkedIn Ads campaign analytics with demographic and company breakdowns. "
        "Returns impressions, clicks, spend, CTR, and engagement metrics."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string", "description": "LinkedIn ad account ID"},
                    "campaign_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Campaign IDs to report on",
                    },
                    "date_range": {
                        "type": "object",
                        "description": "Date range: {start: {day, month, year}, end: {day, month, year}}",
                    },
                    "time_granularity": {
                        "type": "string",
                        "enum": ["DAILY", "MONTHLY", "ALL"],
                        "description": "Time granularity (default: ALL)",
                    },
                    "pivot": {
                        "type": "string",
                        "enum": ["CAMPAIGN", "CREATIVE", "COMPANY", "MEMBER_COMPANY_SIZE",
                                 "MEMBER_INDUSTRY", "MEMBER_JOB_FUNCTION", "MEMBER_SENIORITY"],
                        "description": "Breakdown dimension",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": [],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })

        query_params = {
            "q": "analytics",
            "pivot": params.get("pivot", "CAMPAIGN"),
            "timeGranularity": params.get("time_granularity", "ALL"),
        }

        campaign_ids = params.get("campaign_ids", [])
        if campaign_ids:
            for i, cid in enumerate(campaign_ids):
                query_params[f"campaigns[{i}]"] = f"urn:li:sponsoredCampaign:{cid}"

        if params.get("date_range"):
            dr = params["date_range"]
            if dr.get("start"):
                for k, v in dr["start"].items():
                    query_params[f"dateRange.start.{k}"] = str(v)
            if dr.get("end"):
                for k, v in dr["end"].items():
                    query_params[f"dateRange.end.{k}"] = str(v)

        resp = await self._api_request(
            "GET", f"{LINKEDIN_ADS_API_BASE}/adAnalytics",
            headers=headers, params=query_params,
        )

        return {
            "report": resp.json().get("elements", []),
            "pivot": query_params["pivot"],
            "time_granularity": query_params["timeGranularity"],
        }


class LinkedInAdsManageAudiencesTool(SocialMediaTool):
    """Create and update LinkedIn matched audiences."""

    name = "linkedin_ads_manage_audiences"
    platform = "linkedin_ads"
    description = (
        "Manage LinkedIn Ads matched audiences. Actions: 'create' company/contact/retargeting audience, "
        "'list' audiences, 'delete' an audience."
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
                        "enum": ["create", "list", "delete"],
                        "description": "Action to perform",
                    },
                    "ad_account_id": {"type": "string", "description": "LinkedIn ad account ID"},
                    "name": {"type": "string", "description": "Audience name"},
                    "audience_type": {
                        "type": "string",
                        "enum": ["COMPANY", "CONTACT", "RETARGETING"],
                        "description": "Type of matched audience",
                    },
                    "segment_id": {"type": "string", "description": "Segment ID (for delete)"},
                    "source_data": {
                        "type": "object",
                        "description": "Source data for audience creation (e.g. company names, emails)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific LinkedIn account"},
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        ad_account_id = params.get("ad_account_id") or credentials.get("oauth_metadata", {}).get("ad_account_id", "")
        headers = self._bearer_headers(access_token, {
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        })
        action = params["action"]

        if action == "create":
            body = {
                "name": params.get("name", "Matched Audience"),
                "type": params.get("audience_type", "COMPANY"),
                "account": f"urn:li:sponsoredAccount:{ad_account_id}",
            }
            if params.get("source_data"):
                body["sourceData"] = params["source_data"]
            resp = await self._api_request(
                "POST", f"{LINKEDIN_ADS_API_BASE}/dmpSegments",
                headers=headers, json_body=body,
            )
            segment_id = resp.headers.get("x-restli-id", "")
            return {"action": "create", "success": True, "segment_id": segment_id}

        elif action == "list":
            resp = await self._api_request(
                "GET", f"{LINKEDIN_ADS_API_BASE}/dmpSegments",
                headers=headers,
                params={"q": "account", "account": f"urn:li:sponsoredAccount:{ad_account_id}"},
            )
            return {"action": "list", "audiences": resp.json().get("elements", [])}

        elif action == "delete":
            segment_id = params.get("segment_id", "")
            await self._api_request(
                "DELETE", f"{LINKEDIN_ADS_API_BASE}/dmpSegments/{segment_id}",
                headers=headers,
            )
            return {"action": "delete", "success": True, "segment_id": segment_id}

        return {"error": f"Unknown action: {action}"}
