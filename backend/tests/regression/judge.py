"""
tests/regression/judge.py — LLM-judge for ambiguous regression cases.

Two implementations:

  * ``DeterministicJudge`` — pure-Python, no network. Scores based on
    ``must_mention`` / ``must_not_mention`` substring presence. Used in
    CI by default so nightly tests don't burn LLM credits.

  * ``LLMJudge`` — calls a real LLM (via the kernel's LLMRouter) and
    parses a structured verdict. Used when a tenant pays for accurate
    grading or when must-mention assertions are too brittle.

The judge interface is identical so swapping is a configuration knob.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from tests.regression.case_schema import RegressionCase

logger = logging.getLogger(__name__)


@dataclass
class JudgeVerdict:
    passed: bool
    score: float            # 0..1; meaning varies by judge
    reasons: list[str]
    grader: str             # "deterministic" | "llm-<model>" | ...

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        head = f"[judge:{self.grader} {verdict}] score={self.score:.2f}"
        if self.reasons:
            body = "\n".join(f"  - {r}" for r in self.reasons)
            return f"{head}\n{body}"
        return head


class Judge(Protocol):
    def grade(
        self,
        case: RegressionCase,
        output_text: str,
        *,
        meta: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict: ...


# ---------------------------------------------------------------------------
# Deterministic substring judge
# ---------------------------------------------------------------------------


class DeterministicJudge:
    """Substring presence + cost-band judge.

    Scoring (per case):
      * Each ``must_mention`` token present: +1/N points.
      * Each ``must_not_mention`` token absent: +1/M points.
      * If both lists empty, score defaults to 1.0 (case is data-only).

    The verdict ``passed = score >= case.acceptance.llm_judge_threshold``.
    """

    name = "deterministic"

    def grade(
        self,
        case: RegressionCase,
        output_text: str,
        *,
        meta: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict:
        reasons: list[str] = []
        lowered = output_text.lower()

        must = [m.lower() for m in case.expected_must_mention]
        must_not = [m.lower() for m in case.expected_must_not_mention]

        # ``must_mention`` points
        if must:
            hits = sum(1 for m in must if m in lowered)
            mention_score = hits / len(must)
            for m in must:
                if m not in lowered:
                    reasons.append(f"missing required mention: {m!r}")
        else:
            mention_score = 1.0

        # ``must_not_mention`` points
        if must_not:
            misses = sum(1 for m in must_not if m not in lowered)
            avoid_score = misses / len(must_not)
            for m in must_not:
                if m in lowered:
                    reasons.append(f"contains forbidden mention: {m!r}")
        else:
            avoid_score = 1.0

        # Geometric mean keeps either zero from dominating.
        score = (mention_score * avoid_score) ** 0.5

        # Length constraints
        acceptance = case.acceptance
        if acceptance.output_min_chars and len(output_text) < acceptance.output_min_chars:
            reasons.append(
                f"output {len(output_text)} chars < min "
                f"{acceptance.output_min_chars}"
            )
            score = min(score, 0.0)
        if acceptance.output_max_chars and len(output_text) > acceptance.output_max_chars:
            reasons.append(
                f"output {len(output_text)} chars > max "
                f"{acceptance.output_max_chars}"
            )
            score = min(score, 0.5)

        passed = score >= case.acceptance.llm_judge_threshold
        return JudgeVerdict(passed=passed, score=score, reasons=reasons,
                            grader=self.name)


# ---------------------------------------------------------------------------
# LLM-backed judge (lazy import — only constructed when explicitly chosen)
# ---------------------------------------------------------------------------


JUDGE_SYSTEM_PROMPT = """You are an impartial grader for AI-agent output.

You receive: (1) the case rubric, (2) the actual output. You MUST
respond with JSON of the form:

  {"passed": true|false, "score": 0.0-1.0, "reasons": ["..."]}

Do not include any other text. Be specific about WHY a case failed —
reference the rubric criteria, not your general opinion."""


class LLMJudge:
    """LLM-graded judge. The router and model are injected so this module
    has no hard dependency on a particular kernel build."""

    def __init__(self, router: Any, *, model: str = "claude-sonnet-4-5"):
        self.router = router
        self.model = model
        self.name = f"llm-{model}"

    def grade(
        self,
        case: RegressionCase,
        output_text: str,
        *,
        meta: Optional[dict[str, Any]] = None,
    ) -> JudgeVerdict:
        rubric = case.acceptance.judge_rubric or _default_rubric(case)
        user_prompt = (
            f"### Rubric\n{rubric}\n\n"
            f"### Actual output\n{output_text[:8000]}\n"
        )
        try:
            resp = self.router.call_llm_sync(
                task_type="JUDGE",
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model_name=self.model,
            )
            verdict_data = json.loads(resp.output)
        except Exception as exc:
            logger.exception("LLM judge call failed; defaulting to FAIL")
            return JudgeVerdict(
                passed=False, score=0.0,
                reasons=[f"judge invocation failed: {exc}"],
                grader=self.name,
            )

        passed = bool(verdict_data.get("passed", False))
        score = float(verdict_data.get("score", 0.0))
        reasons = list(verdict_data.get("reasons") or [])
        if score < case.acceptance.llm_judge_threshold:
            passed = False
        return JudgeVerdict(passed=passed, score=score, reasons=reasons,
                            grader=self.name)


def _default_rubric(case: RegressionCase) -> str:
    parts = [
        f"Case ID: {case.case_id}",
        f"Expected status: {case.expected_status}",
    ]
    if case.expected_must_mention:
        parts.append("Must mention: " + ", ".join(case.expected_must_mention))
    if case.expected_must_not_mention:
        parts.append(
            "Must NOT mention: " + ", ".join(case.expected_must_not_mention)
        )
    if case.expected_min_cost_usd is not None or case.expected_max_cost_usd is not None:
        parts.append(
            f"Cost band: ${case.expected_min_cost_usd or 0:.2f} – "
            f"${case.expected_max_cost_usd or 0:.2f}"
        )
    return "\n".join(parts)
