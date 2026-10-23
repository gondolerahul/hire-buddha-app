"""exact quantities and seconds (Phase 15 T1-4, T1-5)

Revision ID: control_0008_exact_quantities
Revises: control_0007_registry_unit_codes
Create Date: 2026-10-23

* ``usage_logs.raw_quantity`` / ``calculated_cost`` and
  ``integration_registry.internal_cost`` → ``NUMERIC(24,10)`` (tech design
  conventions): nothing in costing is rounded, so the store must not round
  at 6 decimals either.
* ``billing_events.telephony_in/out_minutes`` → ``telephony_in/out_seconds``
  (``NUMERIC(24,10)``): calls are billed per second (REQ-CO-1). Existing
  values were started minutes; they become those minutes' seconds (× 60).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0008_exact_quantities'
down_revision: Union[str, Sequence[str], None] = 'control_0007_registry_unit_codes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('usage_logs', 'raw_quantity', type_=EXACT, existing_type=sa.Numeric(18, 6), existing_nullable=False)
    op.alter_column('usage_logs', 'calculated_cost', type_=EXACT, existing_type=sa.Numeric(18, 6),
                    existing_nullable=False)
    op.alter_column('integration_registry', 'internal_cost', type_=EXACT, existing_type=sa.Numeric(18, 6),
                    existing_nullable=False)
    for direction in ('in', 'out'):
        op.alter_column('billing_events', f'telephony_{direction}_minutes', new_column_name=f'telephony_{direction}_seconds',
                        type_=EXACT, existing_type=sa.Numeric(10, 2), existing_nullable=False,
                        postgresql_using=f'telephony_{direction}_minutes * 60')


def downgrade() -> None:
    """Downgrade schema."""
    for direction in ('in', 'out'):
        op.alter_column('billing_events', f'telephony_{direction}_seconds', new_column_name=f'telephony_{direction}_minutes',
                        type_=sa.Numeric(10, 2), existing_type=EXACT, existing_nullable=False,
                        postgresql_using=f'round(telephony_{direction}_seconds / 60, 2)')
    op.alter_column('integration_registry', 'internal_cost', type_=sa.Numeric(18, 6), existing_type=EXACT,
                    existing_nullable=False)
    op.alter_column('usage_logs', 'calculated_cost', type_=sa.Numeric(18, 6), existing_type=EXACT,
                    existing_nullable=False)
    op.alter_column('usage_logs', 'raw_quantity', type_=sa.Numeric(18, 6), existing_type=EXACT, existing_nullable=False)
