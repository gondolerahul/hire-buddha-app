"""Integration categories are one list (LP-11)

Revision ID: p9_service_category
Revises: p7_drop_source_trust
Create Date: 2026-10-03

``integration_registry.service_category`` was free text. The column comment
named ``IMAGE_GEN`` / ``VIDEO_GEN`` while the resolvers query
``IMAGE_GENERATION`` / ``VIDEO_GENERATION``, so a row made by the comment was
never found, and the credentials guide recommended three more (``SEARCH``,
``SCRAPING``, ``PAYMENT``). Those spellings are renamed, and the column is held
to ``ServiceCategory``.

The constraint is added ``NOT VALID`` and validated in the same migration when
no row holds another value (the pattern of ``r1_entity_levels``); a database
that does keeps it unvalidated until those rows are corrected.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p9_service_category"
down_revision: Union[str, Sequence[str], None] = "p7_drop_source_trust"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CATEGORIES = ("LLM", "LLM_LIVE", "EMBEDDING", "IMAGE_GENERATION", "VIDEO_GENERATION", "SANDBOX",
               "COMMUNICATION", "EMAIL", "SOCIAL_MEDIA", "API_TOOL", "OTHER")
_IN = "(" + ", ".join(f"'{c}'" for c in _CATEGORIES) + ")"
# The comment's and the credentials guide's spellings, and old fixtures'.
_RENAMES = {"IMAGE_GEN": "IMAGE_GENERATION", "VIDEO_GEN": "VIDEO_GENERATION", "API": "API_TOOL",
            "TOOL": "API_TOOL", "CUSTOM_API": "API_TOOL", "SEARCH": "API_TOOL", "SCRAPING": "API_TOOL",
            "PAYMENT": "OTHER"}


def upgrade() -> None:
    # Case first ('llm' → 'LLM'), then the old spellings.
    op.execute(f"UPDATE integration_registry SET service_category = upper(service_category) "
               f"WHERE upper(service_category) IN {_IN} AND service_category <> upper(service_category)")
    for old, new in _RENAMES.items():
        op.execute(f"UPDATE integration_registry SET service_category = '{new}' "
                   f"WHERE upper(service_category) = '{old}'")
    op.execute("ALTER TABLE integration_registry ADD CONSTRAINT ck_integration_registry_service_category "
               f"CHECK (service_category IN {_IN}) NOT VALID")
    op.execute(
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM integration_registry WHERE service_category NOT IN {_IN}) THEN "
        "ALTER TABLE integration_registry VALIDATE CONSTRAINT ck_integration_registry_service_category; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.drop_constraint("ck_integration_registry_service_category", "integration_registry", type_="check")
