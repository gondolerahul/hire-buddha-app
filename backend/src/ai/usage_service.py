"""Pricing a metered quantity and writing its usage row.

A registry price is ``internal_cost`` USD per its unit (``cost_unit_code``, one
of ``src.billing.units.CostUnit``): ``cost = quantity × internal_cost ÷
per_quantity`` (Phase 15 T1-3). The free-text unit and its parser are gone
(REQ-CO-2). Each meter says which dimension it measured — tokens, characters,
seconds, vCPU-hours …; a row whose unit measures something else is a *unit
mismatch*, and a quantity with no row is *missing*: both are written as $0
rows marked ``cost_source`` and announced, so an unpriced or mispriced service
is visible instead of free (A6).
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Union
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.ai.orm import UsageLog
from src.billing.units import Dimension, price_usd, unit_spec
from src.config.models import IntegrationRegistry
import logging

logger = logging.getLogger(__name__)


async def app_company_id(db: AsyncSession) -> Optional[UUID]:
    """The platform (APP) company, which owns the cost-bearing SKUs."""
    from src.auth.platform import platform_company_id
    return await platform_company_id(db)


Dimensions = Union[Dimension, Iterable[Dimension]]


def _dimensions(dimension: Dimensions) -> list[Dimension]:
    return [dimension] if isinstance(dimension, Dimension) else list(dimension)


@dataclass(frozen=True)
class Price:
    """What a quantity costs at a registry row. ``cost_source``: ``registry``;
    ``unit_mismatch`` (the row's unit measures something else: $0); ``missing``
    (no row: $0)."""
    cost: Decimal
    cost_source: str

    @property
    def priced(self) -> bool:
        return self.cost_source == "registry"


def price_at(entry: Optional[IntegrationRegistry], quantity, dimension: Dimensions) -> Price:
    """``quantity`` (measured in ``dimension``) at ``entry``'s price — no rounding."""
    if entry is None:
        return Price(Decimal("0"), "missing")
    if unit_spec(entry.cost_unit_code).dimension not in _dimensions(dimension):
        return Price(Decimal("0"), "unit_mismatch")
    return Price(price_usd(Decimal(str(quantity)), Decimal(str(entry.internal_cost)), entry.cost_unit_code),
                 "registry")


async def flag_unpriced(price: Price, *, sku: str, company_id: Optional[UUID], run_id: Optional[UUID],
                        dimension: Dimensions) -> None:
    """Log and emit ``usage.cost.missing`` / ``usage.cost.unit_mismatch`` for a $0 charge that should cost."""
    if price.priced:
        return
    dims = [str(d) for d in _dimensions(dimension)]
    logger.warning("usage of %s charged $0: %s (metered in %s)", sku, price.cost_source, ", ".join(dims))
    try:
        from src.ai.core.agent_loop_sse import event_async
        await event_async(f"usage.cost.{price.cost_source}", sku=sku, dimension=dims,
                          run_id=str(run_id) if run_id else None,
                          company_id=str(company_id) if company_id else None)
    except Exception:                                                       # pragma: no cover
        logger.debug("usage.cost event failed", exc_info=True)


async def registry_entry(db: AsyncSession, company_id: UUID, service_sku: str) -> Optional[IntegrationRegistry]:
    """The company's active row for ``service_sku``, else the platform's.

    Cost-bearing services (models, telephony, …) are registered once, by the
    APP company; a company's own row comes first.
    """
    entry = (await db.execute(select(IntegrationRegistry).where(
        IntegrationRegistry.company_id == company_id,
        IntegrationRegistry.service_sku == service_sku,
        IntegrationRegistry.status == "active",
    ))).scalar_one_or_none()
    if entry is None:
        platform = await app_company_id(db)
        if platform and platform != company_id:
            entry = (await db.execute(select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == platform,
                IntegrationRegistry.service_sku == service_sku,
                IntegrationRegistry.status == "active",
            ))).scalar_one_or_none()
    return entry


class UsageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_usage(
        self,
        company_id: UUID,
        service_sku: str,
        raw_quantity: float,
        execution_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
        attribution: Optional[str] = None,
        *,
        dimension: Dimensions,
    ) -> UsageLog:
        """Price ``raw_quantity`` of ``service_sku`` and write its usage row (committed).

        ``dimension`` is what the meter measured (an LLM call: ``TOKEN``; an
        embedding: ``CHARACTER``; sandbox time: ``SECOND`` …); a meter whose
        quantity can be in more than one may pass several. With no row for the
        SKU, or a row priced in another dimension, the row is written at $0 with
        ``cost_source`` ``missing`` / ``unit_mismatch`` and an event — it used
        to write nothing, so an unpriced model was free and invisible (A6).
        """
        entry = await registry_entry(self.db, company_id, service_sku)
        price = price_at(entry, raw_quantity, dimension)

        # Validate attribution against the closed enum; unknown values
        # silently fall back to the column default "tool" rather than
        # losing the charge.
        clean_attribution = "tool"
        if attribution:
            try:
                from src.ai.services.cost_attribution import VALID_ATTRIBUTIONS
                if attribution in VALID_ATTRIBUTIONS:
                    clean_attribution = attribution
                else:
                    logger.warning(
                        "UsageService: unknown attribution %r — recording as 'tool'",
                        attribution,
                    )
            except Exception:
                clean_attribution = attribution

        log_metadata = dict(metadata or {})
        if not price.priced:
            log_metadata.update(cost_source=price.cost_source, sku=service_sku,
                                dimension=[str(d) for d in _dimensions(dimension)])
            if entry is not None:
                log_metadata["unit"] = entry.cost_unit_code

        usage_log = UsageLog(
            company_id=company_id,
            run_id=execution_id,
            sku_id=entry.id if entry is not None else None,
            raw_quantity=Decimal(str(raw_quantity)),
            calculated_cost=price.cost,
            log_metadata=log_metadata or None,
            attribution=clean_attribution,
        )
        # What the customer is billed for it (Phase 15 T3-3).
        from src.billing.rating import rate_row
        await rate_row(self.db, usage_log, sku=service_sku,
                       sku_category=entry.service_category if entry is not None else None)

        self.db.add(usage_log)
        await self.db.commit()
        await self.db.refresh(usage_log)
        await flag_unpriced(price, sku=service_sku, company_id=company_id, run_id=execution_id,
                            dimension=dimension)
        from src.ai.services.cost_attribution import emit_cost_charged
        await emit_cost_charged(
            run_id=execution_id, company_id=company_id, attribution=clean_attribution,
            sku=service_sku, amount=price.cost,
        )
        return usage_log
