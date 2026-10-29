"""connector data marks, conversations and opt-ins (docs/phase15/14_connector_approvals/10, wave 3)

Revision ID: tenant_platform_0006_data_rules
Revises: tenant_platform_0005_amounts
Create Date: 2026-10-29

* ``connector_data_marks`` (SH-E2): a run read through a connection; how long
  its provider lets that stay in the run's logs, traces, prompts and memory,
  and whether the run may save it to records. A nightly job removes it.
* ``messaging_conversations`` (META-E4): per customer of a Page, Instagram
  account or WhatsApp number — the last messages, the AI disclosure, a
  hand-off to a person.
* ``messaging_opt_ins`` (META-E5): a WhatsApp contact's agreement to messages
  the business starts, or refusal, and where it came from.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'tenant_platform_0006_data_rules'
down_revision: Union[str, Sequence[str], None] = 'tenant_platform_0005_amounts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('connector_data_marks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('connector_id', sa.Text(), nullable=False),
    sa.Column('tool_name', sa.Text(), nullable=False),
    sa.Column('operation', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('results', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('records', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('redacted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['run_id', 'company_id'], ['execution_runs.id', 'execution_runs.company_id'],
                            name='fk_connector_data_marks_run_company', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'tenant'}
    )
    op.create_index('uq_connector_data_marks_read', 'connector_data_marks',
                    ['run_id', 'connection_id', 'tool_name', 'operation'], unique=True)
    op.create_index('ix_connector_data_marks_due', 'connector_data_marks', ['expires_at'], unique=False,
                    postgresql_where=sa.text('redacted_at IS NULL'))
    op.create_index('ix_connector_data_marks_connection', 'connector_data_marks', ['connection_id'], unique=False)

    op.create_table('messaging_conversations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('account_id', sa.Text(), nullable=False),
    sa.Column('contact_id', sa.Text(), nullable=False),
    sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ai_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disclosed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('handed_off_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('handoff_reason', sa.Text(), nullable=True),
    sa.Column('handed_back_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('handed_back_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('messenger', 'instagram', 'whatsapp')",
                       name='ck_messaging_conversations_channel'),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'tenant'}
    )
    op.create_index('uq_messaging_conversations_contact', 'messaging_conversations',
                    ['company_id', 'channel', 'account_id', 'contact_id'], unique=True)
    op.create_index('ix_messaging_conversations_handed_off', 'messaging_conversations', ['company_id'],
                    unique=False, postgresql_where=sa.text('handed_off_at IS NOT NULL'))

    op.create_table('messaging_opt_ins',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('contact_id', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('recorded_by', sa.Text(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('messenger', 'instagram', 'whatsapp')", name='ck_messaging_opt_ins_channel'),
    sa.CheckConstraint("status IN ('in', 'out')", name='ck_messaging_opt_ins_status'),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'tenant'}
    )
    op.create_index('uq_messaging_opt_ins_contact', 'messaging_opt_ins', ['company_id', 'channel', 'contact_id'],
                    unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_messaging_opt_ins_contact', table_name='messaging_opt_ins')
    op.drop_table('messaging_opt_ins')
    op.drop_index('ix_messaging_conversations_handed_off', table_name='messaging_conversations')
    op.drop_index('uq_messaging_conversations_contact', table_name='messaging_conversations')
    op.drop_table('messaging_conversations')
    op.drop_index('ix_connector_data_marks_connection', table_name='connector_data_marks')
    op.drop_index('ix_connector_data_marks_due', table_name='connector_data_marks')
    op.drop_index('uq_connector_data_marks_read', table_name='connector_data_marks')
    op.drop_table('connector_data_marks')
