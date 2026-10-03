"""The platform schema's drift is real and acted on; its static part is built once
(P10.6 — MI-19, MI-I4).

``schema_version`` hashed ``compiled_at``, so every compile "drifted"; drift was
compared only inside one compiler instance (every caller builds a new one), and
nothing acted on it. Every compile also rebuilt sections that change only with
the code.
"""
from __future__ import annotations

import uuid

import pytest

import src.ai.meta.platform_schema_compiler as compiler_mod
import src.ai.meta.schema_drift as drift
from src.ai.meta.platform_schema_compiler import PlatformSchemaCompiler


class _Redis:
    def __init__(self):
        self.store, self.deleted = {}, []

    async def getset(self, key, value):
        old = self.store.get(key)
        self.store[key] = value
        return old

    async def delete(self, key):
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_the_version_is_the_content_not_the_clock():
    a = await PlatformSchemaCompiler().compile(include_tenant_tools=False)
    b = await PlatformSchemaCompiler().compile(include_tenant_tools=False)
    assert a["schema_version"] == b["schema_version"]
    changed = dict(a, tools=a["tools"][1:])
    assert drift.schema_version(changed) != a["schema_version"]


@pytest.mark.asyncio
async def test_drift_drops_the_companys_manifest_and_says_so(monkeypatch):
    import src.ai.core.events as events

    seen, redis, company = [], _Redis(), uuid.uuid4()
    monkeypatch.setattr(events, "event", lambda name, **kw: seen.append((name, kw)))

    assert await drift.note_schema_version(company, "v1", redis) is False     # first sight
    assert await drift.note_schema_version(company, "v1", redis) is False     # unchanged
    assert await drift.note_schema_version(company, "v2", redis) is True
    assert redis.deleted == [f"meta:manifest:{company}"]
    assert seen == [("meta.schema.drift", {"company_id": str(company), "previous": "v1", "version": "v2"})]


@pytest.mark.asyncio
async def test_the_static_sections_are_built_once(monkeypatch):
    calls = []
    original = PlatformSchemaCompiler._compile_step_types

    def counting(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(compiler_mod, "_STATIC_SECTIONS", None)
    monkeypatch.setattr(PlatformSchemaCompiler, "_compile_step_types", counting)
    first = await PlatformSchemaCompiler().compile(include_tenant_tools=False)
    first["step_types"].clear()                      # a caller's edit does not leak back
    second = await PlatformSchemaCompiler().compile(include_tenant_tools=False)
    assert len(calls) == 1 and second["step_types"]
