"""add onboarding, phone pool, and lead queue (self-heal)

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-05-05

Adds:
  - onboarding_status, onboarding_metadata, default_daily_credits to companies
  - phone_number_pool table (legacy; replaced by phone_numbers)
  - lead_queue table (self-heal for skipped migration u1v2w3x4y5z6)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'y2z3a4b5c6d7'
down_revision = 'x1y2z3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # --- Companies: add onboarding columns (idempotent) ---
    company_cols = [c['name'] for c in inspector.get_columns('companies')]
    if 'onboarding_status' not in company_cols:
        op.add_column('companies', sa.Column('onboarding_status', sa.String(), server_default='pending'))
    if 'onboarding_metadata' not in company_cols:
        op.add_column('companies', sa.Column('onboarding_metadata', postgresql.JSONB(), nullable=True))
    if 'default_daily_credits' not in company_cols:
        op.add_column('companies', sa.Column('default_daily_credits', sa.String(), nullable=True))

    # --- Phone Number Pool table (legacy, skip if already exists) ---
    if 'phone_number_pool' not in existing_tables:
        op.create_table(
            'phone_number_pool',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('phone_number', sa.String(20), unique=True, nullable=False),
            sa.Column('provider', sa.String(20), nullable=False),
            sa.Column('country_code', sa.String(5), nullable=False, server_default='+91'),
            sa.Column('status', sa.String(20), server_default='available'),
            sa.Column('label', sa.String(100), nullable=True),
            sa.Column('claimed_by_company_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('companies.id'), nullable=True),
            sa.Column('claimed_at', sa.DateTime(), nullable=True),
            sa.Column('claimed_by_user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=True),
            sa.Column('monthly_cost_usd', sa.Numeric(10, 4), nullable=True),
            sa.Column('provider_sid', sa.String(100), nullable=True),
            sa.Column('capabilities', postgresql.JSONB(), nullable=True),
            sa.Column('added_by_user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=False),
            sa.Column('notes', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        )

    # --- Self-heal: create lead_queue if missing ---
    # Migration u1v2w3x4y5z6 should have created this, but on databases
    # where alembic_version was stamped past it without actually running
    # the DDL, the table will be absent.  Create it now.
    if 'lead_queue' not in existing_tables:
        op.create_table(
            'lead_queue',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('company_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('agent_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('hierarchical_entities.id'), nullable=False),
            sa.Column('lead_id', sa.String(255), nullable=False),
            sa.Column('phone', sa.String(20), nullable=False),
            sa.Column('lead_data', postgresql.JSONB(), nullable=False),
            sa.Column('ad_source', sa.String(100), nullable=True),
            sa.Column('project_id', sa.String(100), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('priority', sa.Integer, nullable=False, server_default='5'),
            sa.Column('attempt_count', sa.Integer, nullable=False, server_default='0'),
            sa.Column('max_attempts', sa.Integer, nullable=False, server_default='3'),
            sa.Column('last_error', sa.Text, nullable=True),
            sa.Column('correlation_id', sa.String(100), nullable=True),
            sa.Column('voice_session_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('voice_sessions.id'), nullable=True),
            sa.Column('call_outcome', postgresql.JSONB(), nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=False,
                      server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime, nullable=False,
                      server_default=sa.text('now()')),
            sa.Column('processed_at', sa.DateTime, nullable=True),
            sa.UniqueConstraint('company_id', 'lead_id', name='uq_lead_queue_company_lead'),
        )
        op.create_index(
            'idx_lead_queue_pending', 'lead_queue',
            ['company_id', 'status', 'priority', 'created_at'],
            postgresql_where=sa.text("status = 'pending'"),
        )
        op.create_index(
            'idx_lead_queue_voice_session', 'lead_queue',
            ['voice_session_id'],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'lead_queue' in existing_tables:
        op.drop_index('idx_lead_queue_voice_session', table_name='lead_queue')
        op.drop_index('idx_lead_queue_pending', table_name='lead_queue')
        op.drop_table('lead_queue')
    if 'phone_number_pool' in existing_tables:
        op.drop_table('phone_number_pool')
    op.drop_column('companies', 'default_daily_credits')
    op.drop_column('companies', 'onboarding_metadata')
    op.drop_column('companies', 'onboarding_status')

