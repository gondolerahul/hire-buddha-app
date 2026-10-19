"""users.token_version: end every session of a user at once (AU-05, AU-09, AU-12)

Revision ID: au05_token_version
Revises: au10_refresh_token_hash
Create Date: 2026-09-30

Access tokens carry the user's ``token_version`` as ``tv``; bumping it refuses
every access token issued before. Existing users start at 0.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "au05_token_version"
down_revision: Union[str, Sequence[str], None] = "au10_refresh_token_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
