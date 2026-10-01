"""Entity types are the six levels of the hierarchy (R1)

Revision ID: r1_entity_levels
Revises: ep13_run_row_hygiene
Create Date: 2026-10-01

``hierarchical_entities.type`` was a plain varchar: the API refused anything
outside the four modelled types, but the database took any value, and a read
path had to present unknown rows ("LOOP") as PROCESS so the Entity Library did
not 500. LOOP (a department or function) and GRAPH (the entire business) are
now levels 5 and 6 of the hierarchy, and the column is held to the six.

The constraint is added ``NOT VALID`` — new and updated rows are checked at
once without scanning the table under a lock — and validated in the same
migration when no row holds another value. A database that does hold one keeps
the constraint unvalidated (the read path still presents those rows as
PROCESS); ``ALTER TABLE hierarchical_entities VALIDATE CONSTRAINT
ck_hierarchical_entities_type`` completes it once they are corrected.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "r1_entity_levels"
down_revision: Union[str, Sequence[str], None] = "ep13_run_row_hygiene"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEVELS = "('ACTION', 'SKILL', 'AGENT', 'PROCESS', 'LOOP', 'GRAPH')"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hierarchical_entities ADD CONSTRAINT ck_hierarchical_entities_type "
        f"CHECK (type IN {_LEVELS}) NOT VALID"
    )
    op.execute(
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM hierarchical_entities WHERE type NOT IN {_LEVELS}) THEN "
        "ALTER TABLE hierarchical_entities VALIDATE CONSTRAINT ck_hierarchical_entities_type; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.drop_constraint("ck_hierarchical_entities_type", "hierarchical_entities", type_="check")
