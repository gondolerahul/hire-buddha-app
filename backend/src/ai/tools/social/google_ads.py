"""
Google Ads AI Agent Tools.

Provides tools for Google Ads campaign management via the Google Ads API:
- GoogleAdsCreateCampaignTool: Create campaigns
- GoogleAdsReportTool: Run GAQL reporting queries
- GoogleAdsManageKeywordsTool: Add/remove/update keywords
- GoogleAdsGetAdGroupsTool: List ad groups and settings
"""
import json
import logging
from typing import Any, Dict, Optional

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

def _api_base() -> str:
    """The Google Ads API at the one version setting, ``GOOGLE_ADS_API_VERSION`` (GADS-E2)."""
    from src.connections.api_versions import google_ads_version
    return f"https://googleads.googleapis.com/{google_ads_version()}"


def _customer_id(credentials: Dict[str, Any]) -> str:
    return str((credentials.get("oauth_metadata") or {}).get("customer_id") or "").replace("-", "")


def _ads_headers(credentials: Dict[str, Any]) -> Dict[str, str]:
    """The bearer token, and the manager account the business works through
    (``login-customer-id``). No developer token is needed: since 9 Sep 2026 the
    access level belongs to the Cloud project of the OAuth client (GADS-E1); an
    old connection's own token is still sent, and Google ignores it."""
    meta = credentials.get("oauth_metadata") or {}
    headers = {"Authorization": f"Bearer {credentials['access_token']}", "Content-Type": "application/json"}
    if meta.get("developer_token"):
        headers["developer-token"] = str(meta["developer_token"])
    login = str(meta.get("login_customer_id") or "").replace("-", "")
    if login:
        headers["login-customer-id"] = login
    return headers


class GoogleAdsCreateCampaignTool(SocialMediaTool):
    """Create a Google Ads campaign."""

    name = "google_ads_create_campaign"
    platform = "google_ads"
    description = (
        "Create a new Google Ads campaign, paused. Supports Search, Display, Shopping "
        "and Performance Max campaign types. Video campaigns cannot be created through "
        "the Google Ads API."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {
                        "type": "string",
                        "description": "Name for the campaign"
                    },
                    "campaign_type": {
                        "type": "string",
                        "description": "Campaign type",
                        "enum": ["SEARCH", "DISPLAY", "SHOPPING", "PERFORMANCE_MAX"]
                    },
                    "contains_eu_political_advertising": {
                        "type": "boolean",
                        "description": "Whether the campaign has EU political advertising; Google requires "
                                       "the declaration on every new campaign (default false)"
                    },
                    "budget_amount_micros": {
                        "type": "integer",
                        "description": "Daily budget in micros (1 dollar = 1,000,000 micros)"
                    },
                    "bidding_strategy": {
                        "type": "string",
                        "description": "Bidding strategy",
                        "enum": ["MAXIMIZE_CLICKS", "MAXIMIZE_CONVERSIONS", "TARGET_CPA", "TARGET_ROAS", "MANUAL_CPC"]
                    },
                    "target_cpa_micros": {
                        "type": "integer",
                        "description": "Target CPA in micros (required for TARGET_CPA bidding)"
                    },
                    "target_roas": {
                        "type": "number",
                        "description": "Target ROAS as a ratio (e.g. 4.0 = 400% ROAS)"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Campaign start date (YYYY-MM-DD)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Campaign end date (YYYY-MM-DD, optional)"
                    },
                    "network_settings": {
                        "type": "object",
                        "description": "Network placement settings",
                        "properties": {
                            "target_google_search": {"type": "boolean"},
                            "target_search_network": {"type": "boolean"},
                            "target_content_network": {"type": "boolean"},
                        }
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Google Ads account to use"
                    },
                },
                "required": ["campaign_name", "campaign_type", "budget_amount_micros", "bidding_strategy"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        customer_id = _customer_id(credentials)

        if not customer_id:
            return {"error": "No customer_id in oauth_metadata. Configure Google Ads customer ID."}

        headers = _ads_headers(credentials)

        # The budget and the campaign are created in ONE googleAds:mutate, the
        # campaign naming the budget by a temporary resource name (-1): both
        # exist or neither does. Two separate mutates left an orphaned budget
        # in the account whenever the campaign failed (TL-49).
        budget_resource = f"customers/{customer_id}/campaignBudgets/-1"
        budget = {
            "resourceName": budget_resource,
            "name": f"{params['campaign_name']} Budget",
            "amountMicros": str(params["budget_amount_micros"]),
            "deliveryMethod": "STANDARD",
            "explicitlyShared": False,
        }

        # The campaign
        # The API reads and reports Video campaigns but cannot create them (YouTube
        # ads are Demand Gen campaigns, GADS-E3): VIDEO is not offered.
        campaign_type_map = {
            "SEARCH": "SEARCH",
            "DISPLAY": "DISPLAY",
            "SHOPPING": "SHOPPING",
            "PERFORMANCE_MAX": "PERFORMANCE_MAX",
        }
        if params["campaign_type"] not in campaign_type_map:
            return {"error": f"campaign_type {params['campaign_type']!r} cannot be created through the Google Ads "
                             f"API; use one of {', '.join(campaign_type_map)}"}

        campaign_data: Dict[str, Any] = {
            "name": params["campaign_name"],
            "advertisingChannelType": campaign_type_map[params["campaign_type"]],
            "status": "PAUSED",  # Always start paused for safety
            "campaignBudget": budget_resource,
            # Required on every new campaign since the EU political ads regulation.
            "containsEuPoliticalAdvertising": ("CONTAINS_EU_POLITICAL_ADVERTISING"
                                               if params.get("contains_eu_political_advertising")
                                               else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"),
        }

        # Bidding strategy
        bidding = params["bidding_strategy"]
        if bidding == "MAXIMIZE_CLICKS":
            campaign_data["maximizeClicks"] = {}
        elif bidding == "MAXIMIZE_CONVERSIONS":
            campaign_data["maximizeConversions"] = {}
        elif bidding == "TARGET_CPA":
            campaign_data["targetCpa"] = {"targetCpaMicros": str(params.get("target_cpa_micros", 0))}
        elif bidding == "TARGET_ROAS":
            campaign_data["targetRoas"] = {"targetRoas": params.get("target_roas", 1.0)}
        elif bidding == "MANUAL_CPC":
            campaign_data["manualCpc"] = {}  # Enhanced CPC was retired for Search and Display (March 2025)

        # Dates
        if params.get("start_date"):
            campaign_data["startDate"] = params["start_date"].replace("-", "")
        if params.get("end_date"):
            campaign_data["endDate"] = params["end_date"].replace("-", "")

        # Network settings
        network = params.get("network_settings", {})
        campaign_data["networkSettings"] = {
            "targetGoogleSearch": network.get("target_google_search", True),
            "targetSearchNetwork": network.get("target_search_network", True),
            "targetContentNetwork": network.get("target_content_network", False),
        }

        resp = await self._api_request(
            "POST",
            f"{_api_base()}/customers/{customer_id}/googleAds:mutate",
            headers=headers,
            json_body={"mutateOperations": [
                {"campaignBudgetOperation": {"create": budget}},
                {"campaignOperation": {"create": campaign_data}},
            ]},
        )
        responses = resp.json().get("mutateOperationResponses", [])
        campaign = next((r.get("campaignResult", {}) for r in responses if "campaignResult" in r), {})
        created_budget = next((r.get("campaignBudgetResult", {}) for r in responses if "campaignBudgetResult" in r), {})
        return {
            "success": True,
            "campaign_resource": campaign.get("resourceName", ""),
            "budget_resource": created_budget.get("resourceName", ""),
            "campaign_name": params["campaign_name"],
            "status": "PAUSED",
            "message": "Campaign created (paused). Enable when ready.",
        }


class GoogleAdsReportTool(SocialMediaTool):
    """Run a GAQL reporting query against Google Ads."""

    name = "google_ads_report"
    platform = "google_ads"
    description = (
        "Run a Google Ads Query Language (GAQL) query to fetch campaign performance data. "
        "Returns metrics like impressions, clicks, cost, conversions, and ROAS."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "GAQL query string. Example: "
                            "'SELECT campaign.name, metrics.impressions, metrics.clicks, metrics.cost_micros "
                            "FROM campaign WHERE segments.date DURING LAST_30_DAYS ORDER BY metrics.cost_micros DESC'"
                        )
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Google Ads account to use"
                    },
                },
                "required": ["query"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        customer_id = _customer_id(credentials)

        if not customer_id:
            return {"error": "No customer_id in oauth_metadata."}

        headers = _ads_headers(credentials)

        resp = await self._api_request(
            "POST",
            f"{_api_base()}/customers/{customer_id}/googleAds:searchStream",
            headers=headers,
            json_body={"query": params["query"]},
        )
        data = resp.json()

        # Parse streaming response (list of batches)
        results = []
        if isinstance(data, list):
            for batch in data:
                results.extend(batch.get("results", []))
        elif isinstance(data, dict):
            results = data.get("results", [])

        # Limit results for LLM context
        return {
            "query": params["query"],
            "result_count": len(results),
            "results": results[:50],  # Cap at 50 rows
        }


class GoogleAdsManageKeywordsTool(SocialMediaTool):
    """Manage keywords in Google Ads ad groups."""

    name = "google_ads_manage_keywords"
    platform = "google_ads"
    description = (
        "Add, remove, or update keywords in a Google Ads ad group. "
        "Supports keyword match types: EXACT, PHRASE, BROAD."
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
                        "description": "Action: add, remove, update_bid, pause, enable",
                        "enum": ["add", "remove", "update_bid", "pause", "enable"]
                    },
                    "ad_group_resource": {
                        "type": "string",
                        "description": "Ad group resource name (e.g. customers/123/adGroups/456)"
                    },
                    "keywords": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "match_type": {"type": "string", "enum": ["EXACT", "PHRASE", "BROAD"]},
                                "cpc_bid_micros": {"type": "integer"},
                            }
                        },
                        "description": "Keywords to add (required for 'add' action)"
                    },
                    "criterion_resource": {
                        "type": "string",
                        "description": "Criterion resource name (required for remove/update_bid/pause/enable)"
                    },
                    "new_bid_micros": {
                        "type": "integer",
                        "description": "New CPC bid in micros (for update_bid action)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Google Ads account to use"
                    },
                },
                "required": ["action", "ad_group_resource"],
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        customer_id = _customer_id(credentials)

        if not customer_id:
            return {"error": "No customer_id in oauth_metadata."}

        headers = _ads_headers(credentials)

        action = params["action"]
        ad_group = params["ad_group_resource"]

        if action == "add":
            keywords = params.get("keywords", [])
            if not keywords:
                return {"error": "keywords list is required for 'add' action"}

            operations = []
            for kw in keywords:
                operations.append({
                    "create": {
                        "adGroup": ad_group,
                        "keyword": {
                            "text": kw["text"],
                            "matchType": kw.get("match_type", "BROAD"),
                        },
                        "cpcBidMicros": str(kw.get("cpc_bid_micros", 0)) if kw.get("cpc_bid_micros") else None,
                        "status": "ENABLED",
                    }
                })

            resp = await self._api_request(
                "POST",
                f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                headers=headers,
                json_body={"operations": operations},
            )
            results = resp.json().get("results", [])
            return {
                "action": "add",
                "success": True,
                "keywords_added": len(results),
                "resources": [r.get("resourceName") for r in results],
            }

        elif action == "remove":
            criterion = params.get("criterion_resource", "")
            if not criterion:
                return {"error": "criterion_resource is required for 'remove' action"}

            resp = await self._api_request(
                "POST",
                f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                headers=headers,
                json_body={"operations": [{"remove": criterion}]},
            )
            return {"action": "remove", "success": True, "removed": criterion}

        elif action in ("pause", "enable"):
            criterion = params.get("criterion_resource", "")
            new_status = "PAUSED" if action == "pause" else "ENABLED"
            resp = await self._api_request(
                "POST",
                f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                headers=headers,
                json_body={"operations": [{"update": {"resourceName": criterion, "status": new_status}, "updateMask": "status"}]},
            )
            return {"action": action, "success": True, "criterion": criterion, "new_status": new_status}

        elif action == "update_bid":
            criterion = params.get("criterion_resource", "")
            new_bid = params.get("new_bid_micros", 0)
            resp = await self._api_request(
                "POST",
                f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                headers=headers,
                json_body={"operations": [{"update": {"resourceName": criterion, "cpcBidMicros": str(new_bid)}, "updateMask": "cpcBidMicros"}]},
            )
            return {"action": "update_bid", "success": True, "criterion": criterion, "new_bid_micros": new_bid}

        return {"error": f"Unknown action: {action}"}


class GoogleAdsGetAdGroupsTool(SocialMediaTool):
    """List ad groups and their settings for a Google Ads campaign."""

    name = "google_ads_get_ad_groups"
    platform = "google_ads"
    description = (
        "List ad groups in a Google Ads campaign with their settings, "
        "status, and key metrics summary."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_resource": {
                        "type": "string",
                        "description": "Campaign resource name (e.g. customers/123/campaigns/456). If not provided, lists all ad groups."
                    },
                    "include_metrics": {
                        "type": "boolean",
                        "description": "Include performance metrics (last 30 days). Default: true"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: specific Google Ads account to use"
                    },
                },
            },
        }

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        customer_id = _customer_id(credentials)

        if not customer_id:
            return {"error": "No customer_id in oauth_metadata."}

        headers = _ads_headers(credentials)

        include_metrics = params.get("include_metrics", True)
        campaign_resource = params.get("campaign_resource")

        # Build GAQL query
        select_fields = [
            "ad_group.id", "ad_group.name", "ad_group.status",
            "ad_group.type", "campaign.name",
        ]
        if include_metrics:
            select_fields.extend([
                "metrics.impressions", "metrics.clicks",
                "metrics.cost_micros", "metrics.conversions",
            ])

        query = f"SELECT {', '.join(select_fields)} FROM ad_group"
        conditions = []
        if campaign_resource:
            conditions.append(f"campaign.resource_name = '{campaign_resource}'")
        if include_metrics:
            conditions.append("segments.date DURING LAST_30_DAYS")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ad_group.name ASC LIMIT 100"

        resp = await self._api_request(
            "POST",
            f"{_api_base()}/customers/{customer_id}/googleAds:searchStream",
            headers=headers,
            json_body={"query": query},
        )
        data = resp.json()

        results = []
        if isinstance(data, list):
            for batch in data:
                results.extend(batch.get("results", []))
        elif isinstance(data, dict):
            results = data.get("results", [])

        return {
            "ad_group_count": len(results),
            "ad_groups": results[:50],
        }
