"""
ai.governance.tool_cost_resolver — the one price lookup for tool calls (BC-11).

Every tool charge goes through :meth:`ToolCostResolver.charge`: both tool
paths in ``step_executor`` (the direct TOOL_CALL step and the REACT function
calls) call ``StepExecutorService._charge_tool``, which calls it. Before
BC-11 each path carried its own hand-copied price tables and this module —
built to replace them — had no callers.

Lookup, first hit wins:

  0. for ``image_generation``, the company's ``billing_config.base_cost_image_gen``
     when set — the per-image override on the Billing Settings page (BC-13)
  1. the company's ownactive ``integration_registry`` row for the tool —
     ``service_sku == tool_id`` or one of :data:`TOOL_SKU_MAP[tool_id]`
  2. the platform's (APP company's) row for it — cost-bearing services are
     registered once, at platform level, as the LLM path already assumed
     (BC-10: tenants without their own row were charged nothing)
  3. :data:`TOOL_FIXED_COST[tool_id]` (e.g. image_generation = $0.04)
  4. :data:`FREE_TOOLS` (or a tenant tool's ``free_reason``): $0, on purpose
  5. otherwise the tool is **unpriced**: $0, and every call writes a $0
     ``usage_logs`` row marked ``cost_source: missing`` plus a
     ``tool.cost.missing`` event (GH-05). It used to warn once per process,
     so a tool shipped without a price was free, permanently and quietly.
     ``tests/unit/test_tool_prices.py`` fails on a registered tool that is
     none of 1–4.

A registry price is per ``cost_unit``: one call is one unit of a per-call SKU
and a thousandth of a "per 1000 …" SKU (``unit_divisor``, shared with
``UsageService``; BC-10). Every non-zero charge is written as one attributed
``usage_logs`` row — with its SKU when it came from the registry, without one
for a fixed cost (BC-07).
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import or_, select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The price tables — the only ones (the planner's cost_estimator predicts
# costs from telemetry; for fixed-cost tools it starts from these).
# ---------------------------------------------------------------------------


TOOL_SKU_MAP: dict[str, list[str]] = {
    "web_search":       ["serp-api-key"],
    "batch_web_search": ["serp-api-key"],
    "scraper_tool":     ["firecrawl-api", "firecrawl"],
    "headless_browser": ["headless-browser"],
    "pdf_generator":    ["pdf-generator"],
    "image_generation": ["imagen-4.0-generate-001"],
}


# Per-call costs for tools with no registry row.
TOOL_FIXED_COST: dict[str, Decimal] = {
    "image_generation": Decimal("0.04"),
    # video_generate carries the model cost; video_edit / video_add_sound are
    # compute-only and bill via the sandbox SKU, so they have no fixed cost here.
    "video_generate": Decimal("0.05"),
}


# Tools that cost nothing *here*, each with why (GH-05). A tool missing from
# this table, from TOOL_FIXED_COST and from TOOL_SKU_MAP is unpriced.
_LOCAL = "runs in-process; no paid service"
_TENANT = "uses the company's own connected account"
_MODEL = "its model calls are billed as LLM usage"
_SANDBOX = "metered as sandbox time"
_RUN = "starts a run, which is billed itself"
_AUTOMATION = "saves a schedule or a signal; the runs it starts are billed themselves"
_RECORDS = "reads or writes the business's own records (Data API); no paid service"
_CODE = "keeps code or opens a pull request; checks and builds are billed themselves"
FREE_TOOLS: dict[str, str] = {
    "agent_introspect": _LOCAL,
    "agent_reflect": _LOCAL,
    "archive_record": _RECORDS,
    "create_record": _RECORDS,
    "describe_schema": _RECORDS,
    "find_records": _RECORDS,
    "get_record": _RECORDS,
    "link_records": _RECORDS,
    "propose_schema_change": _RECORDS,
    "run_report": _RECORDS,
    "update_record": _RECORDS,
    "calculator": _LOCAL,
    "cancel_schedule": _LOCAL,
    "emit_event": _AUTOMATION,
    "crm_update_lead": _TENANT,
    "document_save": _LOCAL,
    "docx_tool": _LOCAL,
    "email_classify": _LOCAL,
    "email_draft": _LOCAL,
    "email_ingest": _TENANT,
    "email_send": _TENANT,
    "excel_tool": _LOCAL,
    "file_writer": _LOCAL,
    "get_current_datetime": _LOCAL,
    "list_schedules": _LOCAL,
    "google_calendar_create_event": _TENANT,
    "meta_entity_creator": _LOCAL,
    "meta_entity_executor": _RUN,
    "meta_platform_introspect": _LOCAL,
    "meta_registry_search": _LOCAL,
    "meta_schema_validator": _LOCAL,
    "meta_spec_critic": _MODEL,
    "pptx_tool": _LOCAL,
    "schedule_agent": _AUTOMATION,
    "sandbox_code": _SANDBOX,
    "social_api": _TENANT,
    "terminal": _SANDBOX,
    "tool_synthesis": _MODEL,
    "video_add_sound": _SANDBOX,
    "wait_for_event": _LOCAL,
    "save_code": _CODE,
    "propose_code_promotion": _CODE,
    "propose_app_change": _CODE,
    "video_edit": _SANDBOX,
    "whatsapp_send_tenant": _TENANT,
}

# One price cache per run (TX-I1, TL-33). A step's service — and with it its
# resolver — is rebuilt every iteration, so a per-instance cache looked every
# tool's price up again each time. Keyed by run id, least recently used first,
# bounded so finished runs fall out.
_RUN_CACHE_LIMIT = 512
_RUN_PRICE_CACHES: "OrderedDict[UUID, dict[str, tuple[Decimal, str, Optional[UUID]]]]" = OrderedDict()


def _run_price_cache(run_id: UUID) -> dict[str, tuple[Decimal, str, Optional[UUID]]]:
    cache = _RUN_PRICE_CACHES.get(run_id)
    if cache is None:
        cache = _RUN_PRICE_CACHES[run_id] = {}
        while len(_RUN_PRICE_CACHES) > _RUN_CACHE_LIMIT:
            _RUN_PRICE_CACHES.popitem(last=False)
    else:
        _RUN_PRICE_CACHES.move_to_end(run_id)
    return cache


__all__ = [
    "TOOL_SKU_MAP",
    "TOOL_FIXED_COST",
    "ToolCostResolver",
    "ToolChargeResult",
]


class ToolChargeResult:
    """Returned by :meth:`ToolCostResolver.charge` so callers can react."""

    __slots__ = ("amount", "source", "sku_id")

    def __init__(
        self,
        *,
        amount: Decimal,
        source: str,
        sku_id: Optional[UUID] = None,
    ):
        self.amount = amount
        self.source = source           # "config" | "registry" | "platform" | "fixed" | "missing"
        self.sku_id = sku_id

    def __bool__(self) -> bool:
        return self.amount > 0


class ToolCostResolver:
    """Single entry point for pricing and recording a tool call."""

    def __init__(self, db: Any, company_id: UUID, *, run_id: Optional[UUID] = None):
        self.db = db
        self.company_id = company_id
        # Key: tool_id. Value: (Decimal, source, sku_id). Shared by every
        # resolver of the same run, so a run prices each tool once — and
        # consistently, even if a price is edited mid-run (TX-I1).
        self._cache: dict[str, tuple[Decimal, str, Optional[UUID]]] = (
            _run_price_cache(run_id) if run_id is not None else {}
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(self, tool_id: str) -> tuple[Decimal, str, Optional[UUID]]:
        """Pure lookup: ``(amount, source, sku_id)`` for one call. Cached per tool_id."""
        if tool_id in self._cache:
            return self._cache[tool_id]
        result = await self._lookup_uncached(tool_id)
        self._cache[tool_id] = result
        return result

    async def charge(
        self,
        *,
        run: Any,
        tool_id: str,
        latency_ms: int = 0,
        attribution: str = "tool",
        units: float = 1.0,
    ) -> ToolChargeResult:
        """Price one call — ``units`` priced units of it — and add its
        ``usage_logs`` row to the session.

        Does not touch ``run.total_cost_usd``: a run's total is the sum of
        its usage rows (``governance.run_cost``, AK-02). The caller commits.
        """
        unit_price, source, sku_id = await self.resolve(tool_id)
        amount = unit_price * Decimal(str(units))
        missing = source == "missing"
        if amount <= 0 and not missing:
            return ToolChargeResult(amount=Decimal("0"), source=source, sku_id=sku_id)
        from src.ai.services.cost_attribution import CostLedger
        run_id = getattr(run, "id", None)
        company_id = getattr(run, "company_id", None) or self.company_id
        await CostLedger(self.db).add(
            run_id=run_id,
            company_id=company_id,
            amount=amount,
            attribution=attribution,
            sku_id=sku_id,
            raw_quantity=float(units),
            latency_ms=latency_ms,
            log_metadata={"tool": tool_id, "cost_source": source, "units": float(units)},
            unpriced=missing,
        )
        if missing:
            # Every call, not once per process (GH-05): the row and the
            # event make an unpriced tool visible in the run's costs.
            logger.warning("ToolCostResolver: tool %r has no price; charged $0", tool_id)
            from src.ai.core.agent_loop_sse import event_async
            await event_async("tool.cost.missing", tool=tool_id, run_id=str(run_id) if run_id else None,
                              company_id=str(company_id) if company_id else None)
        return ToolChargeResult(amount=amount, source=source, sku_id=sku_id)

    def invalidate(self, tool_id: Optional[str] = None) -> None:
        """Drop cached lookups. Pass ``tool_id`` to evict one entry."""
        if tool_id is None:
            self._cache.clear()
        else:
            self._cache.pop(tool_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _registry_row(self, tool_id: str, company_id: UUID) -> Any:
        from src.config.models import IntegrationRegistry as _IR, ServiceCategory
        skus = [tool_id, *TOOL_SKU_MAP.get(tool_id, [])]
        return (await self.db.execute(
            select(_IR).where(
                _IR.company_id == company_id,
                or_(*(_IR.service_sku == sku for sku in skus)),
                _IR.status == "active",
                _IR.internal_cost.isnot(None),
                _IR.service_category != ServiceCategory.LLM,
            ).limit(1)
        )).scalar_one_or_none()

    async def _lookup_uncached(
        self, tool_id: str,
    ) -> tuple[Decimal, str, Optional[UUID]]:
        from src.ai.usage_service import app_company_id, unit_divisor

        if tool_id == "image_generation":
            # The company's billing config may fix the per-image cost (BC-13).
            try:
                from src.billing.billing_service import BillingService
                config = await BillingService(self.db).get_billing_config(self.company_id)
                if config is not None and config.base_cost_image_gen is not None:
                    return (Decimal(str(config.base_cost_image_gen)), "config", None)
            except Exception as exc:                                        # pragma: no cover
                logger.debug(f"ToolCostResolver billing-config lookup failed: {exc}")

        try:
            row = await self._registry_row(tool_id, self.company_id)
            source = "registry"
            if row is None:
                platform = await app_company_id(self.db)
                if platform and platform != self.company_id:
                    row = await self._registry_row(tool_id, platform)
                    source = "platform"
        except Exception as exc:                                            # pragma: no cover
            logger.debug(f"ToolCostResolver registry lookup failed: {exc}")
            row = None

        if row is not None:
            per_call = Decimal(str(row.internal_cost)) / unit_divisor(row.cost_unit)
            return (per_call, source, row.id)

        fixed = TOOL_FIXED_COST.get(tool_id)
        if fixed is not None:
            return (Decimal(str(fixed)), "fixed", None)

        if tool_id in FREE_TOOLS or self._tenant_tool_is_free(tool_id):
            return (Decimal("0"), "free", None)
        return (Decimal("0"), "missing", None)

    def _tenant_tool_is_free(self, tool_id: str) -> bool:
        """A company's own tool (a synthesized one) that says why it is free."""
        from src.ai.tools.base import ToolRegistry
        tool = ToolRegistry._tenant_tools.get(str(self.company_id), {}).get(tool_id)
        return bool(getattr(tool, "free_reason", None))
