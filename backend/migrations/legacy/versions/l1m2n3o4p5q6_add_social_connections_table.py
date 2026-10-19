"""Add social_connections table

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2026-03-08 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'l1m2n3o4p5q6'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'social_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('account_name', sa.String(255), nullable=True),
        sa.Column('encrypted_access_token', sa.Text(), nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('platform_user_id', sa.String(255), nullable=True),
        sa.Column('platform_page_id', sa.String(255), nullable=True),
        sa.Column('scopes', postgresql.JSON(), nullable=True, server_default='[]'),
        sa.Column('oauth_metadata', postgresql.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    # Unique constraint: one account per platform per company
    op.create_unique_constraint(
        'uq_social_connection_company_platform_user',
        'social_connections',
        ['company_id', 'platform', 'platform_user_id']
    )

    # Index for fast lookups by company + platform
    op.create_index(
        'ix_social_connections_company_platform',
        'social_connections',
        ['company_id', 'platform']
    )


def downgrade() -> None:
    op.drop_index('ix_social_connections_company_platform')
    op.drop_table('social_connections')
