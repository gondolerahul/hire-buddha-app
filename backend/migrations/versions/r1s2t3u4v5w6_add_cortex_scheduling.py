"""Add CORTEX scheduling columns

Revision ID: r1s2t3u4v5w6
Revises: q1r2s3t4u5v6
Create Date: 2026-04-10

Adds resume_schedule and next_resume_at columns to cortex_trees
for supporting multi-day scheduled wake-ups (Gap #5).
"""
from alembic import op
import sqlalchemy as sa

revision = 'r1s2t3u4v5w6'
down_revision = 'q1r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('cortex_trees', sa.Column('resume_schedule', sa.String(100), nullable=True))
    op.add_column('cortex_trees', sa.Column('next_resume_at', sa.DateTime(), nullable=True))
    op.create_index('ix_cortex_trees_next_resume', 'cortex_trees', ['next_resume_at'],
                    postgresql_where=sa.text("next_resume_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index('ix_cortex_trees_next_resume', table_name='cortex_trees')
    op.drop_column('cortex_trees', 'next_resume_at')
    op.drop_column('cortex_trees', 'resume_schedule')
