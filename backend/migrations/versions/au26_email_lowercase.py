"""User emails are stored lower-case, one account per address (AU-26)

Revision ID: au26_email_lowercase
Revises: dm12_timestamptz
Create Date: 2026-10-01

``ix_users_email`` is unique on the text as typed, and ``EmailStr`` lower-cases
only the domain, so "Owner@x.com" and "owner@x.com" could be two accounts, and
signing in needed the case used at sign-up. Inputs are now lower-cased; this
lower-cases stored addresses and adds ``CHECK (email = lower(email))``.

If two accounts already differ only in case, the upgrade stops and names them:
merging accounts is a decision, not a migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "au26_email_lowercase"
down_revision: Union[str, Sequence[str], None] = "dm12_timestamptz"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    clashes = op.get_bind().execute(sa.text(
        "SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1"
    )).scalars().all()
    if clashes:
        raise RuntimeError(f"accounts differ only in the case of their email: {sorted(clashes)}; "
                           "merge or rename them, then upgrade")
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")
    op.create_check_constraint("ck_users_email_lowercase", "users", "email = lower(email)")


def downgrade() -> None:
    op.drop_constraint("ck_users_email_lowercase", "users", type_="check")
