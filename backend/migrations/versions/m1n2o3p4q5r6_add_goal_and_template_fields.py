"""Add goal and template fields to hierarchical_entities

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-03-09 07:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'm1n2o3p4q5r6'
down_revision: Union[str, None] = 'l1m2n3o4p5q6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add goal column — entity's objective for prompt generation
    op.add_column('hierarchical_entities',
                  sa.Column('goal', sa.Text(), nullable=True))

    # Add template fields
    op.add_column('hierarchical_entities',
                  sa.Column('is_template', sa.Boolean(),
                            server_default='false', nullable=False))
    op.add_column('hierarchical_entities',
                  sa.Column('template_source_id',
                            postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('hierarchical_entities',
                  sa.Column('created_by',
                            postgresql.UUID(as_uuid=True), nullable=True))

    # Foreign keys
    op.create_foreign_key(
        'fk_entities_template_source',
        'hierarchical_entities', 'hierarchical_entities',
        ['template_source_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_entities_created_by',
        'hierarchical_entities', 'users',
        ['created_by'], ['id'],
        ondelete='SET NULL',
    )

    # Index for fast template listing
    op.create_index(
        'ix_hierarchical_entities_is_template',
        'hierarchical_entities',
        ['is_template'],
    )


def downgrade() -> None:
    op.drop_index('ix_hierarchical_entities_is_template')
    op.drop_constraint('fk_entities_created_by', 'hierarchical_entities')
    op.drop_constraint('fk_entities_template_source', 'hierarchical_entities')
    op.drop_column('hierarchical_entities', 'created_by')
    op.drop_column('hierarchical_entities', 'template_source_id')
    op.drop_column('hierarchical_entities', 'is_template')
    op.drop_column('hierarchical_entities', 'goal')
