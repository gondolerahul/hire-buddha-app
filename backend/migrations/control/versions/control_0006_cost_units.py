"""cost units (Phase 15 T1-1)

Revision ID: control_0006_cost_units
Revises: control_0005_admin_audit
Create Date: 2026-10-23

The enumerated cost units (tech design §2.1): ``cost_units``, seeded with the
list in ``src.billing.units`` as it stands at this revision. The rows are
written out here, not imported, so this revision means the same thing after
the enum grows; a later unit is inserted by its own revision.
``integration_registry`` starts naming its unit by code in T1-2.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0006_cost_units'
down_revision: Union[str, Sequence[str], None] = 'control_0005_admin_audit'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, dimension, per_quantity, label) — tests/unit/test_cost_units.py collects every revision's COST_UNITS
COST_UNITS = [
    ('PER_TOKEN', 'token', 1, 'per token'),
    ('PER_1K_TOKENS', 'token', 1000, 'per 1K tokens'),
    ('PER_1M_TOKENS', 'token', 1000000, 'per 1M tokens'),
    ('PER_CHARACTER', 'character', 1, 'per character'),
    ('PER_1K_CHARACTERS', 'character', 1000, 'per 1K characters'),
    ('PER_1M_CHARACTERS', 'character', 1000000, 'per 1M characters'),
    ('PER_SECOND', 'second', 1, 'per second'),
    ('PER_MINUTE', 'second', 60, 'per minute'),
    ('PER_HOUR', 'second', 3600, 'per hour'),
    ('PER_REQUEST', 'request', 1, 'per request'),
    ('PER_1K_REQUESTS', 'request', 1000, 'per 1K requests'),
    ('PER_IMAGE', 'image', 1, 'per image'),
    ('PER_VIDEO', 'video', 1, 'per video'),
    ('PER_MESSAGE', 'message', 1, 'per message'),
    ('PER_EMAIL', 'email', 1, 'per e-mail'),
    ('PER_PAGE', 'page', 1, 'per page'),
    ('PER_QUERY', 'query', 1, 'per query'),
    ('PER_1K_QUERIES', 'query', 1000, 'per 1K queries'),
    ('PER_GB', 'gb', 1, 'per GB'),
    ('PER_GB_HOUR', 'gb_hour', 1, 'per GB-hour'),
    ('PER_GB_MONTH', 'gb_month', 1, 'per GB-month'),
    ('PER_VCPU_HOUR', 'vcpu_hour', 1, 'per vCPU-hour'),
    ('PER_DAY', 'day', 1, 'per day'),
    ('PER_MONTH', 'month', 1, 'per month'),
    ('PER_UNIT', 'unit', 1, 'per unit'),
]


def upgrade() -> None:
    """Upgrade schema."""
    table = op.create_table('cost_units',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('dimension', sa.Text(), nullable=False),
    sa.Column('per_quantity', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.CheckConstraint('per_quantity > 0', name='ck_cost_units_per_quantity'),
    sa.PrimaryKeyConstraint('code'),
    info={'plane': 'control'}
    )
    op.bulk_insert(table, [
        {'code': code, 'dimension': dimension, 'per_quantity': per_quantity, 'label': label, 'active': True}
        for code, dimension, per_quantity, label in COST_UNITS
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('cost_units')
