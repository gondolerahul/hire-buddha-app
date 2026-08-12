"""
ai.governance.tool_cost_resolver — Phase 11 Track 8 single-source-of-truth
for tool cost lookup.

Before Track 8 the cost-lookup logic lived inline twice in
``step_executor.py`` (direct TOOL_CALL path + REACT AFC path) and once
again as fixed-cost fallbacks. This module collapses all three into
one cached service.

Lookup priority (first hit wins):

  1. ``IntegrationRegistry.service_sku == tool_id``
  2. ``IntegrationRegistry.service_sku`` in :data:`TOOL_SKU_MAP[tool_id]`
  3. :data:`TOOL_FIXED_COST[tool_id]` (e.g. image_generation = $0.04)
  4. ``Decimal('0')`` (with a one-time warning per process)

The resolver returns the charged amount so callers can update
``run.total_cost_usd`` and pass the same value into AgentLoop's
``Budget.consume(...)``. Every successful charge is recorded through
:class:`ai.services.cost_attribution.CostLedger` with the caller's
attribution tag.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import or_, select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lookup tables — moved here from step_executor.py
# ---------------------------------------------------------------------------


TOOL_SKU_MAP: dict[str, list[str]] = {
    "web_search":       ["serp-api-key"],
    "batch_web_search": ["serp-api-key"],
    "scraper_tool":     ["firecrawl-api", "firecrawl"],
    "headless_browser": ["headless-browser"],
    "pdf_generator":    ["pdf-generator"],
    "image_generation": ["imagen-4.0-generate-001"],
}


# Fallback per-call costs for tools that bill independently and have
# no entry in IntegrationRegistry.
TOOL_FIXED_COST: dict[str, Decimal] = {
    "image_generation": Decimal("0.04"),
    "video_generation": Decimal("0.05"),
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
        self.source = source           # "registry" | "fixed" | "missing"
        self.sku_id = sku_id

    def __bool__(self) -> bool:
        return self.amount > 0


class ToolCostResolver:
    """Single entry point for charging tool cost to a run."""

    def __init__(self, db: Any, company_id: UUID):
        self.db = db
        self.company_id = company_id
        # Per-process cache. Key: tool_id. Value: (Decimal, source, sku_id).
        self._cache: dict[str, tuple[Decimal, str, Optional[UUID]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(self, tool_id: str) -> tuple[Decimal, str, Optional[UUID]]:
        """Pure lookup: ``(amount, source, sku_id)``. Cached per tool_id."""
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
        """Resolve cost, mutate ``run.total_cost_usd``, write a ledger row.

        Returns a :class:`ToolChargeResult` regardless of whether a row
        was inserted (``source="missing"`` means we logged a warning
        and didn't charge).
        """
        amount, source, sku_id = await self.resolve(tool_id)
        if amount <= 0:
            return ToolChargeResult(amount=Decimal("0"), source=source, sku_id=sku_id)

        # Update the run's running total in-process (DB commit is the
        # caller's responsibility).
        try:
            existing = Decimal(str(run.total_cost_usd or 0))
        except Exception:                                                   # pragma: no cover
            existing = Decimal("0")
        run.total_cost_usd = existing + amount

        # Persist the attribution row.
        try:
            from src.ai.services.cost_attribution import CostLedger
            await CostLedger(self.db).add(
                run_id=getattr(run, "id", None),
                company_id=getattr(run, "company_id", self.company_id),
                amount=amount,
                attribution=attribution,
                sku_id=sku_id,
                raw_quantity=1.0,
                latency_ms=latency_ms,
                log_metadata={"tool": tool_id, "cost_source": source},
            )
        except Exception as exc:                                            # pragma: no cover
            logger.warning(f"CostLedger insert failed for tool {tool_id}: {exc}")
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

    async def _lookup_uncached(
        self, tool_id: str,
    ) -> tuple[Decimal, str, Optional[UUID]]:
        from src.config.models import IntegrationRegistry as _IR
        sku_matches = TOOL_SKU_MAP.get(tool_id, [])
        or_clauses = [
            _IR.service_sku == tool_id,
            _IR.service_category == "CUSTOM_API",
        ]
        for sku in sku_matches:
            or_clauses.append(_IR.service_sku == sku)

        try:
            row = (await self.db.execute(
                select(_IR).where(
                    _IR.company_id == self.company_id,
                    or_(*or_clauses),
                    _IR.status == "active",
                    _IR.internal_cost.isnot(None),
                    _IR.service_category != "LLM",
                ).limit(1)
            )).scalar_one_or_none()
        except Exception as exc:                                            # pragma: no cover
            logger.debug(f"ToolCostResolver registry lookup failed: {exc}")
            row = None

        if row is not None and row.internal_cost is not None:
            return (Decimal(str(row.internal_cost)), "registry", row.id)

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
