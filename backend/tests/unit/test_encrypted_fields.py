"""AU-24: the key rotation covers every encrypted column a model declares.

``common.encrypted_fields`` lists what ``scripts/rotate_encryption_key.py``
re-encrypts. A column added without being listed would keep its old key after a
rotation and stop decrypting.
"""
from __future__ import annotations

from src.common.encrypted_fields import ENCRYPTED_COLUMNS
from src.common.orm_models import import_all_models


def test_every_encrypted_column_is_rotated() -> None:
    declared = set()
    for metadata in import_all_models():
        for table in metadata.tables.values():
            for column in table.columns:
                if "encrypted" in column.name:
                    declared.add((table.name, column.name))
    import importlib
    listed = {
        (getattr(importlib.import_module(module), name).__tablename__, column)
        for module, name, column in ENCRYPTED_COLUMNS
    }
    assert declared == listed
