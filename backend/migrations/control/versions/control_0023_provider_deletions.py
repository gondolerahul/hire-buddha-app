"""provider deletion requests (docs/phase15/14_connector_approvals/10, META-E1)

``provider_deletion_requests``: one row per deletion a provider asked for
(Meta's data deletion callback), keyed by the confirmation code the provider
shows the person; the public status page reads it. The person's id is kept only
as a SHA-256 hash.

Revision ID: control_0023_provider_deletions
Revises: control_0022_offboarding
Create Date: 2026-10-28 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'control_0023_provider_deletions'
down_revision: Union[str, Sequence[str], None] = 'control_0022_offboarding'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_deletion_requests',
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('person_sha256', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('connections', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('code'),
        info={'plane': 'control'},
    )
    op.create_index('ix_provider_deletion_requests_received', 'provider_deletion_requests', ['received_at'],
                    unique=False)


def downgrade() -> None:
    op.drop_index('ix_provider_deletion_requests_received', table_name='provider_deletion_requests')
    op.drop_table('provider_deletion_requests')
