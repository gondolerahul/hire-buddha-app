"""GH-20: the flags page asks why each flag has its value — for the caller's own company.

``GET /api/v1/ai/admin/feature_flags/explain`` answers every declared flag
with its value and tier (``explain_flags``, held to the resolver in
``tests/integration/test_flag_explain.py``). A tenant admin sees their own
company; ``app_admin`` may name another.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.ai.api import admin


@pytest.fixture
def explained(monkeypatch):
    asked = []

    async def _explain(db, company_id=None, entity_id=None):
        asked.append(company_id)
        return [{"flag_key": "bandit.enabled", "kind": "boolean", "value": True, "source": "env"}]

    monkeypatch.setattr("src.ai.core.flag_explain.explain_flags", _explain)
    return asked


@pytest.mark.asyncio
async def test_a_tenant_admin_sees_their_own_company(explained):
    own = uuid.uuid4()
    user = SimpleNamespace(company_id=own, role="tenant_admin")
    body = await admin.explain_feature_flags(company_id=None, db=object(), user=user)
    assert explained == [own]
    assert body["flags"][0]["source"] == "env" and body["company_id"] == str(own)


@pytest.mark.asyncio
async def test_a_tenant_admin_cannot_ask_about_another(explained):
    user = SimpleNamespace(company_id=uuid.uuid4(), role="tenant_admin")
    with pytest.raises(HTTPException) as refused:
        await admin.explain_feature_flags(company_id=uuid.uuid4(), db=object(), user=user)
    assert refused.value.status_code == 403 and explained == []


@pytest.mark.asyncio
async def test_app_admin_may_ask_about_any(explained):
    other = uuid.uuid4()
    user = SimpleNamespace(company_id=uuid.uuid4(), role="app_admin")
    await admin.explain_feature_flags(company_id=other, db=object(), user=user)
    assert explained == [other]
