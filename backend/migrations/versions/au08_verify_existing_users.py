"""Existing accounts count as verified when verification starts to block sign-in (AU-08)

Revision ID: au08_verify_existing_users
Revises: bc06_credit_holds
Create Date: 2026-09-30

From AU-08 an unverified account cannot sign in. No verification email had ever
been sent — nothing called the sender — so every self-registered account is
unverified through no fault of its own. They are marked verified here; accounts
created after this revision must verify.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "au08_verify_existing_users"
down_revision: Union[str, Sequence[str], None] = "bc06_credit_holds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET is_verified = true WHERE is_verified IS NOT TRUE")


def downgrade() -> None:
    # Which accounts were grandfathered is not recorded; nothing to undo.
    pass
