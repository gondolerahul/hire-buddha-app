"""Two numeric values stored as text become numbers (DM-11)

Revision ID: dm11_numeric_columns
Revises: dm10_drop_legacy_assets
Create Date: 2026-10-01

``documents.file_size`` (bytes) and ``companies.default_daily_credits`` were
``VARCHAR``: every sum or sort had to cast, and nothing stopped a non-number.
They become ``BIGINT`` and ``NUMERIC(10,4)`` (the scale of
``billing_config.default_daily_credits``, which fills it). A value that is not
a number becomes NULL rather than failing the upgrade — both columns are
nullable and both mean "unknown / use the default" when empty.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "dm11_numeric_columns"
down_revision: Union[str, Sequence[str], None] = "dm10_drop_legacy_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(r"""
        ALTER TABLE documents ALTER COLUMN file_size TYPE BIGINT
        USING CASE WHEN btrim(file_size) ~ '^[0-9]+$' THEN btrim(file_size)::bigint END
    """)
    op.execute(r"""
        ALTER TABLE companies ALTER COLUMN default_daily_credits TYPE NUMERIC(10, 4)
        USING CASE WHEN btrim(default_daily_credits) ~ '^-?[0-9]+(\.[0-9]+)?$'
                   THEN btrim(default_daily_credits)::numeric(10, 4) END
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE documents ALTER COLUMN file_size TYPE VARCHAR USING file_size::text")
    op.execute("ALTER TABLE companies ALTER COLUMN default_daily_credits TYPE VARCHAR USING default_daily_credits::text")
