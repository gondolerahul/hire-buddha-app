"""
Voice Usage Logger for tracking call costs and LLM usage.

Logs:
- Call duration and telephony costs
- Gemini API usage (audio input/output)
- Updates voice_sessions.total_cost_usd
- Creates entries in usage_logs table
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.config.models import IntegrationRegistry
from src.ai.orm import UsageLog
from src.ai.services.cost_attribution import CostAttribution
from src.ai.usage_service import Price, flag_unpriced, price_at
from src.billing.units import Dimension, unit_spec
from src.voice.live_usage import LiveUsage
from src.voice.models import VoiceSession

logger = logging.getLogger(__name__)

VOICE_CALL = CostAttribution.VOICE_CALL.value


# Live audio without the provider's token count: about 167 tokens a second
# (Gemini Live); a SKU may say otherwise in service_metadata.tokens_per_second.
DEFAULT_AUDIO_TOKENS_PER_SECOND = 167


@dataclass
class VoiceUsage:
    """A call's logged cost: the total, its telephony part (BC-13) and the
    seconds it was billed for — exact, not started minutes (T1-4)."""
    total_cost: Decimal
    telephony_cost: Decimal
    telephony_seconds: Decimal


class VoiceUsageLogger:
    """
    Logs usage and calculates costs for voice calls.
    
    Tracks:
    - Telephony costs (per second, at the provider SKU's rate)
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
        duration_seconds,
        audio_input_seconds: Optional[int] = None,
        audio_output_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tool_cost: Decimal = Decimal("0"),
        live_usage: Optional[LiveUsage] = None,
        run_id: Optional[UUID] = None,
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
            tool_cost: The call's tool calls, already logged per call against
                the call's run (``voice.tool_calls``, TL-20); counted in the
                total so the call's one charge includes them
            live_usage: What the model reported and the audio each way
                (``voice.live_usage``, VT-05). Its tokens are billed when the
                provider sent usage; otherwise each direction is billed for
                the audio it carried, not the whole call
            run_id: The call's run (``voice.tool_calls``, VT-21). The
                telephony and audio rows are written on it, attributed
                ``voice_call``, so the run's cost is the call's
            
        Returns:
            The total cost in USD and its telephony part
        """
        total_cost = Decimal("0.0")
        telephony_part = Decimal("0")

        # Without the provider's usage, each direction is billed for the audio
        # it carried (VT-I1); a caller that knows neither bills the call length.
        if audio_input_seconds is None:
            audio_input_seconds = live_usage.seconds_in if live_usage is not None else duration_seconds
        if audio_output_seconds is None:
            audio_output_seconds = live_usage.seconds_out if live_usage is not None else duration_seconds
        
        # 1. Log Telephony Cost
        try:
            telephony_cost = await self._log_telephony_usage(
                company_id=company_id,
                provider=provider,
                duration_seconds=duration_seconds,
                run_id=run_id,
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
        
        # 2–3. The model's audio each way — the provider's tokens when it sent them (VT-05)
        total_cost += await self.log_live_model_usage(
            company_id=company_id, live_usage=live_usage, run_id=run_id,
            audio_input_seconds=audio_input_seconds, audio_output_seconds=audio_output_seconds,
            metadata={"session_id": str(session_id), **(metadata or {})},
        )

        # 4. The call's tool calls (each has its own usage_logs row on the run).
        if tool_cost and tool_cost > 0:
            total_cost += Decimal(str(tool_cost))

        # 5. Update voice session total cost
        try:
            await self._update_session_total_cost(session_id, total_cost)
            logger.info(f"Updated voice session {session_id} total cost: ${total_cost}")
        except Exception as e:
            logger.error(f"Failed to update session total cost: {e}")

        return VoiceUsage(total_cost, telephony_part, max(Decimal(str(duration_seconds)), Decimal("0")))

    async def log_live_model_usage(
        self,
        company_id: UUID,
        live_usage: Optional[LiveUsage],
        audio_input_seconds: int,
        audio_output_seconds: int,
        run_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Decimal:
        """The live model's audio in and out, on the call's run; returns their cost.

        A phone call's and a video call's model use are billed the same way:
        the tokens the provider reported, else each direction's audio (VT-05).
        """
        total = Decimal("0")
        reported = live_usage is not None and live_usage.reported
        try:
            input_cost = await self._log_llm_audio_usage(
                company_id=company_id,
                sku_name=self.GEMINI_INPUT_SKU,
                audio_seconds=audio_input_seconds,
                usage_type="input",
                metadata=metadata,
                reported_tokens=live_usage.prompt_tokens if reported and live_usage else None,
                by_modality=live_usage.prompt_by_modality if reported and live_usage else None,
                run_id=run_id,
            )
            if input_cost:
                total += input_cost
                logger.info(f"Logged LLM input cost: ${input_cost} for {audio_input_seconds}s")
        except Exception as e:
            logger.error(f"Failed to log LLM input usage: {e}")
        
        # The model's audio out
        try:
            output_cost = await self._log_llm_audio_usage(
                company_id=company_id,
                sku_name=self.GEMINI_OUTPUT_SKU,
                audio_seconds=audio_output_seconds,
                usage_type="output",
                metadata=metadata,
                reported_tokens=live_usage.response_tokens if reported and live_usage else None,
                by_modality=live_usage.response_by_modality if reported and live_usage else None,
                run_id=run_id,
            )
            if output_cost:
                total += output_cost
                logger.info(f"Logged LLM output cost: ${output_cost} for {audio_output_seconds}s")
        except Exception as e:
            logger.error(f"Failed to log LLM output usage: {e}")

        return total

    async def _write(
        self,
        *,
        company_id: UUID,
        sku_name: str,
        entry: Optional[IntegrationRegistry],
        price: Price,
        quantity: Decimal,
        dimension: Dimension,
        metadata: Dict[str, Any],
        run_id: Optional[UUID],
    ) -> Decimal:
        """One call usage row (committed); a missing or mismatched SKU is a flagged $0 row (T1-3)."""
        meta = dict(metadata)
        if not price.priced:
            meta.update(cost_source=price.cost_source, sku=sku_name, dimension=[str(dimension)])
            if entry is not None:
                meta["unit"] = entry.cost_unit_code
        row = UsageLog(
            company_id=company_id,
            run_id=run_id,
            attribution=VOICE_CALL,
            sku_id=entry.id if entry is not None else None,
            raw_quantity=quantity,
            calculated_cost=price.cost,
            log_metadata=meta,
        )
        from src.billing.rating import rate_row
        await rate_row(self.db, row, sku=sku_name)           # billed as voice (T3-3)
        self.db.add(row)
        await self.db.commit()
        await flag_unpriced(price, sku=sku_name, company_id=company_id, run_id=run_id, dimension=dimension)
        return price.cost

    async def _log_telephony_usage(
        self,
        company_id: UUID,
        provider: str,
        duration_seconds,
        metadata: Optional[Dict[str, Any]] = None,
        run_id: Optional[UUID] = None,
    ) -> Optional[Decimal]:
        """The call's telephony, per second (Phase 15 T1-4, REQ-CO-1).

        ``duration_seconds`` is exact — a fraction when the caller measured
        one. A per-minute SKU (``PER_MINUTE``) is a price per 60 seconds: 125 s
        at $0.60/min costs $1.25. It used to be ``ceil(seconds / 60)`` minutes:
        3 minutes, $1.80. What the carrier itself charges (by the minute, say)
        is the SKU's ``provider_billing_increment_seconds``, used only by the
        cost reconciliation (T1-6), never here.
        """
        sku_name = self.TELEPHONY_SKU_MAP.get(provider)
        if not sku_name:
            logger.warning(f"Unknown telephony provider: {provider}")
            return None
        seconds = max(Decimal(str(duration_seconds)), Decimal("0"))
        entry = await self._get_sku(company_id, sku_name)
        return await self._write(
            company_id=company_id, sku_name=sku_name, entry=entry,
            price=price_at(entry, seconds, Dimension.SECOND), quantity=seconds, dimension=Dimension.SECOND,
            metadata={"usage_type": "telephony", "duration_seconds": float(seconds), "provider": provider,
                      **(metadata or {})},
            run_id=run_id,
        )

    async def _log_llm_audio_usage(
        self,
        company_id: UUID,
        sku_name: str,
        audio_seconds,
        usage_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        reported_tokens: Optional[int] = None,
        by_modality: Optional[Dict[str, int]] = None,
        run_id: Optional[UUID] = None,
    ) -> Optional[Decimal]:
        """The live model's audio one way.

        By the SKU's unit (Phase 15 T1-4): priced in **seconds** (``PER_MINUTE``,
        ``PER_SECOND``) — the audio's exact seconds; priced in **tokens** — the
        tokens the provider reported for the call (VT-05), else the seconds ×
        the SKU's ``service_metadata.tokens_per_second`` (default 167).
        """
        entry = await self._get_sku(company_id, sku_name)
        seconds = max(Decimal(str(audio_seconds or 0)), Decimal("0"))
        by_time = entry is not None and unit_spec(entry.cost_unit_code).dimension == Dimension.SECOND
        if by_time:
            dimension, quantity = Dimension.SECOND, seconds
            log_extra = {"billing_mode": "per_second", "audio_seconds": float(seconds)}
        elif reported_tokens is not None:
            # What the provider reported, summed over the call (VT-05).
            dimension, quantity = Dimension.TOKEN, Decimal(int(reported_tokens))
            log_extra = {
                "billing_mode": "reported_tokens",
                "audio_seconds": float(seconds),
                "reported_tokens": int(reported_tokens),
                "tokens_by_modality": dict(by_modality or {}),
            }
        else:
            rate = Decimal(str((getattr(entry, "service_metadata", None) or {})
                               .get("tokens_per_second", DEFAULT_AUDIO_TOKENS_PER_SECOND)))
            dimension, quantity = Dimension.TOKEN, rate * seconds
            log_extra = {
                "billing_mode": "estimated_from_audio",
                "audio_seconds": float(seconds),
                "estimated_tokens": float(quantity),
                "tokens_per_second": float(rate),
            }
        return await self._write(
            company_id=company_id, sku_name=sku_name, entry=entry,
            price=price_at(entry, quantity, dimension), quantity=quantity, dimension=dimension,
            metadata={"usage_type": f"llm_audio_{usage_type}", **log_extra, **(metadata or {})},
            run_id=run_id,
        )

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
            from src.auth.platform import platform_company_id
            app_company_id = await platform_company_id(self.db)
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
