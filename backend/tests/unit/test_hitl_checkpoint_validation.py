"""A HITL checkpoint that could never fire is refused, or asks (GH-09, GH-10).

A checkpoint that did not parse was skipped with a bare ``continue``, and a
``CUSTOM`` expression outside a two-variable, two-operator evaluator was false
forever — the builder's own example, ``cost > 0.50 or step_count > 5``, among
them. A typo removed a safety gate without a word. Now the grammar is written
down (``schemas/hitl_expression.py``), the entity API refuses a checkpoint
that could never fire (422, naming it), and one stored before that asks a
person at run time, with a trace event.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.ai.core.events import capture_test_events
from src.ai.core.exceptions import HITLPending
from src.ai.governance.governance_service import GovernanceService
from src.ai.schemas import PlanStep
from src.ai.schemas.entity import HierarchicalEntityCreateRequest, HierarchicalEntityUpdateRequest
from src.ai.schemas.governance import checkpoint_problem
from src.ai.schemas.hitl_expression import ExpressionError, evaluate, parse


# ── the grammar ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("expression, step_count, cost, keys, expected", [
    ("cost > 0.50 or step_count > 5", 2, 0.6, (), True),     # the builder's example
    ("cost > 0.50 or step_count > 5", 6, 0.1, (), True),
    ("cost > 0.50 or step_count > 5", 2, 0.1, (), False),
    ("step_count >= 2 and cost < 1", 2, 0.5, (), True),
    ("step_count >= 2 and cost < 1", 2, 1.0, (), False),
    ("cost <= 0.25", 0, 0.25, (), True),
    ("step_count == 3", 3, 0, (), True),
    ("has_key('lead')", 0, 0, ("lead",), True),
    ('has_key("lead") and cost > 1 or step_count > 9', 0, 0, ("lead",), False),
])
def test_the_grammar(expression, step_count, cost, keys, expected):
    assert evaluate(expression, step_count=step_count, cost=cost, keys=keys) is expected


@pytest.mark.parametrize("expression", [
    "", "current_cost > 1", "cost > ", "cost >> 1", "cost > 1 and", "cost > 1 && step_count > 2",
    "has_key(lead)", "tool == 'web_search'", "cost > -1", "cost", "(cost > 1)",
])
def test_anything_else_is_refused(expression):
    with pytest.raises(ExpressionError):
        parse(expression)


# ── what a checkpoint needs ─────────────────────────────────────────────────


@pytest.mark.parametrize("raw, fragment", [
    ({"trigger_type": "NOPE"}, "trigger_type"),
    ({"trigger_type": "BEFORE_STEP"}, "needs step_ref"),
    ({"trigger_type": "AFTER_STEP", "step_ref": " "}, "needs step_ref"),
    ({"trigger_type": "TOOL_CALL"}, "needs tool_ref"),
    ({"trigger_type": "COST_THRESHOLD", "threshold": 0}, "threshold above 0"),
    ({"trigger_type": "CUSTOM", "expression": "current_cost > 1"}, "unknown name 'current_cost'"),
    ({"trigger_type": "BEFORE_STEP", "step_ref": "Send", "timeout_ms": 0}, "timeout_ms"),
    ("not a checkpoint", "checkpoint"),
])
def test_a_checkpoint_that_could_never_fire_says_why(raw, fragment):
    assert fragment in (checkpoint_problem(raw) or "")


@pytest.mark.parametrize("raw", [
    {"trigger_type": "BEFORE_STEP", "step_ref": "Send"},
    {"trigger_type": "TOOL_CALL", "tool_ref": "email_send"},
    {"trigger_type": "COST_THRESHOLD", "threshold": 0.5},
    {"trigger_type": "CUSTOM", "expression": "cost > 0.50 or step_count > 5"},
])
def test_a_working_checkpoint_has_no_problem(raw):
    assert checkpoint_problem(raw) is None


# ── the entity API refuses it (422) ─────────────────────────────────────────


def _payload(*checkpoints, steps=("Send",), dynamic=False):
    return {
        "name": "mailer", "type": "SKILL",
        "planning": {"static_plan": {"enabled": True, "steps": [
            {"step_id": f"s{i}", "name": n, "type": "ACTION"} for i, n in enumerate(steps, start=1)]},
            "dynamic_planning": {"enabled": dynamic}},
        "governance": {"hitl_checkpoints": list(checkpoints)},
    }


def test_saving_a_bad_checkpoint_names_it():
    with pytest.raises(ValidationError) as refused:
        HierarchicalEntityCreateRequest.model_validate(_payload(
            {"trigger_type": "BEFORE_STEP", "step_ref": "Send"},
            {"trigger_type": "CUSTOM", "expression": "cost > 0.5 && step_count > 2"},
        ))
    assert "checkpoint 2 (CUSTOM)" in str(refused.value)
    assert "checkpoint 1" not in str(refused.value)


def test_a_step_reference_must_be_a_step_of_the_static_plan():
    with pytest.raises(ValidationError, match="'Sned' is not a step of the plan"):
        HierarchicalEntityCreateRequest.model_validate(_payload({"trigger_type": "BEFORE_STEP", "step_ref": "Sned"}))
    # By id is fine; and a dynamic plan names its steps at run time.
    HierarchicalEntityCreateRequest.model_validate(_payload({"trigger_type": "BEFORE_STEP", "step_ref": "s1"}))
    HierarchicalEntityCreateRequest.model_validate(
        _payload({"trigger_type": "BEFORE_STEP", "step_ref": "Draft"}, dynamic=True))


def test_an_update_is_checked_too():
    with pytest.raises(ValidationError, match="needs tool_ref"):
        HierarchicalEntityUpdateRequest.model_validate({"governance": {"hitl_checkpoints": [
            {"trigger_type": "TOOL_CALL"}]}})


# ── at run time: one stored before asks, with an event ──────────────────────


class _NoApprovals:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = obj.id or uuid.uuid4()

    async def execute(self, stmt):
        return SimpleNamespace(first=lambda: None)


class _Redis:
    async def publish(self, *_):
        pass


async def _evaluate(checkpoint, phase="BEFORE", spent=0.0, monkeypatch=None):
    db = _NoApprovals()
    svc = GovernanceService(db, _Redis())
    if monkeypatch is not None:
        async def _spend(self, run):  # noqa: ARG001
            return spent
        monkeypatch.setattr(GovernanceService, "_run_spend", _spend)
    run = SimpleNamespace(id=uuid.uuid4(), total_cost_usd=0)
    step = PlanStep(step_id="s1", name="Send email", type="ACTION", target={"prompt_template": "x"})
    entity = SimpleNamespace(name="e", display_name="E", governance={})
    await svc.evaluate_hitl(run, entity, step, {"input": "x", "s0": "done"}, phase,
                            governance_dict={"hitl_checkpoints": [checkpoint]})
    return db


@pytest.mark.asyncio
async def test_a_stored_checkpoint_that_cannot_be_evaluated_asks_a_person():
    with capture_test_events() as events, pytest.raises(HITLPending) as parked:
        await _evaluate({"trigger_type": "CUSTOM", "expression": "current_cost > 1", "timeout_ms": 60000})
    assert parked.value.trigger == "UNUSABLE CHECKPOINT 1 before Send email"
    assert parked.value.timeout_ms == 60000
    [unusable] = [e for e in events if e.name == "agent.hitl.checkpoint_unusable"]
    assert unusable.payload["checkpoint"] == 1 and "current_cost" in unusable.payload["problem"]


@pytest.mark.asyncio
async def test_it_asks_once_per_step_not_after_it_too():
    db = await _evaluate({"trigger_type": "NOPE"}, phase="AFTER")
    assert db.added == []


@pytest.mark.asyncio
async def test_the_builders_example_now_fires(monkeypatch):
    with pytest.raises(HITLPending) as parked:
        await _evaluate({"trigger_type": "CUSTOM", "expression": "cost > 0.50 or step_count > 5"},
                        spent=0.6, monkeypatch=monkeypatch)
    assert parked.value.trigger == "CUSTOM: cost > 0.50 or step_count > 5"
    db = await _evaluate({"trigger_type": "CUSTOM", "expression": "cost > 0.50 or step_count > 5"},
                         spent=0.1, monkeypatch=monkeypatch)
    assert db.added == []
