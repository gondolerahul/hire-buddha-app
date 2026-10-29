"""
Google Ads AI Agent Tools.

Provides tools for Google Ads campaign management via the Google Ads API:
- GoogleAdsCreateCampaignTool: Create campaigns
- GoogleAdsReportTool: Run GAQL reporting queries
- GoogleAdsManageKeywordsTool: Add/remove/update keywords
- GoogleAdsGetAdGroupsTool: List ad groups and settings
- GoogleAdsCreateDemandGenCampaignTool: YouTube video ads, as a Demand Gen campaign (GADS-E3)

Every request is counted against the developer token's daily operations, which
all businesses share (GADS-E6, ``quota``); Google's "not approved for production"
answer is a setup problem on HireBuddha's side, said so. A new campaign may not
take the account's planned monthly spend past the business's ceiling
(``ads_monthly_ceiling``, Settings → Limits).
"""
import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.ai.tools.social.base import SocialMediaTool

logger = logging.getLogger(__name__)

# Google's codes for a project or token not yet allowed on live accounts (GADS-E6).
SETUP_ERRORS = ("CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION", "DEVELOPER_TOKEN_NOT_APPROVED",
                "DEVELOPER_TOKEN_PROHIBITED")
SETUP_MESSAGE = ("HireBuddha's Google Ads access is not approved for live accounts yet: a setup step on "
                 "HireBuddha's side, not a problem with this account (test accounts still work).")
DAYS_PER_MONTH = 30.4   # Google's own: a month may spend up to the daily budget × 30.4
_BUDGETS_QUERY = ("SELECT campaign_budget.resource_name, campaign_budget.amount_micros FROM campaign "
                  "WHERE campaign.status IN ('ENABLED', 'PAUSED')")
# Country codes → geo target constants (2000 + ISO 3166 numeric); any other id may be given as a number.
COUNTRY_GEO = {"IN": 2356, "US": 2840, "GB": 2826, "AE": 2784, "SG": 2702, "AU": 2036, "CA": 2124}
LANGUAGE_IDS = {"en": 1000, "de": 1001, "fr": 1002, "es": 1003, "ar": 1019, "hi": 1023}
DATE_RANGES = ("TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "THIS_MONTH", "LAST_MONTH",
               "THIS_WEEK_MON_TODAY", "LAST_WEEK_MON_SUN")
# GADS-E5: the performance reports an agent runs by name; ``{range}`` is the date condition.
REPORTS = {
    "campaign_performance": (
        "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
        "metrics.impressions, metrics.clicks, metrics.ctr, metrics.average_cpc, metrics.cost_micros, "
        "metrics.conversions, metrics.conversions_value FROM campaign "
        "WHERE segments.date {range} AND campaign.status != 'REMOVED' ORDER BY metrics.cost_micros DESC"),
    "ad_group_performance": (
        "SELECT campaign.name, ad_group.id, ad_group.name, ad_group.status, metrics.impressions, metrics.clicks, "
        "metrics.ctr, metrics.cost_micros, metrics.conversions, metrics.conversions_value FROM ad_group "
        "WHERE segments.date {range} AND ad_group.status != 'REMOVED' ORDER BY metrics.cost_micros DESC"),
    "ad_performance": (
        "SELECT campaign.name, ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status, "
        "metrics.impressions, metrics.clicks, metrics.ctr, metrics.cost_micros, metrics.conversions FROM ad_group_ad "
        "WHERE segments.date {range} AND ad_group_ad.status != 'REMOVED' ORDER BY metrics.impressions DESC"),
    "video_performance": (
        "SELECT campaign.name, ad_group.name, video.id, video.title, metrics.impressions, "
        "metrics.video_trueview_views, metrics.video_trueview_view_rate, metrics.average_cpv, metrics.clicks, "
        "metrics.cost_micros, metrics.conversions FROM video WHERE segments.date {range} "
        "ORDER BY metrics.impressions DESC"),
    "demand_gen_performance": (
        "SELECT campaign.id, campaign.name, campaign.status, metrics.impressions, metrics.clicks, metrics.ctr, "
        "metrics.video_trueview_views, metrics.average_cpv, metrics.cost_micros, metrics.conversions, "
        "metrics.conversions_value FROM campaign WHERE campaign.advertising_channel_type = 'DEMAND_GEN' "
        "AND segments.date {range} ORDER BY metrics.cost_micros DESC"),
}


def _ads_error(resp: httpx.Response) -> Dict[str, Any]:
    """Google Ads' refusal, said plainly (GADS-E6)."""
    text = resp.text or ""
    if any(code in text for code in SETUP_ERRORS):
        return {"error": SETUP_MESSAGE, "code": "setup"}
    if resp.status_code == 429 or "RESOURCE_EXHAUSTED" in text:
        return {"error": "Google Ads is limiting HireBuddha's requests right now; try again in a few minutes.",
                "code": "rate_limited"}
    try:
        detail = resp.json()["error"]["details"][0]["errors"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        detail = text[:300]
    return {"error": f"Google Ads refused it: {detail}"}


async def _ads(tool: SocialMediaTool, context: Optional[Dict[str, Any]], url: str, *, headers: Dict[str, str],
               body: Dict[str, Any], operations: int = 1) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """One Google Ads request, counted against the shared daily operations:
    ``(json, None)``, or ``(None, error)``. 429s are retried by ``_api_request``."""
    from src.ai.tools.social import quota
    from src.common.config import settings

    refused = await quota.draw("google_ads_operations", (context or {}).get("company_id"), amount=operations,
                               total=settings.GOOGLE_ADS_OPERATIONS_PER_DAY,
                               share=settings.GOOGLE_ADS_OPERATIONS_PER_BUSINESS_PER_DAY,
                               what="Google Ads operations")
    if refused:
        return None, {"error": refused, "code": "daily_allowance"}
    try:
        resp = await tool._api_request("POST", url, headers=headers, json_body=body)
    except httpx.HTTPStatusError as exc:
        return None, _ads_error(exc.response)
    return resp.json(), None


def _rows(data: Any) -> List[Dict[str, Any]]:
    """A ``searchStream`` answer's rows (a list of batches, or one)."""
    if isinstance(data, list):
        return [row for batch in data for row in batch.get("results", [])]
    return list((data or {}).get("results", [])) if isinstance(data, dict) else []


def _money(value: Any) -> Any:
    """Every ``…Micros`` amount also in the account's currency units (GADS-E5)."""
    if isinstance(value, dict):
        out = {k: _money(v) for k, v in value.items()}
        for key, raw in value.items():
            if key.endswith("Micros") and isinstance(raw, (int, str)) and str(raw).lstrip("-").isdigit():
                out[key[:-len("Micros")] or "amount"] = int(raw) / 1_000_000
        return out
    if isinstance(value, list):
        return [_money(v) for v in value]
    return value


async def _over_ceiling(tool: SocialMediaTool, context: Optional[Dict[str, Any]], customer_id: str,
                        headers: Dict[str, str], new_daily_micros: int) -> Optional[Dict[str, Any]]:
    """GADS-E3: a new campaign may not take the account's planned monthly spend
    (every active and paused campaign's daily budget × 30.4) past the business's ceiling."""
    from src.automation.limits import limits_for

    company_id = (context or {}).get("company_id")
    ceiling = (await limits_for(company_id)).ads_monthly_ceiling if company_id else None
    if not ceiling:
        return {"error": "Set the Google Ads monthly ceiling (Settings → Limits) before an agent creates "
                         "campaigns: it caps what they may plan to spend.", "code": "no_ceiling"}
    data, error = await _ads(tool, context, f"{_api_base()}/customers/{customer_id}/googleAds:searchStream",
                             headers=headers, body={"query": _BUDGETS_QUERY})
    if error:
        return error
    budgets = {row.get("campaignBudget", {}).get("resourceName"): int(row.get("campaignBudget", {})
                                                                         .get("amountMicros") or 0)
               for row in _rows(data)}
    daily = (sum(budgets.values()) + new_daily_micros) / 1_000_000
    if daily * DAYS_PER_MONTH > ceiling:
        return {"error": f"With this campaign the account's daily budgets come to {daily:,.2f}, up to "
                         f"{daily * DAYS_PER_MONTH:,.0f} a month: over the business's ceiling of {ceiling:,} a month "
                         "(Settings → Limits). Lower the budget, or ask a person to raise the ceiling.",
                "code": "over_ceiling"}
    return None

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

        over = await _over_ceiling(self, context, customer_id, headers, int(params["budget_amount_micros"]))
        if over:
            return over
        data, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/googleAds:mutate",
                                 headers=headers, operations=2, body={"mutateOperations": [
                                     {"campaignBudgetOperation": {"create": budget}},
                                     {"campaignOperation": {"create": campaign_data}},
                                 ]})
        if error:
            return error
        responses = data.get("mutateOperationResponses", [])
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
        "Google Ads performance: a named report (campaign, ad group, ad, video or Demand Gen performance: "
        "impressions, views, view rate, CPV, clicks, cost, conversions, conversion value) over a date range, "
        "or your own GAQL query. Costs come in micros and in the account's currency."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "report": {
                        "type": "string",
                        "enum": sorted(REPORTS),
                        "description": "A named report (or give query)",
                    },
                    "date_range": {
                        "type": "string",
                        "enum": list(DATE_RANGES),
                        "description": "For a named report (default LAST_7_DAYS), or give start_date and end_date",
                    },
                    "start_date": {"type": "string", "description": "YYYY-MM-DD, with end_date"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD, with start_date"},
                    "query": {
                        "type": "string",
                        "description": (
                            "Your own GAQL query instead of a named report. Example: "
                            "'SELECT campaign.name, metrics.impressions, metrics.clicks, metrics.cost_micros "
                            "FROM campaign WHERE segments.date DURING LAST_30_DAYS ORDER BY metrics.cost_micros DESC'"
                        )
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
        report = params.get("report")
        if report:
            if report not in REPORTS:
                return {"error": f"no report {report!r}; one of {sorted(REPORTS)}"}
            if params.get("start_date") and params.get("end_date"):
                span = f"BETWEEN '{params['start_date']}' AND '{params['end_date']}'"
            else:
                preset = params.get("date_range") or "LAST_7_DAYS"
                if preset not in DATE_RANGES:
                    return {"error": f"date_range is one of {list(DATE_RANGES)}"}
                span = f"DURING {preset}"
            query = REPORTS[report].format(range=span)
        elif params.get("query"):
            query = str(params["query"])
        else:
            return {"error": "give a report name or a GAQL query"}

        url = f"{_api_base()}/customers/{customer_id}/googleAds:searchStream"
        data, error = await _ads(self, context, url, headers=headers, body={"query": query})
        if error:
            return error
        results = _rows(data)
        account, _ = await _ads(self, context, url, headers=headers,
                                body={"query": "SELECT customer.currency_code FROM customer LIMIT 1"})
        currency = next((r.get("customer", {}).get("currencyCode") for r in _rows(account)), None)

        # Limit results for LLM context
        return {
            "report": report,
            "query": query,
            "source": "Google Ads",     # each number is Google Ads'; one worked out from them is HireBuddha's
            "currency": currency,
            "result_count": len(results),
            "results": _money(results[:50]),  # Cap at 50 rows
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

            data, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                                     headers=headers, body={"operations": operations}, operations=len(operations))
            if error:
                return error
            results = data.get("results", [])
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

            _, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                                  headers=headers, body={"operations": [{"remove": criterion}]})
            if error:
                return error
            return {"action": "remove", "success": True, "removed": criterion}

        elif action in ("pause", "enable"):
            criterion = params.get("criterion_resource", "")
            new_status = "PAUSED" if action == "pause" else "ENABLED"
            _, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                                  headers=headers, body={"operations": [{"update": {
                                      "resourceName": criterion, "status": new_status}, "updateMask": "status"}]})
            if error:
                return error
            return {"action": action, "success": True, "criterion": criterion, "new_status": new_status}

        elif action == "update_bid":
            criterion = params.get("criterion_resource", "")
            new_bid = params.get("new_bid_micros", 0)
            _, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/adGroupCriteria:mutate",
                                  headers=headers, body={"operations": [{"update": {
                                      "resourceName": criterion, "cpcBidMicros": str(new_bid)},
                                      "updateMask": "cpcBidMicros"}]})
            if error:
                return error
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

        data, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/googleAds:searchStream",
                                 headers=headers, body={"query": query})
        if error:
            return error
        results = _rows(data)

        return {
            "ad_group_count": len(results),
            "ad_groups": _money(results[:50]),
        }


_CALLS_TO_ACTION = ("LEARN_MORE", "SHOP_NOW", "SIGN_UP", "SUBSCRIBE", "BOOK_NOW", "CONTACT_US", "DOWNLOAD",
                    "GET_QUOTE", "APPLY_NOW", "ORDER_NOW", "GET_OFFER", "WATCH_NOW", "VISIT_SITE")
# Demand Gen video responsive ad: Google's counts and lengths.
_TEXT_LIMITS = {"headlines": (1, 5, 40), "long_headlines": (1, 5, 90), "descriptions": (1, 5, 90)}
_MAX_LOGO_BYTES = 5 * 1024 * 1024


def _ids(values: List[Any], names: Dict[str, int], what: str) -> Tuple[List[int], Optional[str]]:
    """Codes or Google's numeric ids → ids; the first unknown one is the problem."""
    out: List[int] = []
    for value in values or []:
        text = str(value).strip()
        if text.isdigit():
            out.append(int(text))
        elif text.upper() in names:
            out.append(names[text.upper()])
        elif text.lower() in names:
            out.append(names[text.lower()])
        else:
            return [], f"{what} {text!r}: give a code ({', '.join(names)}) or Google's numeric id"
    return out, None


class GoogleAdsCreateDemandGenCampaignTool(SocialMediaTool):
    """A YouTube video ad as a Demand Gen campaign (GADS-E3): paused, for a person to enable."""

    name = "google_ads_create_demand_gen_campaign"
    platform = "google_ads"
    description = (
        "Create a paused Demand Gen campaign that shows a video ad on YouTube (and Google's other surfaces): "
        "its daily budget and bidding, locations and languages, one ad group, and a video responsive ad "
        "made from a YouTube video. A person enables it in Google Ads. The account's planned spend must "
        "stay within the business's monthly ceiling."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        texts = {"type": "array", "items": {"type": "string"}}
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                    "daily_budget_micros": {"type": "integer",
                                            "description": "Daily budget in micros of the account's currency"},
                    "bidding_strategy": {"type": "string", "enum": ["MAXIMIZE_CONVERSIONS", "TARGET_CPA"],
                                         "description": "Default MAXIMIZE_CONVERSIONS"},
                    "target_cpa_micros": {"type": "integer", "description": "For TARGET_CPA"},
                    "contains_eu_political_advertising": {"type": "boolean",
                                                          "description": "Google requires the answer"},
                    "locations": {**texts, "description": "Country codes (" + ", ".join(COUNTRY_GEO)
                                  + ") or geo target constant ids"},
                    "languages": {**texts, "description": "Language codes (" + ", ".join(LANGUAGE_IDS)
                                  + ") or language constant ids"},
                    "video_id": {"type": "string", "description": "The YouTube video's id (11 characters)"},
                    "final_url": {"type": "string", "description": "Where the ad leads (https)"},
                    "business_name": {"type": "string", "description": "At most 25 characters"},
                    "headlines": {**texts, "description": "1 to 5, each at most 40 characters"},
                    "long_headlines": {**texts, "description": "1 to 5, each at most 90 characters"},
                    "descriptions": {**texts, "description": "1 to 5, each at most 90 characters"},
                    "logo_image_url": {"type": "string", "description": "A square logo image (public https URL)"},
                    "call_to_action": {"type": "string", "enum": list(_CALLS_TO_ACTION)},
                    "account_name": {"type": "string", "description": "Optional: specific Google Ads account"},
                },
                "required": ["campaign_name", "daily_budget_micros", "contains_eu_political_advertising",
                             "video_id", "final_url", "business_name", "headlines", "long_headlines",
                             "descriptions", "logo_image_url"],
            },
        }

    @staticmethod
    def _check(params: Dict[str, Any]) -> Optional[str]:
        if not isinstance(params.get("contains_eu_political_advertising"), bool):
            return "contains_eu_political_advertising must be true or false: Google requires the answer"
        for field, (least, most, length) in _TEXT_LIMITS.items():
            items = params.get(field) or []
            if not least <= len(items) <= most:
                return f"{field}: {least} to {most} of them"
            long = [t for t in items if len(str(t)) > length]
            if long:
                return f"{field}: each at most {length} characters ({long[0]!r} is longer)"
        if not params.get("business_name") or len(str(params["business_name"])) > 25:
            return "business_name: 1 to 25 characters"
        if not str(params.get("final_url") or "").startswith("https://"):
            return "final_url must be an https address"
        if len(str(params.get("video_id") or "")) != 11:
            return "video_id is a YouTube video's 11-character id"
        if params.get("call_to_action") and params["call_to_action"] not in _CALLS_TO_ACTION:
            return f"call_to_action is one of {list(_CALLS_TO_ACTION)}"
        return None

    async def _execute(
        self, params: Dict[str, Any], credentials: Dict[str, Any], context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        customer_id = _customer_id(credentials)
        if not customer_id:
            return {"error": "No customer_id in oauth_metadata."}
        problem = self._check(params)
        if problem:
            return {"error": problem}
        locations, problem = _ids(params.get("locations") or [], COUNTRY_GEO, "location")
        if problem:
            return {"error": problem}
        languages, problem = _ids(params.get("languages") or [], LANGUAGE_IDS, "language")
        if problem:
            return {"error": problem}
        headers = _ads_headers(credentials)
        over = await _over_ceiling(self, context, customer_id, headers, int(params["daily_budget_micros"]))
        if over:
            return over
        try:
            logo, logo_type = await self._download(params["logo_image_url"], _MAX_LOGO_BYTES)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"could not fetch the logo: {exc}"}
        if not logo_type.startswith("image/"):
            return {"error": f"the logo is {logo_type}, not an image"}

        name = params["campaign_name"]
        base = f"customers/{customer_id}"
        budget, campaign, group = f"{base}/campaignBudgets/-1", f"{base}/campaigns/-2", f"{base}/adGroups/-3"
        video, logo_asset, cta = f"{base}/assets/-4", f"{base}/assets/-5", f"{base}/assets/-6"
        bidding: Dict[str, Any] = {"maximizeConversions": {}}
        if params.get("bidding_strategy") == "TARGET_CPA":
            if not params.get("target_cpa_micros"):
                return {"error": "target_cpa_micros is required for TARGET_CPA"}
            bidding = {"maximizeConversions": {"targetCpaMicros": str(params["target_cpa_micros"])}}
        eu = ("CONTAINS_EU_POLITICAL_ADVERTISING" if params["contains_eu_political_advertising"]
              else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING")
        # One mutate, in dependency order, with temporary ids: all of it exists or none (TL-49).
        operations: List[Dict[str, Any]] = [
            {"campaignBudgetOperation": {"create": {
                "resourceName": budget, "name": f"{name} Budget", "amountMicros": str(params["daily_budget_micros"]),
                "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
            {"campaignOperation": {"create": {
                "resourceName": campaign, "name": name, "status": "PAUSED", "advertisingChannelType": "DEMAND_GEN",
                "campaignBudget": budget, "containsEuPoliticalAdvertising": eu, **bidding}}},
        ]
        operations += [{"campaignCriterionOperation": {"create": {
            "campaign": campaign, "location": {"geoTargetConstant": f"geoTargetConstants/{g}"}}}} for g in locations]
        operations += [{"campaignCriterionOperation": {"create": {
            "campaign": campaign, "language": {"languageConstant": f"languageConstants/{lang}"}}}}
            for lang in languages]
        operations += [
            {"adGroupOperation": {"create": {"resourceName": group, "name": f"{name} ad group", "campaign": campaign,
                                             "status": "ENABLED"}}},
            {"assetOperation": {"create": {"resourceName": video, "name": f"{name} video",
                                           "youtubeVideoAsset": {"youtubeVideoId": params["video_id"]}}}},
            {"assetOperation": {"create": {"resourceName": logo_asset, "name": f"{name} logo",
                                           "imageAsset": {"data": base64.b64encode(logo).decode()}}}},
        ]
        ad: Dict[str, Any] = {
            "headlines": [{"text": t} for t in params["headlines"]],
            "longHeadlines": [{"text": t} for t in params["long_headlines"]],
            "descriptions": [{"text": t} for t in params["descriptions"]],
            "videos": [{"asset": video}],
            "logoImages": [{"asset": logo_asset}],
            "businessName": {"text": params["business_name"]},
        }
        if params.get("call_to_action"):
            operations.append({"assetOperation": {"create": {
                "resourceName": cta, "callToActionAsset": {"callToAction": params["call_to_action"]}}}})
            ad["callToActions"] = [{"asset": cta}]
        operations.append({"adGroupAdOperation": {"create": {
            "adGroup": group, "status": "ENABLED",
            "ad": {"name": f"{name} video ad", "finalUrls": [params["final_url"]], "demandGenVideoResponsiveAd": ad}}}})

        data, error = await _ads(self, context, f"{_api_base()}/customers/{customer_id}/googleAds:mutate",
                                 headers=headers, body={"mutateOperations": operations}, operations=len(operations))
        if error:
            return error
        responses = data.get("mutateOperationResponses", [])

        def made(kind: str) -> str:
            return next((r[kind].get("resourceName", "") for r in responses if kind in r), "")

        return {"success": True, "status": "PAUSED", "campaign_resource": made("campaignResult"),
                "ad_group_resource": made("adGroupResult"), "ad_resource": made("adGroupAdResult"),
                "message": "Demand Gen campaign created, paused, with its video ad. A person enables it in Google "
                           "Ads once Google's review is done."}
