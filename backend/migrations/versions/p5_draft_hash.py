"""A draft may match a version while it is edited; published versions stay unique

Revision ID: p5_draft_hash
Revises: p5_entity_versions
Create Date: 2026-10-02

``uq_entity_versions_content`` made every version's content unique, so a new
draft — which starts as a copy of its base, to add files say — was refused
before it could be edited. Uniqueness now holds among published versions
only; publishing a draft that matches one is refused by the application.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p5_draft_hash"
down_revision: Union[str, Sequence[str], None] = "p5_entity_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_entity_versions_content", "entity_versions", type_="unique")
    op.create_index("ix_entity_versions_content", "entity_versions", ["entity_id", "content_hash"])
    op.create_index("uq_entity_versions_published_content", "entity_versions", ["entity_id", "content_hash"],
                    unique=True, postgresql_where=sa.text("published"))


def downgrade() -> None:
    op.drop_index("uq_entity_versions_published_content", table_name="entity_versions")
    op.drop_index("ix_entity_versions_content", table_name="entity_versions")
    op.create_unique_constraint("uq_entity_versions_content", "entity_versions", ["entity_id", "content_hash"])
