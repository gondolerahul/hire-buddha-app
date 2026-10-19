"""merge_campaign_and_assets_billing_branches

Revision ID: 39b85529e254
Revises: g1h2i3j4k5l6
Create Date: 2026-02-23 17:21:10.349003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39b85529e254'
down_revision: Union[str, Sequence[str], None] = 'g1h2i3j4k5l6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
