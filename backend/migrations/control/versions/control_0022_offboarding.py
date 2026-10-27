"""offboarding and erasure (docs/phase15/13_offboarding_and_erasure.md)

``companies.is_test``; ``company_offboardings`` (one per request, no foreign key
to the company it erases: it is the proof that outlives it) and
``offboarding_step_log``. The settings ``offboarding.*`` live in the catalogue.

Revision ID: control_0022_offboarding
Revises: control_0021_staff_functions
Create Date: 2026-10-27 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'control_0022_offboarding'
down_revision: Union[str, Sequence[str], None] = 'control_0021_staff_functions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('is_test', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_table(
        'company_offboardings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('company_ref', sa.Text(), nullable=False),
        sa.Column('company_name', sa.Text(), nullable=True),
        sa.Column('mode', sa.Text(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.UUID(), nullable=True),
        sa.Column('requested_by_role', sa.Text(), nullable=True),
        sa.Column('confirmed_by', sa.UUID(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('previous_status', sa.Text(), nullable=True),
        sa.Column('export_requested', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('export_key', sa.Text(), nullable=True),
        sa.Column('export_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_step', sa.Text(), nullable=True),
        sa.Column('inventory', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('certificate', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('certificate_key', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("mode IN ('erasure', 'immediate')", name='ck_company_offboardings_mode'),
        sa.CheckConstraint("state IN ('requested', 'cancelled', 'exporting', 'erasing', 'erased', 'failed')",
                           name='ck_company_offboardings_state'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_company_offboardings_open', 'company_offboardings', ['company_id'], unique=True,
                    postgresql_where=sa.text("state IN ('requested', 'exporting', 'erasing', 'failed')"))
    op.create_index('ix_company_offboardings_state', 'company_offboardings', ['state', 'grace_until'])
    op.create_table(
        'offboarding_step_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('offboarding_id', sa.UUID(), nullable=False),
        sa.Column('step', sa.Text(), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('attempt', sa.Integer(), server_default='1', nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("outcome IN ('started', 'succeeded', 'skipped', 'failed')",
                           name='ck_offboarding_step_log_outcome'),
        sa.ForeignKeyConstraint(['offboarding_id'], ['company_offboardings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_offboarding_step_log_offboarding', 'offboarding_step_log', ['offboarding_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_offboarding_step_log_offboarding', table_name='offboarding_step_log')
    op.drop_table('offboarding_step_log')
    op.drop_index('ix_company_offboardings_state', table_name='company_offboardings')
    op.drop_index('uq_company_offboardings_open', table_name='company_offboardings')
    op.drop_table('company_offboardings')
    op.drop_column('companies', 'is_test')
