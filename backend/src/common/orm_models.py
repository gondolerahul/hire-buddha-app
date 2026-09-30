"""Every module that declares ORM tables, and the metadata they populate.

A table exists in ``Base.metadata`` only once its module has been imported.
Alembic's ``env.py`` and the schema census both need *every* table, so both call
``import_all_models()`` instead of keeping their own import lists — ``env.py``'s
list had already lost ``phone_pool_models``, so autogenerate could not see
``phone_numbers`` at all. ``tests/unit/test_orm_model_registry.py`` fails when a
module that declares ``__tablename__`` is missing from ``MODEL_MODULES``.
"""
from __future__ import annotations

import importlib

from sqlalchemy import MetaData

MODEL_MODULES: tuple[str, ...] = (
    "src.auth.models",
    "src.billing.billing_models",
    "src.config.models",
    "src.ai.orm.document",
    "src.ai.orm.entity",
    "src.ai.orm.execution",
    "src.ai.orm.tools",
    "src.ai.orm.trace",
    "src.ai.orm.trust",
    "src.ai.orm.usage",
    "src.ai.artifact_models",
    "src.ai.campaign_models",
    "src.ai.email_models",
    "src.ai.lead_queue_model",
    "src.ai.social_models",
    "src.mobile.models",
    "src.voice.models",
    "src.voice.phone_pool_models",
    "cortex_memory.models",
)


def import_all_models() -> list[MetaData]:
    """Import every model module; return the host's and the CORTEX package's metadata.

    The CORTEX tables live on the ``cortex_memory`` package's own declarative
    ``Base``, so there are two ``MetaData`` objects, not one.
    """
    for module in MODEL_MODULES:
        importlib.import_module(module)
    import cortex_memory
    from src.common.database import Base

    return [Base.metadata, cortex_memory.metadata]
