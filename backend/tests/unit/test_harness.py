"""Phase 11 — Self-tests for the regression harness.

If these break, every parity / regression test that depends on the
harness is suspect. The harness primitives are pure-Python and have no
DB / Redis / LLM dependencies, so they MUST stay green offline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.harness import (
    EMBEDDING_DIM,
    MockLLMResponse,
    MockLLMRouter,
    ParityTolerance,
    RunResult,
    StepSummary,
    compare_run_results,
    cosine_similarity,
    deterministic_cosine_similarity,
    deterministic_embedding,
    fixture_path,
    list_entity_fixtures,
    load_entity_fixture,
    load_meta_input,
)


# ---------------------------------------------------------------------------
# RunResult round-trip
# ---------------------------------------------------------------------------


def _make_run_result(**overrides) -> RunResult:
    base = dict(
        run_id="r1",
        entity_id="e1",
        status="COMPLETED",
        total_cost_usd=0.10,
        total_tokens=1234,
        execution_time_ms=4500,
        iterations=2,
        step_count=2,
        error_message=None,
        output_text="A short factual summary citing NIST.",
        plan_step_types=["TOOL_CALL", "ACTION"],
        steps=[
            StepSummary(step_id="s1", name="web_search", type="TOOL_CALL",
                        status="success", cost_usd=0.04, latency_ms=2000,
                        tool_id="web_search", output_len=400),
            StepSummary(step_id="s2", name="summarise", type="ACTION",
                        status="success", cost_usd=0.06, latency_ms=2500,
                        output_len=180),
        ],
    )
    base.update(overrides)
    return RunResult(**base)


def test_run_result_roundtrip(tmp_path: Path) -> None:
    r = _make_run_result()
    p = tmp_path / "r.json"
    r.save(p)
    r2 = RunResult.load(p)
    assert r2 == r


def test_run_result_from_dict_with_missing_optionals() -> None:
    payload = {
        "run_id": "x",
        "entity_id": "y",
        "status": "FAILED",
        "total_cost_usd": 0.0,
        "total_tokens": 0,
        "execution_time_ms": 0,
        "iterations": 0,
        "step_count": 0,
    }
    r = RunResult.from_dict(payload)
    assert r.steps == []
    assert r.output_text == ""
    assert r.plan_step_types == []
    assert r.meta == {}


# ---------------------------------------------------------------------------
# Tolerance comparison
# ---------------------------------------------------------------------------


def test_compare_identical_returns_no_violations() -> None:
    r1 = _make_run_result()
    r2 = _make_run_result()
    assert compare_run_results(r1, r2, ParityTolerance()) == []


def test_compare_status_mismatch_fails() -> None:
    r1 = _make_run_result(status="COMPLETED")
    r2 = _make_run_result(status="FAILED")
    vio = compare_run_results(r1, r2, ParityTolerance())
    assert any(v.metric == "status" for v in vio)


def test_compare_cost_within_tolerance_passes() -> None:
    r1 = _make_run_result(total_cost_usd=0.10)
    r2 = _make_run_result(total_cost_usd=0.103)  # +3%
    vio = compare_run_results(r1, r2, ParityTolerance(cost_pct=0.05))
    assert not any(v.metric == "cost_usd" for v in vio)


def test_compare_cost_outside_tolerance_fails() -> None:
    r1 = _make_run_result(total_cost_usd=0.10)
    r2 = _make_run_result(total_cost_usd=0.20)  # +100%
    vio = compare_run_results(r1, r2, ParityTolerance(cost_pct=0.05))
    assert any(v.metric == "cost_usd" for v in vio)


def test_compare_step_count_drift_fails() -> None:
    r1 = _make_run_result(step_count=2)
    r2 = _make_run_result(step_count=8)
    vio = compare_run_results(r1, r2, ParityTolerance(step_count_delta=2))
    assert any(v.metric == "step_count" for v in vio)


def test_compare_with_similarity_fn() -> None:
    r1 = _make_run_result(output_text="lattice cryptography NIST FIPS-203")
    r2 = _make_run_result(output_text="completely unrelated text about pancakes")
    vio = compare_run_results(
        r1, r2,
        ParityTolerance(output_similarity_min=0.85),
        similarity_fn=deterministic_cosine_similarity,
    )
    assert any(v.metric == "output_similarity" for v in vio)


def test_parity_tolerance_for_track_lookup() -> None:
    assert ParityTolerance.for_track(2).cost_pct == 0.05
    assert ParityTolerance.for_track(3).cost_pct == 0.15
    assert ParityTolerance.for_track(7).cost_pct == 0.10
    assert ParityTolerance.for_track(99).cost_pct == 0.05  # default


# ---------------------------------------------------------------------------
# Deterministic embeddings
# ---------------------------------------------------------------------------


def test_embedding_dim_is_fixed() -> None:
    assert len(deterministic_embedding("hello world")) == EMBEDDING_DIM


def test_embedding_is_deterministic() -> None:
    a = deterministic_embedding("the quick brown fox")
    b = deterministic_embedding("the quick brown fox")
    assert a == b


def test_cosine_identical_is_one() -> None:
    text = "lattice based post-quantum cryptography"
    assert deterministic_cosine_similarity(text, text) == pytest.approx(1.0)


def test_cosine_disjoint_is_low() -> None:
    s = deterministic_cosine_similarity(
        "lattice cryptography kyber",
        "pancake recipe blueberry maple",
    )
    assert s < 0.3


def test_cosine_overlapping_is_positive() -> None:
    s = deterministic_cosine_similarity(
        "lattice cryptography kyber nist",
        "nist standardised kyber for post-quantum kem",
    )
    assert s > 0.2


def test_cosine_zero_vector_returns_zero() -> None:
    # Empty text → zero vector.
    assert cosine_similarity([0.0] * EMBEDDING_DIM, [0.0] * EMBEDDING_DIM) == 0.0


# ---------------------------------------------------------------------------
# Fixture loaders
# ---------------------------------------------------------------------------


def test_entity_fixtures_are_listed() -> None:
    names = list_entity_fixtures()
    for required in ("simple_skill", "research_agent", "research_process"):
        assert required in names


def test_load_entity_fixture_validates_against_schema() -> None:
    """Every entity fixture MUST validate as a HierarchicalEntityCreate."""
    for name in ("simple_skill", "research_agent", "research_process"):
        entity = load_entity_fixture(name)
        assert entity.name.startswith("test_")
        assert entity.type.value in {"SKILL", "AGENT", "PROCESS"}


def test_load_meta_inputs() -> None:
    for name in ("simple_skill", "research_agent", "hostile"):
        payload = load_meta_input(name)
        assert "user_request" in payload
        assert "expected_kind" in payload


def test_canonical_cortex_tree_fixture_present() -> None:
    p = fixture_path("cortex", "canonical_tree.json")
    assert p.exists()
    data = json.loads(p.read_text())
    assert "knowledge_nodes" in data
    assert "intelligence_rules" in data


# ---------------------------------------------------------------------------
# MockLLMRouter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_llm_returns_fixture_on_match() -> None:
    router = MockLLMRouter()
    router.record("PLANNING", "plan something",
                  MockLLMResponse(output='[{"step_id":"s1"}]', cost_usd=0.01))
    resp = await router.call_llm(task_type="PLANNING", user_prompt="plan something")
    assert resp.output == '[{"step_id":"s1"}]'
    assert resp.cost_usd == 0.01


@pytest.mark.asyncio
async def test_mock_llm_stub_fallback_on_miss() -> None:
    router = MockLLMRouter()
    resp = await router.call_llm(task_type="PLANNING", user_prompt="anything")
    # PLANNING stub returns parseable JSON.
    assert "step_id" in resp.output
    assert resp.metadata.get("stub") is True


@pytest.mark.asyncio
async def test_mock_llm_strict_mode_raises_on_miss() -> None:
    router = MockLLMRouter(strict=True)
    with pytest.raises(LookupError):
        await router.call_llm(task_type="PLANNING", user_prompt="anything")


@pytest.mark.asyncio
async def test_mock_llm_logs_calls() -> None:
    router = MockLLMRouter()
    await router.call_llm(task_type="REVIEW", user_prompt="check this")
    assert len(router.calls) == 1
    assert router.calls[0]["task_type"] == "REVIEW"


def test_mock_llm_roundtrip(tmp_path: Path) -> None:
    router = MockLLMRouter()
    router.record("X", "p", MockLLMResponse(output="r", cost_usd=0.5))
    path = tmp_path / "f.json"
    router.save(path)
    router2 = MockLLMRouter.from_file(path)
    assert len(router2.fixtures) == 1
    [resp] = router2.fixtures.values()
    assert resp.output == "r"
    assert resp.cost_usd == 0.5
