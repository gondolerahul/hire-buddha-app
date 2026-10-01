"""
Voice Usage Logger for tracking call costs and LLM usage.

Logs:
- Call duration and telephony costs
- Gemini API usage (audio input/output)
- Updates voice_sessions.total_cost_usd
- Creates entries in usage_logs table
"""
import math
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.config.models import IntegrationRegistry
from src.ai.models import UsageLog
from src.voice.models import VoiceSession

logger = logging.getLogger(__name__)


def billed_minutes(duration_seconds: int) -> Decimal:
    """Telephony is billed per started minute: 125 s is 3 minutes. The one
    rounding rule — the usage log and the billing event both use it (BC-12)."""
    return Decimal(str(math.ceil(max(duration_seconds, 0) / 60.0)))


@dataclass
class VoiceUsage:
    """A call's logged cost: the total, and its telephony part (BC-13)."""
    total_cost: Decimal
    telephony_cost: Decimal
    telephony_minutes: Decimal


class VoiceUsageLogger:
    """
    Logs usage and calculates costs for voice calls.
    
    Tracks:
    - Telephony costs (per minute based on provider SKU)
    - LLM costs (Gemini audio input/output)
    """
    
    # SKU mappings for different providers
    TELEPHONY_SKU_MAP = {
        "tata_tele": "tata-tele-voice-in-out",
        "twilio": "in-out"
    }
    
    # These will be resolved dynamically from the speech_to_speech task default
    # Fallbacks only used if dynamic resolution fails
    GEMINI_INPUT_SKU = "gemini-3.1-flash-live-preview-in"
    GEMINI_OUTPUT_SKU = "gemini-3.1-flash-live-preview-out"
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def log_voice_session_usage(
        self,
        session_id: UUID,
        company_id: UUID,
        provider: str,
        duration_seconds: int,
        audio_input_seconds: Optional[int] = None,
        audio_output_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> VoiceUsage:
        """
        Log usage for a completed voice session.
        
        Args:
            session_id: Voice session UUID
            company_id: Company UUID
            provider: 'twilio' or 'tata_tele'
            duration_seconds: Total call duration
            audio_input_seconds: Audio sent to LLM (optional, defaults to full duration)
            audio_output_seconds: Audio received from LLM (optional, defaults to full duration)
            metadata: Additional metadata to log
            
        Returns:
            The total cost in USD and its telephony part
        """
        total_cost = Decimal("0.0")
        telephony_part = Decimal("0")

        # Default audio durations to total call duration.
        # Both input (user speech) and output (agent speech) span the
        # entire call, so each is billed for the full duration.
        if audio_input_seconds is None:
            audio_input_seconds = duration_seconds
        if audio_output_seconds is None:
            audio_output_seconds = duration_seconds
        
        # 1. Log Telephony Cost
        try:
            telephony_cost = await self._log_telephony_usage(
                company_id=company_id,
                provider=provider,
                duration_seconds=duration_seconds,
                metadata={
                    "session_id": str(session_id),
                    "provider": provider,
                    **(metadata or {})
                }
            )
            if telephony_cost:
                total_cost += telephony_cost
                telephony_part = telephony_cost
                logger.info(f"Logged telephony cost: ${telephony_cost} for {duration_seconds}s")
        except Exception as e:
            logger.error(f"Failed to log telephony usage: {e}")
        
        # 2. Log LLM Audio Input Cost
        try:
            input_cost = await self._log_llm_audio_usage(
                company_id=company_id,
                sku_name=self.GEMINI_INPUT_SKU,
                audio_seconds=audio_input_seconds,
                usage_type="input",
                metadata={
                    "session_id": str(session_id),
                    **(metadata or {})
                }
            )
            if input_cost:
                total_cost += input_cost
                logger.info(f"Logged LLM input cost: ${input_cost} for {audio_input_seconds}s")
        except Exception as e:
            logger.error(f"Failed to log LLM input usage: {e}")
        
        # 3. Log LLM Audio Output Cost
        try:
            output_cost = await self._log_llm_audio_usage(
                company_id=company_id,
                sku_name=self.GEMINI_OUTPUT_SKU,
                audio_seconds=audio_output_seconds,
                usage_type="output",
                metadata={
                    "session_id": str(session_id),
                    **(metadata or {})
                }
            )
            if output_cost:
                total_cost += output_cost
                logger.info(f"Logged LLM output cost: ${output_cost} for {audio_output_seconds}s")
        except Exception as e:
            logger.error(f"Failed to log LLM output usage: {e}")
        
        # 4. Update voice session total cost
        try:
            await self._update_session_total_cost(session_id, total_cost)
            logger.info(f"Updated voice session {session_id} total cost: ${total_cost}")
        except Exception as e:
            logger.error(f"Failed to update session total cost: {e}")

        return VoiceUsage(total_cost, telephony_part, billed_minutes(duration_seconds))

    async def _log_telephony_usage(
        self,
        company_id: UUID,
        provider: str,
        duration_seconds: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Decimal]:
        """Log telephony usage based on provider and duration."""
        sku_name = self.TELEPHONY_SKU_MAP.get(provider)
        if not sku_name:
            logger.warning(f"Unknown telephony provider: {provider}")
            return None
        
        # Get SKU from registry
        registry_entry = await self._get_sku(company_id, sku_name)
        if not registry_entry:
            logger.warning(f"No active SKU found: {sku_name} for company {company_id}")
            return None
        
        # Calculate cost (rate is per minute, floored to higher integer value based on requirement limit)
        duration_minutes = billed_minutes(duration_seconds)
        calculated_cost = registry_entry.internal_cost * duration_minutes

        # Create usage log
        usage_log = UsageLog(
            company_id=company_id,
            sku_id=registry_entry.id,
            raw_quantity=duration_minutes,
            calculated_cost=calculated_cost,
            log_metadata={
                "usage_type": "telephony",
                "duration_seconds": duration_seconds,
                "duration_minutes": float(duration_minutes),
                "provider": provider,
                **(metadata or {})
            }
        )
        
        self.db.add(usage_log)
        await self.db.commit()
        
        return calculated_cost
    
    async def _log_llm_audio_usage(
        self,
        company_id: UUID,
        sku_name: str,
        audio_seconds: int,
        usage_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Decimal]:
        """
        Log LLM audio usage.
        
        Supports two billing modes based on the SKU's cost_unit:
        - 'per_minute': Charges per minute (ceiling-rounded). E.g. 125s → 3 min.
        - '1M Tokens' / '1K': Estimates tokens from audio duration (~167 tok/s).
        """
        # Get SKU from registry
        registry_entry = await self._get_sku(company_id, sku_name)
        if not registry_entry:
            logger.warning(f"No active SKU found: {sku_name} for company {company_id}")
            return None
        
        from src.ai.usage_service import parse_cost_unit
        try:
            unit = parse_cost_unit(registry_entry.cost_unit)
        except ValueError:
            logger.error("Unknown cost_unit %r on SKU %s", registry_entry.cost_unit, sku_name)
            unit = None

        if unit is not None and unit.noun == "minute":
            # ── Per-minute billing (ceiling-rounded) ──────────────────
            duration_minutes = Decimal(str(math.ceil(audio_seconds / 60.0)))
            calculated_cost = registry_entry.internal_cost * duration_minutes / unit.quantity
            raw_quantity = duration_minutes
            log_extra = {
                "billing_mode": "per_minute",
                "audio_seconds": audio_seconds,
                "billed_minutes": float(duration_minutes),
            }
        else:
            # ── Token-based billing (1M or 1K tokens) ─────────────────
            tokens_per_second = Decimal("167")
            estimated_tokens = tokens_per_second * Decimal(str(audio_seconds))
            cost_divisor = Decimal("1000000")
            if unit is not None and unit.noun == "token":
                cost_divisor = unit.quantity
            calculated_cost = (registry_entry.internal_cost * estimated_tokens) / cost_divisor
            raw_quantity = estimated_tokens
            log_extra = {
                "billing_mode": "per_token",
                "audio_seconds": audio_seconds,
                "estimated_tokens": float(estimated_tokens),
                "tokens_per_second": float(tokens_per_second),
            }
        
        # Create usage log
        usage_log = UsageLog(
            company_id=company_id,
            sku_id=registry_entry.id,
            raw_quantity=raw_quantity,
            calculated_cost=calculated_cost,
            log_metadata={
                "usage_type": f"llm_audio_{usage_type}",
                **log_extra,
                **(metadata or {})
            }
        )
        
        self.db.add(usage_log)
        await self.db.commit()
        
        return calculated_cost
    
    async def _get_sku(
        self,
        company_id: UUID,
        sku_name: str
    ) -> Optional[IntegrationRegistry]:
        """Get active SKU from integration registry.
        
        Lookup order:
        1. Company-specific SKU (tenant override)
        2. service_sku match for company
        3. model_name match for company
        4. APP company fallback (platform-level SKUs)
        """
        # Try company-specific SKU first
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.service_sku == sku_name,
                IntegrationRegistry.status == "active"
            ).limit(1)
        )
        entry = result.scalar_one_or_none()
        
        if not entry:
            # Try model_name as fallback (some SKUs use model_name)
            result = await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == company_id,
                    IntegrationRegistry.model_name == sku_name,
                    IntegrationRegistry.status == "active"
                ).limit(1)
            )
            entry = result.scalar_one_or_none()

        if not entry:
            # Fall back to APP company SKUs (platform-level pricing shared across all tenants)
            from src.auth.models import Company
            app_result = await self.db.execute(
                select(Company.id).where(Company.type == "APP").limit(1)
            )
            app_company_id = app_result.scalar_one_or_none()
            if app_company_id and app_company_id != company_id:
                result = await self.db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == app_company_id,
                        IntegrationRegistry.service_sku == sku_name,
                        IntegrationRegistry.status == "active"
                    ).limit(1)
                )
                entry = result.scalar_one_or_none()
                if not entry:
                    result = await self.db.execute(
                        select(IntegrationRegistry).where(
                            IntegrationRegistry.company_id == app_company_id,
                            IntegrationRegistry.model_name == sku_name,
                            IntegrationRegistry.status == "active"
                        ).limit(1)
                    )
                    entry = result.scalar_one_or_none()
                if entry:
                    logger.debug(f"Using APP-company SKU fallback for {sku_name} (billing company: {company_id})")

        return entry

    
    async def _update_session_total_cost(
        self,
        session_id: UUID,
        total_cost: Decimal
    ) -> None:
        """Update voice_sessions.total_cost_usd."""
        await self.db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == session_id)
            .values(total_cost_usd=total_cost)
        )
        await self.db.commit()
