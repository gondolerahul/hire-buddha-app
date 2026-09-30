"""Drop the legacy assets table and call_content.audio_asset_id (DM-10)

Revision ID: dm10_drop_legacy_assets
Revises: dm08_tool_name_per_company
Create Date: 2026-10-01

``h1i2j3k4l5m6`` copied every ``assets`` row into ``artifacts`` and pointed
``call_content`` at ``audio_artifact_id``, leaving ``assets`` and
``call_content.audio_asset_id`` "for one release, dropped after verification".
That follow-up never came. Nothing has read or written either since: no model
maps them.

The copy is verified before anything is dropped: if an ``assets`` row has no
``artifacts`` row with its id, the upgrade stops instead of losing it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dm10_drop_legacy_assets"
down_revision: Union[str, Sequence[str], None] = "dm08_tool_name_per_company"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "assets" in tables:
        missing = bind.execute(sa.text(
            "SELECT count(*) FROM assets a WHERE NOT EXISTS (SELECT 1 FROM artifacts r WHERE r.id = a.id)"
        )).scalar_one()
        if missing:
            raise RuntimeError(
                f"{missing} assets row(s) were never copied to artifacts; copy them "
                "(see h1i2j3k4l5m6's INSERT) before running dm10_drop_legacy_assets"
            )
    columns = {c["name"] for c in sa.inspect(bind).get_columns("call_content")}
    if "audio_asset_id" in columns:
        # Any reference the earlier migration did not carry over, where the artifact exists.
        op.execute("""
            UPDATE call_content c SET audio_artifact_id = c.audio_asset_id
            WHERE c.audio_artifact_id IS NULL AND c.audio_asset_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM artifacts r WHERE r.id = c.audio_asset_id)
        """)
        op.drop_column("call_content", "audio_asset_id")
    if "assets" in tables:
        op.drop_table("assets")


def downgrade() -> None:
    # The data lives in artifacts; recreate the empty shapes only.
    op.create_table(
        "assets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("asset_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.add_column("call_content", sa.Column("audio_asset_id", sa.UUID(), sa.ForeignKey("assets.id"), nullable=True))
