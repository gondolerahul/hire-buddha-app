"""support access grants and views (docs/phase15/14_connector_approvals/10, SH-E6)

``support_access_grants``: a business lets HireBuddha's staff read what came
through its connections, until a time or until revoked. ``support_access_views``:
each time a staff member opened such a run, under which grant or with the
content withheld.

Revision ID: control_0024_support_access
Revises: control_0023_provider_deletions
Create Date: 2026-10-29 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'control_0024_support_access'
down_revision: Union[str, Sequence[str], None] = 'control_0023_provider_deletions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_access_grants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('granted_by', sa.UUID(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
        info={'plane': 'control'},
    )
    op.create_index('ix_support_access_grants_company', 'support_access_grants', ['company_id', 'expires_at'],
                    unique=False)
    op.create_table(
        'support_access_views',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('grant_id', sa.UUID(), nullable=True),
        sa.Column('run_id', sa.UUID(), nullable=True),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('withheld', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
        info={'plane': 'control'},
    )
    op.create_index('ix_support_access_views_company_at', 'support_access_views', ['company_id', 'at'],
                    unique=False)


def downgrade() -> None:
    op.drop_index('ix_support_access_views_company_at', table_name='support_access_views')
    op.drop_table('support_access_views')
    op.drop_index('ix_support_access_grants_company', table_name='support_access_grants')
    op.drop_table('support_access_grants')
