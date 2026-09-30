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
  4. ``Decimal('0')``, with a one-time warning per process.

A registry price is per ``cost_unit``: one call is one unit of a per-call SKU
and a thousandth of a "per 1000 …" SKU (``unit_divisor``, shared with
``UsageService``; BC-10). Every non-zero charge is written as one attributed
``usage_logs`` row — with its SKU when it came from the registry, without one
for a fixed cost (BC-07).
"""
from __future__ import annotations

import logging
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


_MISSING_COST_WARNED: set[str] = set()


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

    def __init__(self, db: Any, company_id: UUID):
        self.db = db
        self.company_id = company_id
        # Per-instance cache. Key: tool_id. Value: (Decimal, source, sku_id).
        self._cache: dict[str, tuple[Decimal, str, Optional[UUID]]] = {}

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
    ) -> ToolChargeResult:
        """Price one call and add its ``usage_logs`` row to the session.

        Does not touch ``run.total_cost_usd``: the caller adds the amount
        atomically (``StepExecutorService._bump_run_cost``), and its commit
        persists the row with it.
        """
        amount, source, sku_id = await self.resolve(tool_id)
        if amount <= 0:
            return ToolChargeResult(amount=Decimal("0"), source=source, sku_id=sku_id)
        from src.ai.services.cost_attribution import CostLedger
        await CostLedger(self.db).add(
            run_id=getattr(run, "id", None),
            company_id=getattr(run, "company_id", None) or self.company_id,
            amount=amount,
            attribution=attribution,
            sku_id=sku_id,
            raw_quantity=1.0,
            latency_ms=latency_ms,
            log_metadata={"tool": tool_id, "cost_source": source},
        )
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
        from src.config.models import IntegrationRegistry as _IR
        skus = [tool_id, *TOOL_SKU_MAP.get(tool_id, [])]
        return (await self.db.execute(
            select(_IR).where(
                _IR.company_id == company_id,
                or_(*(_IR.service_sku == sku for sku in skus)),
                _IR.status == "active",
                _IR.internal_cost.isnot(None),
                _IR.service_category != "LLM",
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

        if tool_id not in _MISSING_COST_WARNED:
            logger.warning(
                "ToolCostResolver: no cost entry for tool %r — defaulting to $0",
                tool_id,
            )
            _MISSING_COST_WARNED.add(tool_id)
        return (Decimal("0"), "missing", None)
