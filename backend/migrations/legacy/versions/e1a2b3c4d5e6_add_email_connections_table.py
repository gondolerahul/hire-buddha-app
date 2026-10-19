"""Add email_connections table

Revision ID: e1a2b3c4d5e6
Revises: 9bf859b51116
Create Date: 2026-02-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5e6'
down_revision: Union[str, None] = '9bf859b51116'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('email_address', sa.String(), nullable=False),
        sa.Column('encrypted_app_password', sa.Text(), nullable=False),
        sa.Column('imap_host', sa.String(), nullable=False, server_default='imap.gmail.com'),
        sa.Column('imap_port', sa.Integer(), nullable=False, server_default='993'),
        sa.Column('smtp_host', sa.String(), nullable=False, server_default='smtp.gmail.com'),
        sa.Column('smtp_port', sa.Integer(), nullable=False, server_default='587'),
        sa.Column('provider_type', sa.String(), nullable=False, server_default='gmail'),
        sa.Column('folder_prefix', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_connected_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    
    # Add unique constraint: one email per company
    op.create_unique_constraint(
        'uq_email_connection_company_email',
        'email_connections',
        ['company_id', 'email_address']
    )


def downgrade() -> None:
    op.drop_table('email_connections')
