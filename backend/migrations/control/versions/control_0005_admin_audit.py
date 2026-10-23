"""admin audit log (Phase 15 T0-1)

Revision ID: control_0005_admin_audit
Revises: control_0004_media_categories
Create Date: 2026-10-23

Who changed a platform setting, when, and from what (tech design §17):
``admin_audit_log``, written first by the feature-flag admin API.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'control_0005_admin_audit'
down_revision: Union[str, Sequence[str], None] = 'control_0004_media_categories'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('admin_audit_log',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_role', sa.Text(), nullable=True),
    sa.Column('acting_company_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('object_type', sa.Text(), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('target_company_id', sa.UUID(), nullable=True),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_admin_audit_log_object', 'admin_audit_log', ['object_type', 'object_key', 'at'], unique=False)
    op.create_index('ix_admin_audit_log_company', 'admin_audit_log', ['target_company_id', 'at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_admin_audit_log_company', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_log_object', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
