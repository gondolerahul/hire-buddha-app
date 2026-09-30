"""
Billing Service — implements the global billing formula and billing event recording.

TB = (c × mf) + (c × mf × pf) + (c × mf × spf) - (c × mf × d)

Where:
  c   = base cost (unit execution cost)
  mf  = multiplier factor %
  pf  = platform fee %
  spf = sales partner fee %
  d   = discount %
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from typing import Optional
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from src.billing.billing_models import BILLING_EVENT_UNIQUE_KEY, BillingConfig, BillingEvent

_CATEGORY_CHARGES = ("telephony", "llm", "image", "video")
_CHARGE_COLUMNS = tuple(f"{c}_charge" for c in _CATEGORY_CHARGES) + ("api_charge",)


def calculate_tb(
    c: Decimal,
    mf: Decimal,
    pf: Decimal,
    spf: Decimal,
    d: Decimal,
) -> dict:
    """
    Calculate Total Billing using the formula:
    TB = (c*mf) + (c*mf*pf) + (c*mf*spf) - (c*mf*d)

    Returns a dict with all intermediate values and the final TB.
    """
    multiplied = c * mf
    platform_fee = multiplied * pf
    partner_fee = multiplied * spf
    discount = multiplied * d
    total = multiplied + platform_fee + partner_fee - discount
    return {
        "base_cost": c,
        "multiplied_cost": multiplied,
        "platform_fee_amount": platform_fee,
        "partner_fee_amount": partner_fee,
        "discount_amount": discount,
        "total_billing": total,
    }


def compute_billed_amount(base_cost: Decimal, config: Optional["BillingConfig"]) -> Decimal:
    """
    Customer-billed amount for a given internal cost under a billing config.

    Falls back to the identity formula (no fees/discounts) when the company
    has no active config, matching the per-call credit deduction behavior.
    """
    if config is None:
        mf, pf, spf, d = Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0")
    else:
        mf = Decimal(str(config.multiplier_factor))
        pf = Decimal(str(config.platform_fee_pct))
        spf = Decimal(str(config.sales_partner_fee_pct))
        d = Decimal(str(config.discount_pct))
    return calculate_tb(Decimal(str(base_cost)), mf, pf, spf, d)["total_billing"]


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_billing_config(self, company_id: UUID) -> BillingConfig:
        """
        Return company-specific billing config, falling back to global default.
        """
        # Try company-specific first
        stmt = select(BillingConfig).where(
            BillingConfig.company_id == company_id,
            BillingConfig.is_active == True,
        ).order_by(BillingConfig.updated_at.desc())
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if config:
            return config

        # Fall back to global default (company_id IS NULL)
        stmt = select(BillingConfig).where(
            BillingConfig.company_id == None,
            BillingConfig.is_active == True,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def record_billing_event(
        self,
        company_id: UUID,
        base_cost: Decimal,
        grouping_type: Optional[str] = None,
        grouping_value: Optional[str] = None,
        telephony_in_minutes: Decimal = Decimal("0"),
        telephony_out_minutes: Decimal = Decimal("0"),
        image_gen_count: int = 0,
        video_gen_count: int = 0,
        other_ai_cost: Decimal = Decimal("0"),
        event_category: str = "api",  # "telephony", "llm", "image", "video", "api"
    ) -> BillingEvent:
        """
        Calculate TB from formula, then upsert a BillingEvent for the current month.
        Divides the final price into category charges based on event_category.
        """
        config = await self.get_billing_config(company_id)
        if not config:
            # No config found — use identity formula (no fees/discounts)
            mf, pf, spf, d = Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0")
        else:
            mf = Decimal(str(config.multiplier_factor))
            pf = Decimal(str(config.platform_fee_pct))
            spf = Decimal(str(config.sales_partner_fee_pct))
            d = Decimal(str(config.discount_pct))
            
            # Use overrides if defined
            if event_category == "telephony" and config.base_cost_telephony is not None:
                base_cost = Decimal(str(config.base_cost_telephony)) * (telephony_in_minutes + telephony_out_minutes)
            elif event_category == "llm" and config.base_cost_llm is not None:
                # Assuming base cost provided is directly overridden. 
                pass
            elif event_category == "image" and config.base_cost_image_gen is not None:
                base_cost = Decimal(str(config.base_cost_image_gen)) * Decimal(str(image_gen_count))

        tb = calculate_tb(base_cost, mf, pf, spf, d)

        today = date.today()
        period = date(today.year, today.month, 1)

        # One row per (company, month, grouping) — the unique constraint
        # uq_billing_events_period_grouping (DM-04). A single INSERT ... ON
        # CONFLICT adds this event's amounts to the row atomically, so two
        # concurrent settlements can neither create a second row nor overwrite
        # each other's increments (the old select-then-write did both).
        charge_column = f"{event_category}_charge" if event_category in _CATEGORY_CHARGES else "api_charge"
        amounts = {
            **{k: Decimal(str(v)) for k, v in tb.items()},
            "telephony_in_minutes": telephony_in_minutes,
            "telephony_out_minutes": telephony_out_minutes,
            "image_gen_count": image_gen_count,
            "video_gen_count": video_gen_count,
            "other_ai_cost": other_ai_cost,
            **{column: Decimal("0") for column in _CHARGE_COLUMNS},
        }
        amounts[charge_column] = tb["total_billing"]
        now = datetime.utcnow()
        insert_stmt = pg_insert(BillingEvent).values(
            id=uuid.uuid4(),
            company_id=company_id,
            period_month=period,
            grouping_type=grouping_type,
            grouping_value=grouping_value,
            created_at=now,
            updated_at=now,
            **amounts,
        )
        table = BillingEvent.__table__
        upsert = insert_stmt.on_conflict_do_update(
            constraint=BILLING_EVENT_UNIQUE_KEY,
            set_={
                **{column: table.c[column] + insert_stmt.excluded[column] for column in amounts},
                "updated_at": insert_stmt.excluded.updated_at,
            },
        ).returning(BillingEvent)
        result = await self.db.execute(upsert, execution_options={"populate_existing": True})
        event = result.scalar_one()
        await self.db.commit()
        return event

    async def get_costing_report(
        self,
        company_id: Optional[UUID] = None,
        period_month: Optional[date] = None,
        grouping_type: Optional[str] = None,
    ) -> list:
        """Return billing events for the costing report (internal view).

        ``company_id=None`` returns every company's events. Each event's
        ``company`` is loaded so the report can name it.
        """
        conditions = []
        if company_id:
            conditions.append(BillingEvent.company_id == company_id)
        if period_month:
            conditions.append(BillingEvent.period_month == period_month)
        if grouping_type:
            conditions.append(BillingEvent.grouping_type == grouping_type)

        stmt = select(BillingEvent).options(selectinload(BillingEvent.company)).where(and_(true(), *conditions)).order_by(
            BillingEvent.period_month.desc(), BillingEvent.total_billing.desc()
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_billing_config(
        self,
        company_id: Optional[UUID],
        multiplier_factor: Optional[Decimal] = None,
        platform_fee_pct: Optional[Decimal] = None,
        sales_partner_fee_pct: Optional[Decimal] = None,
        discount_pct: Optional[Decimal] = None,
        default_daily_credits: Optional[Decimal] = None,
        base_cost_telephony: Optional[Decimal] = None,
        base_cost_llm: Optional[Decimal] = None,
        base_cost_image_gen: Optional[Decimal] = None,
    ) -> BillingConfig:
        """Create or update billing config for a company (or global)."""
        stmt = select(BillingConfig).where(
            BillingConfig.company_id == company_id,
            BillingConfig.is_active == True,
        )
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if not config:
            config = BillingConfig(company_id=company_id)
            self.db.add(config)

        if multiplier_factor is not None:
            config.multiplier_factor = multiplier_factor
        if platform_fee_pct is not None:
            config.platform_fee_pct = platform_fee_pct
        if sales_partner_fee_pct is not None:
            config.sales_partner_fee_pct = sales_partner_fee_pct
        if discount_pct is not None:
            config.discount_pct = discount_pct
            
        if default_daily_credits is not None:
            config.default_daily_credits = default_daily_credits
        if base_cost_telephony is not None:
            config.base_cost_telephony = base_cost_telephony
        if base_cost_llm is not None:
            config.base_cost_llm = base_cost_llm
        if base_cost_image_gen is not None:
            config.base_cost_image_gen = base_cost_image_gen

        config.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(config)
        return config
