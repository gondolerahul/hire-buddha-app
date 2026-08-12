"""cortex_memory package — boundary + provider contract (Phase 12 `04` Stage B).

Verifies the extraction's core invariant (the package imports with **no host
dependency**), that the provider Protocols are satisfied by the reference
implementations, and that the host's ``scope_policy`` re-export shim still works.
"""
from __future__ import annotations

import pytest

import cortex_memory
from cortex_memory.providers import (
    EmbeddingProvider,
    LLMProvider,
    RunRegistry,
    UsageReporter,
)
from cortex_memory.providers_reference import (
    EchoLLMProvider,
    HashEmbeddingProvider,
    InMemoryRunRegistry,
    NullUsageReporter,
)


def test_package_has_no_host_imports() -> None:
    """The extraction's core invariant: no ``cortex_memory`` source file may
    import the host (``src.ai.*`` / ``src.*``)."""
    import pathlib

    pkg_dir = pathlib.Path(cortex_memory.__file__).parent
    offenders = []
    for py in pkg_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from src.", "import src.", "from src ", "import src")):
                offenders.append(f"{py.name}: {stripped}")
    assert not offenders, "cortex_memory must not import the host:\n" + "\n".join(offenders)


def test_reference_providers_satisfy_protocols() -> None:
    assert isinstance(EchoLLMProvider(), LLMProvider)
    assert isinstance(HashEmbeddingProvider(), EmbeddingProvider)
    assert isinstance(NullUsageReporter(), UsageReporter)
    assert isinstance(InMemoryRunRegistry(), RunRegistry)


@pytest.mark.asyncio
async def test_echo_llm_provider() -> None:
    res = await EchoLLMProvider().complete(system="sys", user="hello world")
    assert "hello world" in res.text
    assert res.model == "echo-llm"
    assert res.output_tokens > 0


@pytest.mark.asyncio
async def test_hash_embedding_provider_deterministic() -> None:
    p = HashEmbeddingProvider(dim=8)
    a = await p.embed(["alpha", "beta"])
    b = await p.embed(["alpha", "beta"])
    assert a.dimension == 8
    assert a.vectors == b.vectors  # deterministic
    assert a.char_count == len("alpha") + len("beta")


@pytest.mark.asyncio
async def test_in_memory_run_registry() -> None:
    reg = InMemoryRunRegistry()
    reg.add(cortex_memory.RunRef(run_id="r1", company_id="c1"))
    got = await reg.get_run("r1")
    assert got is not None and got.company_id == "c1"
    assert await reg.get_run("missing") is None


def test_scope_policy_exported_from_package_root() -> None:
    sp = cortex_memory.ScopePolicy.child_recursion_default()
    assert sp.can_read_outside is True and sp.can_write_outside is False
    assert issubclass(cortex_memory.ScopeViolation, RuntimeError)


def test_host_scope_policy_reexport_is_same_object() -> None:
    """The host shim re-exports the package's classes (identity, not a copy)."""
    from src.ai.memory.scope_policy import ScopePolicy, ScopeViolation

    assert ScopePolicy is cortex_memory.ScopePolicy
    assert ScopeViolation is cortex_memory.ScopeViolation


# ---------------------------------------------------------------------------
# Data layer (own Base + opaque-FK models + unified enum)
# ---------------------------------------------------------------------------


def test_models_on_package_base_with_three_tables() -> None:
    from cortex_memory.db import Base

    tables = set(Base.metadata.tables)
    assert {"cortex_trees", "cortex_nodes", "cortex_edges"} <= tables
    # The package Base must NOT contain host tables (it's self-contained).
    assert not any(t in tables for t in ("companies", "users", "execution_runs", "hierarchical_entities"))


def test_external_references_are_opaque_no_fk() -> None:
    """External refs (company/user/entity/run) are plain UUID columns with no
    ForeignKey to host tables (decision K5); internal refs keep their FKs."""
    from cortex_memory.models import CortexNode, CortexTree

    for col in ("company_id", "entity_id", "user_id", "app_id", "partner_id", "run_id"):
        assert not CortexTree.__table__.c[col].foreign_keys, f"{col} must be opaque"
    assert not CortexNode.__table__.c["execution_run_id"].foreign_keys
    # Internal tree/parent FKs are retained.
    assert CortexNode.__table__.c["tree_id"].foreign_keys
    assert CortexNode.__table__.c["parent_id"].foreign_keys


def test_host_and_package_share_one_cortex_node_type() -> None:
    from src.ai.memory.cortex_models import CortexNodeType as ModelEnum
    from src.ai.schemas.enums import CortexNodeType as SchemaEnum

    assert ModelEnum is cortex_memory.CortexNodeType
    assert SchemaEnum is cortex_memory.CortexNodeType
    # The unified enum is the full set (the old host schemas copy was a subset).
    assert "CHUNK" in cortex_memory.CortexNodeType.__members__
    assert "OBSERVATION" in cortex_memory.CortexNodeType.__members__


def test_provenance_roundtrips_via_package() -> None:
    p = cortex_memory.Provenance(source_type=cortex_memory.SourceType.TOOL, tool_id="web_search")
    ref = p.to_source_ref()
    back = cortex_memory.Provenance.from_source_ref(ref)
    assert back is not None and back.source_type == cortex_memory.SourceType.TOOL
    assert back.effective_trust_score() == 0.7
