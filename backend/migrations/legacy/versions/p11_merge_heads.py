"""Phase 11 — merge with the parallel onboarding/phone_pool chain.

The Phase 11 migration chain branches at ``x1y2z3a4b5c6`` (the unified
CORTEX memory v2 schema): one descendant is ``y2z3a4b5c6d7`` (onboarding +
phone pool, shipped pre-Phase-11), the other is the
``p11t08_usage_attr → … → p11t09_drop_flags`` chain. Alembic refuses to
``upgrade head`` while two heads exist, so this is the standard merge
revision with no schema changes of its own.

Revision ID: p11_merge_2026_05_28
Revises: p11t09_drop_flags, y2z3a4b5c6d7
Create Date: 2026-05-28
"""
from __future__ import annotations


revision = "p11_merge_2026_05_28"
down_revision = ("p11t09_drop_flags", "y2z3a4b5c6d7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
