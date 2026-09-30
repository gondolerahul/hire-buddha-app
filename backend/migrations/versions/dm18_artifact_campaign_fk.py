"""artifacts.campaign_id references campaigns, as its name says (DM-18)

Revision ID: dm18_artifact_campaign_fk
Revises: dm11_numeric_columns
Create Date: 2026-10-01

The column's foreign key pointed at ``hierarchical_entities``: uploading a file
for a real campaign — the only writer is the artifacts upload API, whose form
field is a campaign id — failed the key, and an entity id was accepted in its
place. The key now references ``campaigns`` (``ON DELETE SET NULL``). A stored
value that is not a campaign id is cleared first; it could only have been an
entity id.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "dm18_artifact_campaign_fk"
down_revision: Union[str, Sequence[str], None] = "dm11_numeric_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP CONSTRAINT IF EXISTS artifacts_campaign_id_fkey")
    op.execute("""
        UPDATE artifacts a SET campaign_id = NULL
        WHERE campaign_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM campaigns c WHERE c.id = a.campaign_id)
    """)
    op.create_foreign_key("artifacts_campaign_id_fkey", "artifacts", "campaigns",
                          ["campaign_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("artifacts_campaign_id_fkey", "artifacts", type_="foreignkey")
    op.execute("UPDATE artifacts SET campaign_id = NULL")
    op.create_foreign_key("artifacts_campaign_id_fkey", "artifacts", "hierarchical_entities",
                          ["campaign_id"], ["id"])
