"""speech and music integration categories

Revision ID: control_0004_media_categories
Revises: control_0003_domains
Create Date: 2026-10-20

Gemini TTS and Lyria become configurable models: the registry's category
check admits SPEECH_GENERATION and MUSIC_GENERATION (ServiceCategory).

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'control_0004_media_categories'
down_revision: Union[str, Sequence[str], None] = 'control_0003_domains'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BEFORE = ("'LLM', 'LLM_LIVE', 'EMBEDDING', 'IMAGE_GENERATION', 'VIDEO_GENERATION', 'SANDBOX', "
           "'COMMUNICATION', 'EMAIL', 'SOCIAL_MEDIA', 'API_TOOL', 'OAUTH_APP', 'OTHER'")
_AFTER = ("'LLM', 'LLM_LIVE', 'EMBEDDING', 'IMAGE_GENERATION', 'VIDEO_GENERATION', 'SPEECH_GENERATION', "
          "'MUSIC_GENERATION', 'SANDBOX', 'COMMUNICATION', 'EMAIL', 'SOCIAL_MEDIA', 'API_TOOL', 'OAUTH_APP', "
          "'OTHER'")


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_integration_registry_service_category', 'integration_registry', type_='check')
    op.create_check_constraint('ck_integration_registry_service_category', 'integration_registry',
                               f"service_category IN ({_AFTER})")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM integration_registry WHERE service_category IN ('SPEECH_GENERATION', 'MUSIC_GENERATION')")
    op.drop_constraint('ck_integration_registry_service_category', 'integration_registry', type_='check')
    op.create_check_constraint('ck_integration_registry_service_category', 'integration_registry',
                               f"service_category IN ({_BEFORE})")
