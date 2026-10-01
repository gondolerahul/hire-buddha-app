import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.ai.models import UsageLog
from src.config.models import IntegrationRegistry
import logging

logger = logging.getLogger(__name__)


async def app_company_id(db: AsyncSession) -> Optional[UUID]:
    """The platform (APP) company, which owns the cost-bearing SKUs."""
    from src.auth.models import Company
    result = await db.execute(select(Company.id).where(Company.type == "APP").limit(1))
    return result.scalar_one_or_none()


_UNIT_NOUNS: dict[str, str] = {
    "token": "token", "tokens": "token",
    "character": "character", "characters": "character", "char": "character", "chars": "character",
    "call": "call", "calls": "call", "request": "call", "requests": "call", "flat fee": "call",
    "second": "second", "seconds": "second", "sec": "second", "secs": "second",
    "minute": "minute", "minutes": "minute", "min": "minute", "mins": "minute",
    "image": "image", "images": "image", "video": "video", "videos": "video",
    "query": "query", "queries": "query", "search": "query", "searches": "query",
    "page": "page", "pages": "page", "email": "email", "emails": "email",
    "message": "message", "messages": "message",
    "transaction pct": "transaction pct",
}
_SCALE = {"": Decimal(1), "k": Decimal(1000), "m": Decimal(1_000_000),
          "thousand": Decimal(1000), "million": Decimal(1_000_000)}
_UNIT_RE = re.compile(
    r"^(?:per\s+)?(?:(?P<num>\d+(?:\.\d+)?)?\s*(?P<scale>k|m|thousand|million)?\s+)?(?P<noun>[a-z ]+?)$"
)


@dataclass(frozen=True)
class CostUnit:
    """A parsed ``cost_unit``: the price is for ``quantity`` of ``noun``."""
    quantity: Decimal
    noun: str


def parse_cost_unit(cost_unit: Optional[str]) -> CostUnit:
    """Parse ``per_1k_tokens``, ``per 1M tokens``, ``1M Tokens``,
    ``per_million_tokens``, ``per 1000 characters``, ``per_minute``,
    ``second`` … Separators (``_``, ``-``, spaces) and case do not matter.
    Raises ``ValueError`` for anything else: a pricing field that silently
    defaulted to "per one" over-billed 1000× or 1,000,000× (LP-01)."""
    text = re.sub(r"[_\-\s]+", " ", (cost_unit or "").strip().lower())
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = re.sub(r"(?<=\d)(k|m)\b", r" \1", text)  # "1k tokens" -> "1 k tokens"
    match = _UNIT_RE.match(text)
    noun = _UNIT_NOUNS.get(match.group("noun").strip()) if match else None
    if not match or noun is None:
        raise ValueError(
            f"unknown cost_unit {cost_unit!r}: use e.g. 'per_1k_tokens', 'per_1m_tokens', "
            f"'per_minute', 'per_call' (nouns: {', '.join(sorted(set(_UNIT_NOUNS.values())))})"
        )
    num = Decimal(match.group("num")) if match.group("num") else Decimal(1)
    quantity = num * _SCALE[match.group("scale") or ""]
    if quantity <= 0:
        raise ValueError(f"cost_unit {cost_unit!r} prices zero units")
    return CostUnit(quantity=quantity, noun=noun)


def unit_divisor(cost_unit: Optional[str]) -> Decimal:
    """How many units ``internal_cost`` is quoted for: a price "per 1M tokens"
    is divided by 1,000,000 to price one token, "per 1000 …" by 1000.

    Registry writes reject an unknown unit; a row stored before that check is
    logged and priced per one unit, as it always was."""
    try:
        return parse_cost_unit(cost_unit).quantity
    except ValueError:
        logger.error("Unknown cost_unit %r; pricing per one unit. Fix the registry row.", cost_unit)
        return Decimal(1)


class UsageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_app_company_id(self) -> Optional[UUID]:
        """Get the ID of the platform (APP) company.

        Cost-bearing services (AI models, telephony, SERP API, etc.) are
        always registered at the platform level under the APP company.
        This helper enables the fallback lookup for cost calculation.
        """
        return await app_company_id(self.db)

    async def log_usage(
        self,
        company_id: UUID,
        service_sku: str,
        raw_quantity: float,
        execution_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
        attribution: Optional[str] = None,
    ) -> UsageLog:
        """
        Logs usage for a specific SKU and company.
        Calculates cost based on the internal_cost in IntegrationRegistry.

        Cost-bearing services (AI models, telephony, etc.) are owned by the
        APP company (platform-level).  If no company-specific SKU entry is
        found, we fall back to the platform-level entry for cost calculation.
        """
        # 1. Try company-specific SKU
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.service_sku == service_sku,
                IntegrationRegistry.status == "active"
            )
        )
        registry_entry = result.scalar_one_or_none()
        
        # 2. Platform-level fallback: AI models, telephony, etc. are
        #    owned by the APP company and should be used for cost
        #    calculation across all tenants.
        if not registry_entry:
            app_company_id = await self._get_app_company_id()
            if app_company_id and app_company_id != company_id:
                result = await self.db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == app_company_id,
                        IntegrationRegistry.service_sku == service_sku,
                        IntegrationRegistry.status == "active"
                    )
                )
                registry_entry = result.scalar_one_or_none()
                if registry_entry:
                    logger.info(
                        f"Using platform-level SKU '{service_sku}' for cost calculation "
                        f"(company {company_id} has no company-specific entry)"
                    )

        if not registry_entry:
            # No SKU found at company or platform level
            logger.warning(
                f"No active registry entry found for SKU '{service_sku}' "
                f"(checked company {company_id} and platform)"
            )
            return None

        # Calculate cost
        # registry_entry.internal_cost is Decimal(18,6)
        # raw_quantity is float (e.g. number of tokens)
        
        # Support unit-based costing (e.g., 1M Tokens, per_million_tokens)
        calculated_cost = (
            registry_entry.internal_cost * Decimal(str(raw_quantity))
        ) / unit_divisor(registry_entry.cost_unit)

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

        usage_log = UsageLog(
            company_id=company_id,
            run_id=execution_id,
            sku_id=registry_entry.id,
            raw_quantity=Decimal(str(raw_quantity)),
            calculated_cost=calculated_cost,
            log_metadata=metadata,
            attribution=clean_attribution,
        )
        
        self.db.add(usage_log)
        await self.db.commit()
        await self.db.refresh(usage_log)
        return usage_log
