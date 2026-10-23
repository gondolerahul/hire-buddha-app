"""billing formulas (Phase 15 T3-2)

Revision ID: control_0012_billing_formulas
Revises: control_0011_company_geography
Create Date: 2026-10-23

``billing_formulas``: versions of ``TB = c·mf·(1 + pf − d)`` per platform /
plan / company (tech design §8.1). Each active ``billing_config`` row becomes a
version in effect from 2000-01-01 — the global row the platform's, a company's
its own — with ``spf`` added to ``pf`` so the price is unchanged (K-10; a row
whose ``pf + spf`` would exceed 1 stops the upgrade with a list).

The cost overrides become registry rows, as staff would have made them:
``base_cost_telephony`` ($/minute) → the company's (the platform's for the
global row) ``in-out`` and ``tata-tele-voice-in-out`` rows at ``PER_MINUTE``;
``base_cost_image_gen`` ($/image) → its ``image_generation`` row at
``PER_IMAGE``. Their ``service_metadata.migrated_from`` names the field.
``billing_config`` keeps ``default_daily_credits`` (read until T5-5); nothing
reads its formula or override columns after this.

"""
import json
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0012_billing_formulas'
down_revision: Union[str, Sequence[str], None] = 'control_0011_company_geography'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SINCE = datetime(2000, 1, 1)  # naive UTC, as the app's timestamp codec expects
TELEPHONY = (('in-out', 'twilio'), ('tata-tele-voice-in-out', 'tata_tele'))


def _override_row(bind, company_id, sku: str, provider: str, category: str, cost, unit: str, field: str) -> None:
    metadata = json.dumps({"migrated_from": f"billing_config.{field}"})
    existing = bind.execute(sa.text("SELECT id FROM integration_registry WHERE company_id = :c AND service_sku = :s"),
                            {"c": company_id, "s": sku}).first()
    if existing:
        bind.execute(sa.text(
            "UPDATE integration_registry SET internal_cost = :cost, cost_unit_code = :u, status = 'active', "
            "service_metadata = COALESCE(service_metadata, '{}'::jsonb) || CAST(:m AS jsonb), updated_at = now() "
            "WHERE id = :id"), {"cost": cost, "u": unit, "m": metadata, "id": existing[0]})
    else:
        bind.execute(sa.text(
            "INSERT INTO integration_registry (id, company_id, provider_name, service_sku, service_category, "
            "component_type, internal_cost, cost_unit_code, service_metadata, status, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :c, :p, :s, :cat, :ct, :cost, :u, CAST(:m AS jsonb), 'active', now(), now())"),
            {"c": company_id, "p": provider, "s": sku, "cat": category, "ct": category.lower(), "cost": cost,
             "u": unit, "m": metadata})


def migrate_configs(bind) -> None:
    """Active ``billing_config`` rows → formula versions and registry rows (the data step)."""
    configs = bind.execute(sa.text(
        "SELECT id, company_id, multiplier_factor, platform_fee_pct, sales_partner_fee_pct, discount_pct, "
        "base_cost_telephony, base_cost_image_gen FROM billing_config WHERE is_active "
        "ORDER BY company_id NULLS FIRST, updated_at DESC")).all()
    too_high = [str(c.id) for c in configs if (c.platform_fee_pct or 0) + (c.sales_partner_fee_pct or 0) > 1]
    if too_high:
        raise RuntimeError("control_0012: billing_config rows whose pf + spf exceeds 1 — fix them first: "
                           + ", ".join(too_high))
    platform = bind.execute(sa.text("SELECT id FROM companies WHERE type = 'APP' LIMIT 1")).scalar()
    seen = set()
    for c in configs:
        if c.company_id in seen:      # one per scope: the latest-updated active row wins, as it did
            continue
        seen.add(c.company_id)
        spf = c.sales_partner_fee_pct or 0
        bind.execute(sa.text(
            "INSERT INTO billing_formulas (scope, scope_id, mf, pf, d, effective_from, reason) "
            "VALUES (:scope, :sid, :mf, :pf, :d, :since, :reason)"),
            {"scope": "company" if c.company_id else "platform", "sid": c.company_id,
             "mf": c.multiplier_factor, "pf": (c.platform_fee_pct or 0) + spf, "d": c.discount_pct or 0,
             "since": SINCE,
             "reason": f"migrated from billing_config {c.id}" + (f" (spf {spf} added to pf)" if spf else "")})
        owner = c.company_id or platform
        if owner is None:
            continue
        if c.base_cost_telephony is not None:
            for sku, provider in TELEPHONY:
                _override_row(bind, owner, sku, provider, 'COMMUNICATION', c.base_cost_telephony, 'PER_MINUTE',
                              'base_cost_telephony')
        if c.base_cost_image_gen is not None:
            _override_row(bind, owner, 'image_generation', 'override', 'IMAGE_GENERATION', c.base_cost_image_gen,
                          'PER_IMAGE', 'base_cost_image_gen')



def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('billing_formulas',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('scope_id', sa.UUID(), nullable=True),
    sa.Column('mf', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('pf', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('d', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("scope IN ('platform', 'plan', 'company')", name='ck_billing_formulas_scope'),
    sa.CheckConstraint('mf > 0 AND mf <= 100', name='ck_billing_formulas_mf'),
    sa.CheckConstraint('pf >= 0 AND pf <= 1 AND d >= 0 AND d <= 1', name='ck_billing_formulas_fractions'),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_billing_formulas_scope', 'billing_formulas', ['scope', 'scope_id', 'effective_from'],
                    unique=False)

    migrate_configs(op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM integration_registry WHERE service_metadata->>'migrated_from' LIKE 'billing_config.%'")
    op.drop_index('ix_billing_formulas_scope', table_name='billing_formulas')
    op.drop_table('billing_formulas')
