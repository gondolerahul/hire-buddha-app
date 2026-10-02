"""First-party social SKILLs are data (P6.3, R2).

With the social tools collapsed into ``social_api`` (P6.2), platform knowledge
lives in one SKILL per platform: how to work it, its rules, what to report.
Real Postgres, rolled back.
"""
from __future__ import annotations

import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import src.ai.tools  # noqa: F401
from src.ai.schemas.entity import HierarchicalEntityCreateRequest
from src.ai.tools.social.social_api import SOCIAL_PLATFORMS, operations

pytestmark = pytest.mark.needs_db

SEED = Path(__file__).resolve().parents[2] / "scripts" / "seeds" / "default_entities" / "SeedSocialSkills"
sys.path.insert(0, str(SEED))
import create_social_skills  # noqa: E402
from skills import PLATFORMS, SKILLS  # noqa: E402


def test_one_valid_skill_per_platform_granting_only_social_api():
    assert sorted(p["platform"] for p in PLATFORMS) == sorted(SOCIAL_PLATFORMS)
    for payload in SKILLS:
        HierarchicalEntityCreateRequest(**payload)           # strict: an unknown key is a 422
        assert payload["type"] == "SKILL"
        assert payload["capabilities"]["tools"] == [{"tool_id": "social_api"}]
        assert '"describe"' in payload["identity"]["system_prompt"]


@pytest.mark.parametrize("p", PLATFORMS, ids=[p["platform"] for p in PLATFORMS])
def test_the_guidance_names_only_real_operations_and_parameters(p):
    ops = operations()[p["platform"]]
    known = set(ops)
    for op in ops.values():
        known |= set(op.get_function_schema()["parameters"]["properties"])
    named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", p["guidance"]))
    assert named <= known, f"{p['platform']}: {sorted(named - known)}"


@pytest.mark.asyncio
async def test_the_seed_creates_them_once(db, monkeypatch):
    import src.common.database as database
    from src.auth.models import Company

    @asynccontextmanager
    async def _session():
        yield db
    monkeypatch.setattr(database, "AsyncSessionLocal", _session)
    c = Company(name=f"p63-{uuid.uuid4().hex[:6]}", type="TENANT", status="active")
    db.add(c)
    await db.flush()

    first = await create_social_skills.create(c.id)
    again = await create_social_skills.create(c.id)
    assert sorted(first) == sorted(s["name"] for s in SKILLS) and again == []
