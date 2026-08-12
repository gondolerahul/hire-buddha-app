"""
tests.harness — Shared regression / parity primitives.

Public surface:

* ``RunResult`` / ``ParityTolerance`` / ``compare_run_results`` —
  unit of comparison between a baseline (legacy) and candidate (new)
  execution run.
* ``MockLLMRouter`` / ``MockLLMResponse`` — hermetic LLM fixture replay.
* ``deterministic_embedding`` / ``cosine_similarity`` /
  ``deterministic_cosine_similarity`` — offline output-similarity
  scoring.
* ``load_entity_fixture`` / ``load_meta_input`` / ``fixture_path`` —
  filesystem loaders for fixtures under ``backend/tests/fixtures/``.
"""
from tests.harness.embeddings import (
    EMBEDDING_DIM,
    cosine_similarity,
    deterministic_cosine_similarity,
    deterministic_embedding,
)
from tests.harness.fixtures import (
    FIXTURES_ROOT,
    fixture_path,
    list_entity_fixtures,
    list_regression_cases,
    load_entity_fixture,
    load_entity_fixture_raw,
    load_meta_input,
)
from tests.harness.mock_llm import (
    MockLLMResponse,
    MockLLMRouter,
)
from tests.harness.run_result import (
    ParityTolerance,
    ParityViolation,
    RunResult,
    StepSummary,
    compare_run_results,
)

__all__ = [
    "RunResult",
    "StepSummary",
    "ParityTolerance",
    "ParityViolation",
    "compare_run_results",
    "MockLLMRouter",
    "MockLLMResponse",
    "deterministic_embedding",
    "deterministic_cosine_similarity",
    "cosine_similarity",
    "EMBEDDING_DIM",
    "fixture_path",
    "load_entity_fixture",
    "load_entity_fixture_raw",
    "load_meta_input",
    "list_entity_fixtures",
    "list_regression_cases",
    "FIXTURES_ROOT",
]
