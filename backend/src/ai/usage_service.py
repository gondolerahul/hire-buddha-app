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

class UsageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_app_company_id(self) -> Optional[UUID]:
        """Get the ID of the platform (APP) company.
        
        Cost-bearing services (AI models, telephony, SERP API, etc.) are
        always registered at the platform level under the APP company.
        This helper enables the fallback lookup for cost calculation.
        """
        from src.auth.models import Company
        result = await self.db.execute(
            select(Company.id).where(Company.type == "APP").limit(1)
        )
        return result.scalar_one_or_none()

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
        divisor = Decimal("1.0")
        if registry_entry.cost_unit:
            unit_lower = registry_entry.cost_unit.lower()
            if "1m token" in unit_lower or "per_million" in unit_lower or "million" in unit_lower:
                divisor = Decimal("1000000.0")
            elif "1k token" in unit_lower:
                divisor = Decimal("1000.0")
            elif "1000 char" in unit_lower:
                divisor = Decimal("1000.0")
        
        calculated_cost = (registry_entry.internal_cost * Decimal(str(raw_quantity))) / divisor

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
