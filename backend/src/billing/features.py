"""What a plan includes: the feature catalogue, entitlements and limits (Phase 15 T6-2, tech design §10.2).

Every feature and limit is a key of :data:`CATALOGUE`. A company's entitlement
to one is resolved

    its own override (``company_entitlement_overrides``, until it lapses)
    → its plan's (``plan_entitlements``; the plan is its live subscription's, else Pay-as-you-go)
    → the catalogue's default

At launch every feature is on for every plan and each limit is what the
platform allowed before (``LIVE_SESSIONS_PER_COMPANY``, ``RUNS_STARTED_PER_MINUTE``),
so nothing changes for anyone until staff restrict a plan (REQ-SB-3).

Enforcement: :func:`require_feature` on routes (403 ``feature_locked``),
:func:`check_feature` / :func:`limit_of` in code paths with no route (tools,
admission), ``GET /api/v1/me/entitlements`` for menus. The platform's own
company and its staff are never locked.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException

FEATURE, LIMIT = "feature", "limit"
STAFF_ROLES = frozenset({"app_admin", "app_user"})
CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class Spec:
    key: str
    group: str
    label: str
    kind: str = FEATURE
    fixed_default: Optional[int] = None          # for a limit, or a feature with a quantity (numbers, apps)
    limit_label: Optional[str] = None
    default_setting: Optional[str] = None        # the default is this ``Settings`` value, read when used

    @property
    def default_limit(self) -> Optional[int]:
        """The limit without a plan or override: a setting's value now (0 = none), else the fixed default."""
        if self.default_setting:
            from src.common.config import settings
            return int(getattr(settings, self.default_setting, 0) or 0) or None
        return self.fixed_default


def _f(key: str, group: str, label: str, limit_label: Optional[str] = None) -> Spec:
    return Spec(key, group, label, FEATURE, None, limit_label)


def _limits() -> list:
    return [
        Spec("limit.users", "Limits", "Users", LIMIT),
        Spec("limit.agents", "Limits", "Agents", LIMIT),
        Spec("limit.live_sessions", "Limits", "Live calls and sessions at once", LIMIT,
             default_setting="LIVE_SESSIONS_PER_COMPANY"),
        Spec("limit.runs_per_minute", "Limits", "Runs started a minute", LIMIT,
             default_setting="RUNS_STARTED_PER_MINUTE"),
        Spec("limit.sandbox_size", "Limits", "Sandbox size (vCPU)", LIMIT),
        Spec("limit.storage_gb", "Limits", "Storage (GB)", LIMIT),
    ]


_FEATURES = [
    _f("feature.agents.builder", "Agents", "Create and edit agents"),
    _f("feature.agents.process_level", "Agents", "Process level"),
    _f("feature.agents.loop_graph_levels", "Agents", "Department and business levels"),
    _f("feature.agents.templates", "Agents", "Templates"),
    _f("feature.agents.versions", "Agents", "Versions and test runs"),
    _f("feature.agents.hitl", "Agents", "Approval checkpoints"),
    _f("feature.agents.meta_agent", "Agents", "Agents that create agents"),
    _f("feature.agents.debate_critics", "Agents", "Debate and cross-model critics"),
    _f("feature.knowledge.base", "Knowledge", "Documents and knowledge base"),
    _f("feature.knowledge.cortex_explorer", "Knowledge", "Memory explorer"),
    _f("feature.automation.schedules", "Automation", "Schedules"),
    _f("feature.automation.triggers", "Automation", "Event triggers and waits"),
    _f("feature.automation.webhooks_inbound", "Automation", "Inbound webhooks"),
    _f("feature.automation.agent_schedules", "Automation", "Agents creating schedules"),
    _f("feature.voice.inbound", "Voice & messaging", "Inbound calls"),
    _f("feature.voice.outbound_campaigns", "Voice & messaging", "Campaigns and auto-dialer"),
    _f("feature.voice.mobile_dialer", "Voice & messaging", "Mobile dialer"),
    _f("feature.voice.browser_calls", "Voice & messaging", "Browser calls"),
    _f("feature.video.calls", "Voice & messaging", "Video calls"),
    _f("feature.messaging.whatsapp", "Voice & messaging", "WhatsApp"),
    _f("feature.messaging.email", "Voice & messaging", "E-mail"),
    _f("feature.messaging.social", "Voice & messaging", "Social posting"),
    _f("feature.phone_numbers", "Voice & messaging", "Phone numbers", "Numbers"),
    _f("feature.media.image", "Media", "Image generation"),
    _f("feature.media.video", "Media", "Video generation"),
    _f("feature.media.speech", "Media", "Speech generation"),
    _f("feature.media.music", "Media", "Music generation"),
    _f("feature.compute.sandbox", "Code & compute", "Code execution and terminal"),
    _f("feature.compute.browser", "Code & compute", "Headless browser"),
    _f("feature.compute.persistent_browser", "Code & compute", "Persistent browser profile"),
    _f("feature.code.lanes", "Code & compute", "Code, Git and pull requests"),
    _f("feature.compute.tool_synthesis", "Code & compute", "Agents writing tools"),
    _f("feature.records", "Business data", "Records"),
    _f("feature.records.data_api_keys", "Business data", "Data API keys"),
    _f("feature.records.public_api", "Business data", "Public API access"),
    _f("feature.apps.hosting", "Apps", "Hosted apps", "Apps"),
    _f("feature.apps.custom_domains", "Apps", "Custom domains"),
    _f("feature.connections.oauth", "Connections", "OAuth connectors"),
    _f("feature.connections.mcp", "Connections", "MCP servers"),
    _f("feature.reports.advanced", "Insight", "Advanced reports and exports"),
]

# The feature a tool needs (Phase 15 T6-2): checked once per call in ``ai.tool_executor._run``.
_SOCIAL = ("facebook_", "instagram_", "linkedin_", "reddit_", "tiktok_", "twitter_", "youtube_")
TOOL_FEATURES: Dict[str, str] = {
    "image_generation": "feature.media.image",
    "video_generate": "feature.media.video", "video_edit": "feature.media.video", "video_add_sound": "feature.media.video",
    "text_to_speech": "feature.media.speech",
    "music_generation": "feature.media.music",
    "sandbox_code": "feature.compute.sandbox", "terminal": "feature.compute.sandbox",
    "headless_browser": "feature.compute.browser",
    "tool_synthesis": "feature.compute.tool_synthesis",
    "email_send": "feature.messaging.email", "email_draft": "feature.messaging.email",
    "email_ingest": "feature.messaging.email", "email_classify": "feature.messaging.email",
    "social_api": "feature.messaging.social",
    "whatsapp_send_tenant": "feature.messaging.whatsapp",
    "schedule_agent": "feature.automation.agent_schedules", "emit_event": "feature.automation.agent_schedules",
    "meta_entity_creator": "feature.agents.meta_agent", "meta_entity_executor": "feature.agents.meta_agent",
    "create_record": "feature.records", "update_record": "feature.records", "archive_record": "feature.records",
    "find_records": "feature.records", "get_record": "feature.records", "link_records": "feature.records",
}


def feature_for_tool(name: str) -> Optional[str]:
    key = TOOL_FEATURES.get(name)
    if key is None and name.startswith(_SOCIAL):
        key = "feature.messaging.social"
    return key


CATALOGUE: Dict[str, Spec] = {}


def catalogue() -> Dict[str, Spec]:
    if not CATALOGUE:
        for spec in _FEATURES + _limits():
            CATALOGUE[spec.key] = spec
    return CATALOGUE


class UnknownFeature(KeyError):
    pass


def spec_for(key: str) -> Spec:
    try:
        return catalogue()[key]
    except KeyError:
        raise UnknownFeature(key) from None


@dataclass(frozen=True)
class Entitlement:
    key: str
    enabled: bool
    limit: Optional[int]
    source: str                   # override | plan | default


_cache: Dict[str, Tuple[Dict[str, Entitlement], float]] = {}


def forget(company_id: Any = None) -> None:
    if company_id is None:
        _cache.clear()
    else:
        _cache.pop(str(company_id), None)


async def _is_platform(db: Any, company_id: UUID) -> bool:
    from src.auth.platform import platform_company_id

    try:
        return str(await platform_company_id(db)) == str(company_id)
    except Exception:  # noqa: BLE001
        return False


async def entitlements_for(db: Any, company_id: UUID) -> Dict[str, Entitlement]:
    """Every key's entitlement for the company (three queries; cached half a minute)."""
    from sqlalchemy import select

    from src.billing.billing_models import CompanyEntitlementOverride, PlanEntitlement
    from src.billing.plans import plan_id_of

    from src.billing import rollout

    specs = catalogue()
    if not await rollout.enabled(db, rollout.ENTITLEMENTS):          # T10-3: plans do not gate yet
        return {k: Entitlement(k, True, None, "rollout") for k in specs}
    key = str(company_id)
    hit = _cache.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    out = {k: Entitlement(k, True, s.default_limit, "default") for k, s in specs.items()}
    if not await _is_platform(db, company_id):
        plan_id = await plan_id_of(db, company_id)
        if plan_id is not None:
            for row in (await db.execute(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan_id))
                        ).scalars().all():
                if row.feature_key in specs:
                    out[row.feature_key] = Entitlement(row.feature_key, row.enabled, row.limit_value, "plan")
        now = datetime.utcnow()
        for row in (await db.execute(select(CompanyEntitlementOverride).where(
                CompanyEntitlementOverride.company_id == company_id))).scalars().all():
            if row.feature_key in specs and (row.until is None or row.until > now):
                out[row.feature_key] = Entitlement(row.feature_key, row.enabled, row.limit_value, "override")
    _cache[key] = (out, time.monotonic() + CACHE_SECONDS)
    return out


async def entitlement(db: Any, company_id: UUID, key: str) -> Entitlement:
    spec_for(key)
    return (await entitlements_for(db, company_id))[key]


def locked_message(key: str) -> str:
    spec = spec_for(key)
    return f"{spec.label} is not included in your plan. Upgrade the plan to use it."


async def check_feature(db: Any, company_id: Optional[UUID], key: str) -> Optional[str]:
    """Why the company may not use ``key``, or ``None``."""
    if company_id is None:
        return None
    return None if (await entitlement(db, company_id, key)).enabled else locked_message(key)


async def limit_of(db: Any, company_id: UUID, key: str) -> Optional[int]:
    """The company's limit for ``key`` (``None``: no limit)."""
    return (await entitlement(db, company_id, key)).limit


async def check_limit(db: Any, company_id: UUID, key: str, in_use: int) -> Optional[str]:
    """Why one more is refused (``in_use`` already at the limit), or ``None``."""
    ent = await entitlement(db, company_id, key)
    if not ent.enabled:
        return locked_message(key)
    if ent.limit is not None and in_use >= ent.limit:
        spec = spec_for(key)
        noun = (spec.limit_label or spec.label).lower()
        return f"Your plan allows {ent.limit} {noun}; you have {in_use}. Upgrade the plan for more."
    return None


def feature_locked(key: str, detail: Optional[str] = None) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": "feature_locked", "feature": key,
                                                  "message": detail or locked_message(key)})


def require_feature(key: str) -> Callable[..., Any]:
    """A route dependency: 403 ``feature_locked`` unless the caller's company has ``key``."""
    spec_for(key)                                     # a typo fails at import, not at request time
    from src.auth.router import get_current_user
    from src.common.database import get_db

    async def _dependency(user: Any = Depends(get_current_user), db: Any = Depends(get_db)) -> Any:
        role = str(getattr(getattr(user, "role", None), "value", getattr(user, "role", "")) or "")
        if role in STAFF_ROLES:
            return user
        refusal = await check_feature(db, getattr(user, "company_id", None), key)
        if refusal:
            raise feature_locked(key, refusal)
        return user

    _dependency.__name__ = f"require_{key.replace('.', '_')}"
    return _dependency
