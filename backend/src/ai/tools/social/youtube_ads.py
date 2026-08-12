"""
YouTube Ads AI Agent Tools.

Provides tools for YouTube video campaign management via the Google Ads API:
- YouTubeAdsCreateCampaignTool: Create video ad campaigns
- YouTubeAdsManageAdGroupsTool: Manage ad groups with targeting
- YouTubeAdsReportTool: Fetch video campaign performance metrics
- YouTubeAdsManageTargetingTool: Configure audience and placement targeting
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

GOOGLE_ADS_API_BASE = "https://googleads.googleapis.com/v17"


class YouTubeAdsCreateCampaignTool(SocialMediaTool):
    """Create YouTube video advertising campaigns via Google Ads."""

    name = "youtube_ads_create_campaign"
    platform = "youtube_ads"
    description = (
        "Create a YouTube Ads video campaign via Google Ads API. "
        "Supports TrueView, bumper, and non-skippable ad formats."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "Google Ads customer ID"},
                    "name": {"type": "string", "description": "Campaign name"},
                    "budget_amount_micros": {"type": "integer", "description": "Daily budget in micros (1 USD = 1000000)"},
                    "advertising_channel_type": {
                        "type": "string",
                        "enum": ["VIDEO"],
                        "description": "Channel type (VIDEO for YouTube)",
                    },
                    "advertising_channel_sub_type": {
                        "type": "string",
                        "enum": ["VIDEO_ACTION", "VIDEO_NON_SKIPPABLE", "VIDEO_REACH_TARGET_FREQUENCY"],
                        "description": "Sub type for video campaigns",
                    },
                    "bidding_strategy_type": {
                        "type": "string",
                        "enum": ["TARGET_CPA", "MAXIMIZE_CONVERSIONS", "TARGET_CPM"],
                        "description": "Bidding strategy",
                    },
                    "target_cpa_micros": {"type": "integer", "description": "Target CPA in micros"},
                    "status": {
                        "type": "string",
                        "enum": ["ENABLED", "PAUSED"],
                        "description": "Campaign status (default: PAUSED)",
                    },
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "account_name": {"type": "string", "description": "Optional: specific Google account"},
                },
                "required": ["customer_id", "name", "budget_amount_micros"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        customer_id = params["customer_id"].replace("-", "")
        headers = self._bearer_headers(access_token, {"developer-token": credentials.get("oauth_metadata", {}).get("developer_token", "")})

        operations = [{
            "create": {
                "name": params["name"],
                "status": params.get("status", "PAUSED"),
                "advertisingChannelType": "VIDEO",
                "advertisingChannelSubType": params.get("advertising_channel_sub_type", "VIDEO_ACTION"),
                "campaignBudget": {
                    "amountMicros": str(params["budget_amount_micros"]),
                    "deliveryMethod": "STANDARD",
                },
            }
        }]

        if params.get("bidding_strategy_type") == "TARGET_CPA" and params.get("target_cpa_micros"):
            operations[0]["create"]["targetCpa"] = {"targetCpaMicros": str(params["target_cpa_micros"])}

        resp = await self._api_request(
            "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/campaigns:mutate",
            headers=headers, json_body={"operations": operations},
        )
        data = resp.json()
        results = data.get("results", [])
        campaign_resource = results[0].get("resourceName", "") if results else ""
        return {
            "success": True,
            "campaign_resource_name": campaign_resource,
            "name": params["name"],
            "message": "YouTube Ads campaign created",
        }


class YouTubeAdsManageAdGroupsTool(SocialMediaTool):
    """Manage YouTube ad groups with targeting and ad formats."""

    name = "youtube_ads_manage_ad_groups"
    platform = "youtube_ads"
    description = (
        "Manage YouTube Ads ad groups. Actions: 'create', 'update', 'list' ad groups "
        "within a campaign, with targeting and bidding configuration."
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
                    "customer_id": {"type": "string", "description": "Google Ads customer ID"},
                    "campaign_id": {"type": "string", "description": "Campaign resource name or ID"},
                    "ad_group_id": {"type": "string", "description": "Ad group ID (for update)"},
                    "name": {"type": "string", "description": "Ad group name"},
                    "type": {
                        "type": "string",
                        "enum": ["VIDEO_TRUE_VIEW_IN_STREAM", "VIDEO_TRUE_VIEW_IN_DISPLAY", "VIDEO_BUMPER", "VIDEO_NON_SKIPPABLE_IN_STREAM"],
                        "description": "Ad group type",
                    },
                    "cpc_bid_micros": {"type": "integer", "description": "CPC bid in micros"},
                    "cpv_bid_micros": {"type": "integer", "description": "CPV bid in micros"},
                    "status": {"type": "string", "enum": ["ENABLED", "PAUSED"], "description": "Status"},
                    "account_name": {"type": "string", "description": "Optional: specific Google account"},
                },
                "required": ["action", "customer_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        customer_id = params["customer_id"].replace("-", "")
        headers = self._bearer_headers(access_token, {"developer-token": credentials.get("oauth_metadata", {}).get("developer_token", "")})
        action = params["action"]

        if action == "create":
            operations = [{
                "create": {
                    "name": params.get("name", "Ad Group"),
                    "campaign": params.get("campaign_id", ""),
                    "type": params.get("type", "VIDEO_TRUE_VIEW_IN_STREAM"),
                    "status": params.get("status", "PAUSED"),
                }
            }]
            if params.get("cpv_bid_micros"):
                operations[0]["create"]["cpvBidMicros"] = str(params["cpv_bid_micros"])
            resp = await self._api_request(
                "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/adGroups:mutate",
                headers=headers, json_body={"operations": operations},
            )
            results = resp.json().get("results", [])
            return {"action": "create", "success": True, "ad_group": results[0] if results else {}}

        elif action == "update":
            ad_group_id = params.get("ad_group_id", "")
            operations = [{"update": {"resourceName": ad_group_id, "status": params.get("status", "PAUSED")}, "updateMask": "status"}]
            resp = await self._api_request(
                "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/adGroups:mutate",
                headers=headers, json_body={"operations": operations},
            )
            return {"action": "update", "success": True}

        elif action == "list":
            query = f"SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.type FROM ad_group WHERE campaign.id = '{params.get('campaign_id', '')}'"
            resp = await self._api_request(
                "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/googleAds:searchStream",
                headers=headers, json_body={"query": query},
            )
            return {"action": "list", "ad_groups": resp.json()}

        return {"error": f"Unknown action: {action}"}


class YouTubeAdsReportTool(SocialMediaTool):
    """Fetch YouTube Ads campaign performance metrics."""

    name = "youtube_ads_report"
    platform = "youtube_ads"
    description = (
        "Get performance reports for YouTube Ads campaigns. Returns video views, "
        "view rate, CPV, impressions, clicks, and conversions."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "Google Ads customer ID"},
                    "campaign_id": {"type": "string", "description": "Campaign ID (optional filter)"},
                    "date_range": {
                        "type": "string",
                        "enum": ["TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_30_DAYS", "THIS_MONTH", "LAST_MONTH"],
                        "description": "Date range preset (default: LAST_30_DAYS)",
                    },
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to include (default: impressions, video_views, clicks, cost_micros, video_view_rate)",
                    },
                    "account_name": {"type": "string", "description": "Optional: specific Google account"},
                },
                "required": ["customer_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        customer_id = params["customer_id"].replace("-", "")
        headers = self._bearer_headers(access_token, {"developer-token": credentials.get("oauth_metadata", {}).get("developer_token", "")})

        metrics = params.get("metrics", ["metrics.impressions", "metrics.video_views", "metrics.clicks", "metrics.cost_micros", "metrics.video_view_rate"])
        metrics_str = ", ".join(metrics)
        date_range = params.get("date_range", "LAST_30_DAYS")

        query = f"SELECT campaign.id, campaign.name, {metrics_str} FROM campaign WHERE campaign.advertising_channel_type = 'VIDEO' AND segments.date DURING {date_range}"
        if params.get("campaign_id"):
            query += f" AND campaign.id = '{params['campaign_id']}'"

        resp = await self._api_request(
            "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/googleAds:searchStream",
            headers=headers, json_body={"query": query},
        )
        return {"report": resp.json(), "date_range": date_range}


class YouTubeAdsManageTargetingTool(SocialMediaTool):
    """Configure audience and placement targeting for YouTube Ads."""

    name = "youtube_ads_manage_targeting"
    platform = "youtube_ads"
    description = (
        "Manage targeting for YouTube Ads ad groups. Configure audience segments, "
        "topics, placements, keywords, and demographics."
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
                        "enum": ["add", "remove", "list"],
                        "description": "Action to perform",
                    },
                    "customer_id": {"type": "string", "description": "Google Ads customer ID"},
                    "ad_group_id": {"type": "string", "description": "Ad group resource name"},
                    "targeting_type": {
                        "type": "string",
                        "enum": ["AUDIENCE", "TOPIC", "PLACEMENT", "KEYWORD", "AGE_RANGE", "GENDER"],
                        "description": "Type of targeting criterion",
                    },
                    "criterion_value": {"type": "string", "description": "Value for the targeting criterion"},
                    "audience_id": {"type": "string", "description": "Audience segment resource name"},
                    "account_name": {"type": "string", "description": "Optional: specific Google account"},
                },
                "required": ["action", "customer_id", "ad_group_id"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        access_token = credentials["access_token"]
        customer_id = params["customer_id"].replace("-", "")
        headers = self._bearer_headers(access_token, {"developer-token": credentials.get("oauth_metadata", {}).get("developer_token", "")})
        action = params["action"]
        ad_group_id = params["ad_group_id"]

        if action == "add":
            targeting_type = params.get("targeting_type", "AUDIENCE")
            operations = [{"create": {"adGroup": ad_group_id, "type": targeting_type}}]
            if targeting_type == "AUDIENCE" and params.get("audience_id"):
                operations[0]["create"]["audience"] = {"audienceSegment": params["audience_id"]}
            elif params.get("criterion_value"):
                operations[0]["create"]["criterionValue"] = params["criterion_value"]
            resp = await self._api_request(
                "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/adGroupCriteria:mutate",
                headers=headers, json_body={"operations": operations},
            )
            return {"action": "add", "success": True, "data": resp.json()}

        elif action == "remove":
            criterion_value = params.get("criterion_value", "")
            operations = [{"remove": criterion_value}]
            resp = await self._api_request(
                "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/adGroupCriteria:mutate",
                headers=headers, json_body={"operations": operations},
            )
            return {"action": "remove", "success": True}

        elif action == "list":
            query = f"SELECT ad_group_criterion.type, ad_group_criterion.status FROM ad_group_criterion WHERE ad_group.resource_name = '{ad_group_id}'"
            resp = await self._api_request(
                "POST", f"{GOOGLE_ADS_API_BASE}/customers/{customer_id}/googleAds:searchStream",
                headers=headers, json_body={"query": query},
            )
            return {"action": "list", "criteria": resp.json()}

        return {"error": f"Unknown action: {action}"}
