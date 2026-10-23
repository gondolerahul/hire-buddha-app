"""company geography and billing profile (Phase 15 T2-2)

Revision ID: control_0011_company_geography
Revises: control_0010_currency
Create Date: 2026-10-23

``companies`` + ``country_code`` (→ ``country_profiles``), ``billing_currency``
(→ ``currencies``), ``billing_state``, ``gstin``, ``legal_name``,
``billing_address`` (tech design §3.1). Every existing company becomes India /
INR (the defaults; plan §4 step 2): the platform's companies are Indian.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'control_0011_company_geography'
down_revision: Union[str, Sequence[str], None] = 'control_0010_currency'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('companies', sa.Column('country_code', sa.CHAR(length=2), server_default='IN', nullable=False))
    op.add_column('companies', sa.Column('billing_currency', sa.CHAR(length=3), server_default='INR', nullable=False))
    op.add_column('companies', sa.Column('billing_state', sa.String(length=2), nullable=True))
    op.add_column('companies', sa.Column('gstin', sa.Text(), nullable=True))
    op.add_column('companies', sa.Column('legal_name', sa.Text(), nullable=True))
    op.add_column('companies', sa.Column('billing_address', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_foreign_key('companies_country_code_fkey', 'companies', 'country_profiles',
                          ['country_code'], ['country_code'])
    op.create_foreign_key('companies_billing_currency_fkey', 'companies', 'currencies',
                          ['billing_currency'], ['code'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('companies_billing_currency_fkey', 'companies', type_='foreignkey')
    op.drop_constraint('companies_country_code_fkey', 'companies', type_='foreignkey')
    for column in ('billing_address', 'legal_name', 'gstin', 'billing_state', 'billing_currency', 'country_code'):
        op.drop_column('companies', column)
