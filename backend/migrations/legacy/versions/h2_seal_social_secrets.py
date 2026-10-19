"""Social connections' client secrets are stored encrypted (AU-25)

Revision ID: h2_seal_social_secrets
Revises: h2_webhook_endpoints
Create Date: 2026-10-07

``social_connections.oauth_metadata`` held the platform app's ``client_secret``
(and Google Ads' ``developer_token``) as plain JSON beside access tokens that
were encrypted. Every secret-named key moves, encrypted with the current
``ENCRYPTION_MASTER_KEY``, under ``oauth_metadata.secrets_encrypted`` —
``ai.social_connection_service.seal_oauth_metadata``. Downgrade decrypts them back.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h2_seal_social_secrets"
down_revision: Union[str, Sequence[str], None] = "h2_webhook_endpoints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rewrite(transform) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, oauth_metadata FROM social_connections WHERE oauth_metadata IS NOT NULL"
    )).fetchall()
    for row_id, metadata in rows:
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        new = transform(metadata)
        if new != metadata:
            bind.execute(sa.text("UPDATE social_connections SET oauth_metadata = CAST(:m AS JSONB) WHERE id = :id"),
                         {"m": json.dumps(new), "id": row_id})


def upgrade() -> None:
    from src.ai.social_connection_service import seal_oauth_metadata
    _rewrite(seal_oauth_metadata)


def downgrade() -> None:
    from src.ai.social_connection_service import open_oauth_metadata
    _rewrite(open_oauth_metadata)
