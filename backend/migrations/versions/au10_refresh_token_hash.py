"""Store refresh tokens as SHA-256 hashes, not in plaintext (AU-10)

Revision ID: au10_refresh_token_hash
Revises: bc03_tier_razorpay_plan
Create Date: 2026-09-30

``refresh_tokens.token`` held each 7-day session credential as-is, so any read
of the table — a backup, a log, an injection elsewhere — was a set of working
sessions for every active user. The column becomes ``token_hash``, the hex
SHA-256 of the token. Existing rows are hashed in place, so signed-in users
stay signed in.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "au10_refresh_token_hash"
down_revision: Union[str, Sequence[str], None] = "bc03_tier_razorpay_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("token_hash", sa.String(64), nullable=True))
    op.execute("UPDATE refresh_tokens SET token_hash = encode(sha256(convert_to(token, 'UTF8')), 'hex')")
    op.alter_column("refresh_tokens", "token_hash", nullable=False)
    op.drop_index("ix_refresh_tokens_token", table_name="refresh_tokens", if_exists=True)
    op.drop_column("refresh_tokens", "token")
    op.create_unique_constraint("uq_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])


def downgrade() -> None:
    # A hash cannot be turned back into a token: every session ends.
    op.execute("DELETE FROM refresh_tokens")
    op.drop_constraint("uq_refresh_tokens_token_hash", "refresh_tokens", type_="unique")
    op.drop_column("refresh_tokens", "token_hash")
    op.add_column("refresh_tokens", sa.Column("token", sa.String(), nullable=False))
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True)
