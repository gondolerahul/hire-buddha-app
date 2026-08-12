# backend/tests/regression/

Nightly regression suite. Cases live as YAML under `cases/`; each case
declares what to run, what to expect, and how to grade. See
`case_schema.py::RegressionCase` for the full schema.

## Adding a case

1. Pick an entity fixture from `tests/fixtures/entities/` (or add one).
2. Drop a YAML at `cases/<your_case_id>.yaml`. Minimum fields:

   ```yaml
   case_id: my_case
   entity_fixture: research_agent
   input: {topic: "..."}
   expected_status: COMPLETED
   expected_must_mention: ["..."]
   ```

3. Run `pytest backend/tests/unit/test_regression_suite.py` to confirm
   the loader accepts it.
4. CI nightly will pick it up automatically.

## The judge

`judge.py::DeterministicJudge` is the default — pure substring +
length checks, no LLM call. Set `acceptance.judge_rubric` and switch
to `LLMJudge` (`from src.ai.llm.router import LLMRouter`) for cases
where structured grading is too brittle.

## Running locally

```bash
# Quick check: just the loader / judge tests (no kernel needed).
pytest tests/unit/test_regression_suite.py

# Full nightly (Track 2+ — needs DB, Redis, possibly LLM credits).
pytest -m regression tests/regression/
```

## When this becomes live

The actual `tests/regression/test_regression_cases.py` (the
parametrised pytest entry point) lands in Track 2 alongside the
real run-creation wiring. Until then the seed cases serve as
golden snapshot inputs.
