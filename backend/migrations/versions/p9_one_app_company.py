"""At most one platform (APP) company (LP-21)

Revision ID: p9_one_app_company
Revises: p9_service_category
Create Date: 2026-10-03

Every tenant falls back to the APP company's integrations, prices and task
defaults, and six readers took ``LIMIT 1`` of ``type = 'APP'`` with no order,
so a second APP company split the platform non-deterministically. A partial
unique index keeps a second one out. A database that already holds two keeps
running — ``platform_company_id`` orders by ``created_at, id`` — and is told so;
the index is built once the duplicate is merged.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p9_one_app_company"
down_revision: Union[str, Sequence[str], None] = "p9_service_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF (SELECT count(*) FROM companies WHERE type = 'APP') > 1 THEN "
        "RAISE WARNING 'companies holds more than one APP company; uq_companies_one_app not built. "
        "Merge them, then rerun this migration''s CREATE UNIQUE INDEX.'; "
        "ELSE "
        "CREATE UNIQUE INDEX uq_companies_one_app ON companies ((type)) WHERE type = 'APP'; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_companies_one_app")
