"""Every task type the code resolves is one the API accepts (P9.3 — LP-09).

``embedding``, ``vision`` and ``goal_validation`` were resolved by live code
(the embedding service, the video gateway, the goal check) but missing from
``TASK_TYPES``, so ``POST /config/task-defaults`` answered 422 and the AI config
page's Embedding card could never be saved.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi import HTTPException

from src.config.models import TASK_TYPES

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"

# ``task_type="x"``, ``task_type == "x"``, ``task_type: str = "x"`` and
# ``*_TASK = "x"`` constants.
_LITERAL = re.compile(r"""(?:task_type\s*(?::\s*\w+\s*)?==?|_TASK\s*=)\s*["']([a-z0-9_]+)["']""")


def _task_types_in_code() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in SRC.rglob("*.py"):
        for name in _LITERAL.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, []).append(str(path.relative_to(SRC)))
    return found


def test_every_task_type_the_code_resolves_is_accepted():
    found = _task_types_in_code()
    assert {"embedding", "vision", "goal_validation", "text_generation"} <= set(found)
    assert {name: files for name, files in found.items() if name not in TASK_TYPES} == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", ["embedding", "vision", "goal_validation"])
async def test_the_api_accepts_them(task_type, monkeypatch):
    from uuid import uuid4

    from src.config import router as config_router
    from src.config.schemas import ModelTaskDefaultCreate

    saved = {}

    class _Service:
        def __init__(self, _db):
            pass

        async def set_task_default(self, **kw):
            saved.update(kw)
            raise HTTPException(status_code=418, detail="stop here")

    monkeypatch.setattr(config_router, "ConfigService", _Service)
    user = type("U", (), {"company_id": uuid4()})()
    with pytest.raises(HTTPException) as err:
        await config_router.set_task_default(
            ModelTaskDefaultCreate(task_type=task_type, integration_id=uuid4()), user, None)
    assert err.value.status_code == 418  # past the 422 check
    assert saved["task_type"] == task_type
