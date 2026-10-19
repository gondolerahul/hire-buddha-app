"""Artifacts are stored by a neutral storage key (Phase 14 WS1 1.2)

Revision ID: p14_artifact_storage_key
Revises: h4_company_spend_cap
Create Date: 2026-10-17

Files move behind ``src/common/platform/storage``: an artifact records the
key its bytes are stored under (``<namespace>/<path>``), not a disk path, so
the same row works on local disk and on Azure Blob (tech spec §12.1, P-05).

Existing rows whose file sits under ``backend/artifact/`` get the key of that
file relative to it (``system-generated/<company>/<date>/<name>``), which the
``local_disk`` adapter, rooted at ``backend/artifact``, resolves to the same
file. Rows holding a provider URL (call recordings) keep a NULL key and are
proxied as before. The WS7 file mover rewrites keys into tenant containers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p14_artifact_storage_key"
down_revision: Union[str, Sequence[str], None] = "h4_company_spend_cap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("storage_key", sa.Text(), nullable=True))
    # Windows paths have backslashes; the key is what follows the last /artifact/.
    op.execute(r"""
        UPDATE artifacts
           SET storage_key = regexp_replace(replace(file_path, '\', '/'), '^.*/artifact/', '')
         WHERE storage_key IS NULL
           AND replace(file_path, '\', '/') ~ '/artifact/(user-uploads|system-generated)/[^/]'
           AND file_path !~ '^https?://'
    """)


def downgrade() -> None:
    op.drop_column("artifacts", "storage_key")
