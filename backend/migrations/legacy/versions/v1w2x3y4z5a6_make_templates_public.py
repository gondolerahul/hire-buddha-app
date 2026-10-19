"""No-op — templates are identified by is_template=True, company_id stays NOT NULL

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-05-06

Originally intended to set company_id=NULL for templates, but the column has
a NOT NULL constraint.  Templates are identified by is_template=True and
remain company-scoped (owned by the app admin's company).  Clone operations
copy them into the requesting user's company.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'v1w2x3y4z5a6'
down_revision = 'u1v2w3x4y5z6'
branch_labels = None
depends_on = None


def upgrade():
    """No-op — templates stay company-scoped via is_template=True."""
    pass


def downgrade():
    pass
