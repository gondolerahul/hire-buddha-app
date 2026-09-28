"""Pure-logic tests for cortex_memory (no DB / LLM / host)."""
from __future__ import annotations

from uuid import uuid4

import pytest

import cortex_memory
from cortex_memory import (
    DEFAULT_TRUST_BY_SOURCE,
    CortexNodeType,
    GoalNode,
    Provenance,
    ScopePolicy,
    ScopeViolation,
    SourceType,
)
from cortex_memory._textutil import (
    parse_json_array,
    parse_json_object,
    strip_markdown_fences,
    truncate_for_storage,
)
from cortex_memory.domains import (
    DEFAULT_DOMAIN_WEIGHTS,
    DomainItem,
    DomainTreeBase,
    score_signals,
)
from cortex_memory.embedding import embed_node, embed_query, embed_texts
from cortex_memory.providers import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    RunRegistry,
    UsageReporter,
)
from cortex_memory.providers_reference import (
    EchoLLMProvider,
    HashEmbeddingProvider,
    InMemoryRunRegistry,
    NullUsageReporter,
)


# --------------------------------------------------------------------------- #
# package + version
# --------------------------------------------------------------------------- #


def test_version_and_exports() -> None:
    assert cortex_memory.__version__ == "0.1.0"
    for name in ("CortexService", "DreamingEngine", "MemoryAssemblyService",
                 "CortexTree", "Provenance", "ScopePolicy", "LLMProvider"):
        assert name in cortex_memory.__all__
        assert hasattr(cortex_memory, name)


# --------------------------------------------------------------------------- #
# enums
# --------------------------------------------------------------------------- #


def test_cortex_node_type_full_set() -> None:
    for v in ("root", "knowledge", "chunk", "observation", "pattern", "snapshot"):
        assert CortexNodeType(v).value == v
    assert len(list(CortexNodeType)) == 21


# --------------------------------------------------------------------------- #
# Provenance / DTOs
# --------------------------------------------------------------------------- #


def test_provenance_default_trust_and_roundtrip() -> None:
    for st, expected in DEFAULT_TRUST_BY_SOURCE.items():
        p = Provenance(source_type=SourceType(st))
        assert p.effective_trust_score() == expected
    p = Provenance(source_type=SourceType.TOOL, tool_id="web_search", trust_score=0.42, run_id=uuid4())
    ref = p.to_source_ref()
    assert ref["trust_score"] == 0.42 and ref["tool_id"] == "web_search"
    back = Provenance.from_source_ref(ref)
    assert back is not None and back.source_type is SourceType.TOOL


def test_provenance_trust_clamped() -> None:
    assert Provenance(source_type=SourceType.TOOL, trust_score=5.0).effective_trust_score() == 1.0
    assert Provenance(source_type=SourceType.TOOL, trust_score=-1.0).effective_trust_score() == 0.0


def test_provenance_from_bad_ref_is_none() -> None:
    assert Provenance.from_source_ref(None) is None
    assert Provenance.from_source_ref({"no": "source_type"}) is None
    assert Provenance.from_source_ref({"source_type": "not-a-type"}) is None


def test_goalnode_tree() -> None:
    root = GoalNode(goal="root")
    child = GoalNode(goal="child", depth=1, parent=root)
    root.children.append(child)
    assert not root.is_leaf() and child.is_leaf()
    d = root.to_dict()
    assert d["goal"] == "root" and d["children"][0]["goal"] == "child"


# --------------------------------------------------------------------------- #
# scope policy
# --------------------------------------------------------------------------- #


def test_scope_policy_defaults_and_child_recursion() -> None:
    strict = ScopePolicy()
    assert not strict.can_read_outside and strict.error_on_violation
    cr = ScopePolicy.child_recursion_default()
    assert cr.can_read_outside and not cr.can_write_outside


def test_scope_violation_message() -> None:
    e = ScopeViolation("write", "n1", "r1")
    assert "n1" in str(e) and e.operation == "write" and e.scope_root_id == "r1"


# --------------------------------------------------------------------------- #
# domain weights / scorer
# --------------------------------------------------------------------------- #


def test_score_signals_and_weights() -> None:
    assert set(DEFAULT_DOMAIN_WEIGHTS) == {"knowledge", "experience", "intelligence", "episodic"}
    assert score_signals({"semantic": 1.0}, {"semantic": 1.0}) == 1.0
    assert score_signals({"a": 0.0}, {"a": 1.0}) == 0.0  # all-zero weights
    # partial credit: recency missing penalises
    w = {"semantic": 1.0, "recency": 1.0}
    assert score_signals(w, {"semantic": 1.0}) == pytest.approx(0.5)


def test_domain_item_to_dict() -> None:
    item = DomainItem(node_id=uuid4(), title="t", summary="s", domain="knowledge", score=0.9)
    d = item.to_dict()
    assert d["domain"] == "knowledge" and d["score"] == 0.9 and isinstance(d["node_id"], str)


def test_domain_tree_base_score() -> None:
    class _D(DomainTreeBase):
        RETRIEVAL_WEIGHTS = {"semantic": 1.0}

    assert _D(db=None, company_id=uuid4()).score({"semantic": 0.5}) == 0.5


# --------------------------------------------------------------------------- #
# text utils
# --------------------------------------------------------------------------- #


def test_truncate_for_storage() -> None:
    assert truncate_for_storage(None) == ""
    assert truncate_for_storage("x" * 10, max_chars=4) == "xxxx"
    assert truncate_for_storage({"a": 1})[:1] == "{"


def test_strip_fences_and_json_parsers() -> None:
    assert strip_markdown_fences("```json\n[1]\n```") == "[1]"
    assert parse_json_array('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert parse_json_array("garbage") == []
    assert parse_json_object('prefix {"a": 1} suffix') == {"a": 1}
    assert parse_json_object("nope") is None


# --------------------------------------------------------------------------- #
# providers + reference impls
# --------------------------------------------------------------------------- #


def test_reference_providers_satisfy_protocols() -> None:
    assert isinstance(EchoLLMProvider(), LLMProvider)
    assert isinstance(HashEmbeddingProvider(), EmbeddingProvider)
    assert isinstance(NullUsageReporter(), UsageReporter)
    assert isinstance(InMemoryRunRegistry(), RunRegistry)


def test_embedding_result_dimension() -> None:
    assert EmbeddingResult(vectors=[[1.0, 2.0, 3.0]]).dimension == 3
    assert EmbeddingResult(vectors=[]).dimension == 0


def test_llm_result_fields() -> None:
    r = LLMResult(text="hi", model="m", input_tokens=1, output_tokens=2, cost_usd=0.5)
    assert r.text == "hi" and r.cost_usd == 0.5


@pytest.mark.asyncio
async def test_echo_and_hash_providers() -> None:
    llm = await EchoLLMProvider().complete(system="s", user="hello")
    assert "hello" in llm.text
    emb = await HashEmbeddingProvider(dim=8).embed(["a", "b"])
    assert emb.dimension == 8 and len(emb.vectors) == 2
    again = await HashEmbeddingProvider(dim=8).embed(["a", "b"])
    assert emb.vectors == again.vectors  # deterministic


@pytest.mark.asyncio
async def test_run_registry() -> None:
    reg = InMemoryRunRegistry()
    reg.add(cortex_memory.RunRef(run_id="r1", company_id="c1"))
    assert (await reg.get_run("r1")).company_id == "c1"
    assert await reg.get_run("missing") is None


# --------------------------------------------------------------------------- #
# embedding helpers (with a reference provider + a fake node)
# --------------------------------------------------------------------------- #


class _FakeNode:
    def __init__(self, summary="", title="", content=""):
        self.summary = summary
        self.title = title
        self.content = content
        self.embedding = None
        self.embedding_model = None


@pytest.mark.asyncio
async def test_embed_helpers() -> None:
    provider = HashEmbeddingProvider(dim=8)
    assert await embed_query(None, "x") is None
    assert await embed_query(provider, "") is None
    q = await embed_query(provider, "hello")
    assert q is not None and len(q) == 8

    vecs, model = await embed_texts(provider, ["a", "b"])
    assert len(vecs) == 2 and model == "hash-embed"
    assert (await embed_texts(None, ["a"]))[0] == [None]

    node = _FakeNode(summary="a summary")
    assert await embed_node(provider, node) is True
    assert node.embedding is not None and node.embedding_model == "hash-embed"
    assert await embed_node(None, node) is False
    assert await embed_node(provider, _FakeNode()) is False  # no text


# --------------------------------------------------------------------------- #
# models metadata (no DB) — opaque-FK invariant
# --------------------------------------------------------------------------- #


def test_models_metadata_and_opaque_fks() -> None:
    from cortex_memory.db import Base
    from cortex_memory.models import CortexNode, CortexTree

    assert {"cortex_trees", "cortex_nodes", "cortex_edges"} <= set(Base.metadata.tables)
    for col in ("company_id", "entity_id", "user_id", "run_id"):
        assert not CortexTree.__table__.c[col].foreign_keys
    assert CortexNode.__table__.c["tree_id"].foreign_keys  # internal FK kept
