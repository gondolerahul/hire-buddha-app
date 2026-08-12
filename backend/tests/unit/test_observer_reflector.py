"""Phase 11 Track 2 — Observer + Reflector unit tests."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.ai.core.agent_state import AgentState, Verdicts, PostCriticVerdict, AlignmentVerdict
from src.ai.core.budget import Budget
from src.ai.core.executors.base import ActionResult
from src.ai.core.observer import Observer
from src.ai.core.reflector import Reflector
from src.ai.planning.failure_tags import FailureTag
from src.ai.schemas.enums import EntityType


def _state() -> AgentState:
    return AgentState(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=EntityType.SKILL,
        budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
    )


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------


def test_observer_success_outcome() -> None:
    o = Observer().parse(
        ActionResult(success=True, output="all done", cost_usd=Decimal("0.05")),
        _state(),
    )
    assert o.outcome == "success"
    assert o.goal_delta_estimate > 0


def test_observer_fail_when_error_present() -> None:
    o = Observer().parse(
        ActionResult(success=False, error="boom"),
        _state(),
    )
    assert o.outcome == "fail"
    assert o.goal_delta_estimate < 0


def test_observer_partial_when_no_error_but_success_false() -> None:
    o = Observer().parse(
        ActionResult(success=False, error=""),
        _state(),
    )
    assert o.outcome == "partial"


def test_observer_novelty_bumps_on_cortex_writes() -> None:
    from uuid import uuid4 as u
    ar = ActionResult(success=True, cortex_nodes_written=[u()])
    assert Observer().parse(ar, _state()).novelty_score == 1.0


def test_observer_summary_truncates_long_output() -> None:
    long_out = "x" * 1000
    o = Observer().parse(ActionResult(success=True, output=long_out), _state())
    assert len(o.summary) < 250
    assert "[success]" in o.summary


# ---------------------------------------------------------------------------
# Reflector
# ---------------------------------------------------------------------------


def test_reflector_produces_for_success() -> None:
    s = _state()
    obs = Observer().parse(ActionResult(success=True, output="ok"), s)
    r = Reflector().produce(s, obs)
    assert r.what_worked
    assert r.scope == "run"


def test_reflector_includes_post_critic_tags() -> None:
    s = _state()
    obs = Observer().parse(ActionResult(success=False, error="boom"), s)
    verdicts = Verdicts(
        post=PostCriticVerdict(kind="REVISE",
                                tags=[FailureTag.HALLUCINATION, FailureTag.WRONG_FORMAT],
                                suggestion="try different model"),
    )
    r = Reflector().produce(s, obs, verdicts)
    assert "HALLUCINATION" in r.what_didnt
    assert "WRONG_FORMAT" in r.what_didnt
    assert r.proposed_change == "try different model"


def test_reflector_includes_alignment_drift() -> None:
    s = _state()
    obs = Observer().parse(ActionResult(success=False, error="x"), s)
    verdicts = Verdicts(
        align=AlignmentVerdict(aligned=False, drift=0.4, correction_hint="back to goal"),
    )
    r = Reflector().produce(s, obs, verdicts)
    assert "drift" in r.cause_hypothesis
    assert "back to goal" in r.proposed_change
