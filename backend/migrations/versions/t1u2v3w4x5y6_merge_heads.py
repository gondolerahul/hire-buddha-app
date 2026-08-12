"""Merge heads: billing config fix + legacy field removal

Revision ID: t1u2v3w4x5y6
Revises: 2999001a9221, s1t2u3v4w5x6
Create Date: 2026-04-16

Merges two independent migration branches into a single head.
"""
from alembic import op

revision = 't1u2v3w4x5y6'
down_revision = ('2999001a9221', 's1t2u3v4w5x6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
