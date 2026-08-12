"""Phase 11 Track 6 — Reflector scope escalation + persist behaviour."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.ai.core.agent_state import AgentState, Observation, Verdicts
from src.ai.core.budget import Budget
from src.ai.core.reflector import Reflector
from src.ai.core.agent_state import (
    AlignmentVerdict,
    PostCriticVerdict,
    PreCriticVerdict,
    SupervisorVerdict,
)
from src.ai.planning.failure_tags import FailureTag
from src.ai.schemas.enums import EntityType


def _state(*, iteration: int = 1) -> AgentState:
    return AgentState(
        run_id=uuid4(),
        entity_id=uuid4(),
        company_id=uuid4(),
        entity_type=EntityType.SKILL,
        iteration=iteration,
        budget=Budget.from_governance(max_cost_usd=1.0, timeout_ms=60_000),
    )


def _verdicts(*, post_tags=None, suggestion="", align_drift=0.0, aligned=True) -> Verdicts:
    post = PostCriticVerdict(
        kind="REVISE" if post_tags else "PASS",
        tags=list(post_tags or []),
        suggestion=suggestion,
    )
    align = AlignmentVerdict(aligned=aligned, drift=align_drift)
    return Verdicts(pre=PreCriticVerdict(kind="PASS"), post=post, align=align,
                    supervise=SupervisorVerdict())


# ---------------------------------------------------------------------------
# Scope escalation logic — pure (no DB)
# ---------------------------------------------------------------------------


def test_run_scope_when_success_and_no_proposed_change() -> None:
    r = Reflector()
    state = _state()
    obs = Observation(iteration=1, outcome="success", novelty_score=0.5,
                      goal_delta_estimate=0.1, summary="ok")
    reflection = r.produce(state, obs, _verdicts())
    assert reflection.scope == "run"
    assert reflection.proposed_change == ""


def test_entity_scope_when_failure_carries_suggestion() -> None:
    r = Reflector()
    state = _state()
    obs = Observation(iteration=1, outcome="fail", novelty_score=0.3,
                      goal_delta_estimate=-0.1, summary="upstream API 500")
    verdicts = _verdicts(post_tags=[FailureTag.WRONG_FORMAT],
                         suggestion="wrap output in JSON")
    reflection = r.produce(state, obs, verdicts)
    assert reflection.scope == "entity"
    assert "JSON" in reflection.proposed_change


def test_alignment_drift_correction_promotes_to_entity() -> None:
    r = Reflector()
    state = _state()
    obs = Observation(iteration=1, outcome="partial", novelty_score=0.5,
                      goal_delta_estimate=0.0, summary="some text")
    verdicts = _verdicts(post_tags=[], aligned=False, align_drift=0.4)
    verdicts.align.correction_hint = "narrow scope to original topic"
    reflection = r.produce(state, obs, verdicts)
    assert reflection.scope == "entity"
    assert "narrow scope" in reflection.proposed_change


# ---------------------------------------------------------------------------
# persist() — degrades cleanly without a DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_no_db_is_safe_noop() -> None:
    r = Reflector(db=None)
    state = _state()
    obs = Observation(iteration=1, outcome="fail", novelty_score=0.3,
                      goal_delta_estimate=-0.1, summary="x")
    reflection = r.produce(state, obs,
                           _verdicts(post_tags=[FailureTag.WRONG_FORMAT],
                                     suggestion="use JSON"))
    # No raise even though scope is "entity".
    await r.persist(reflection, state)


@pytest.mark.asyncio
async def test_persist_run_scope_does_nothing_even_with_db() -> None:
    db = AsyncMock()
    r = Reflector(db=db)
    state = _state()
    obs = Observation(iteration=1, outcome="success", novelty_score=0.5,
                      goal_delta_estimate=0.1, summary="ok")
    reflection = r.produce(state, obs, _verdicts())
    await r.persist(reflection, state)
    db.execute.assert_not_called()
    db.add.assert_not_called()
