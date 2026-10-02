"""The run's final output is checked against the output schema; loop_control
is retired (P8.2 — EP-05).

``io_contract.output_schema`` was a sentence in the prompt and nothing checked
the result; ``planning.loop_control`` was authored and read by nothing. Now
the final output must be a JSON object with the schema's required keys and
types, or the post verdict becomes REVISE / WRONG_FORMAT and the retry rewrites
the step's prompt with what is wrong.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.ai.core.agent_loop import AgentLoop
from src.ai.core.agent_state import PostCriticVerdict, PreCriticVerdict
from src.ai.core.executors.base import EXECUTOR_REGISTRY, ActionResult, register_executor
from src.ai.core.feature_flags import FeatureFlags
from src.ai.planning.critic_pipeline import NoOpCriticPipeline
from src.ai.planning.step_health_record import StepHealthRecord

from tests.unit.test_agent_loop_robustness import _FakeDB, _FakeRun, _no_credit_gate  # noqa: F401

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "pages": {"type": "integer"}},
          "required": ["title"]}


class _Writes:
    name = "SingleStep"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.fragments: list = []

    async def execute(self, move, state, db):  # noqa: ARG002
        self.fragments.append(move.plan_fragment)
        return ActionResult(success=True, output=self.outputs.pop(0), cost_usd=Decimal("0"),
                            completed_step_ids=[s["step_id"] for s in move.plan_fragment or []])


class _Passes(NoOpCriticPipeline):
    """A critic that passes everything and keeps a health record."""

    def __init__(self):
        self.record = None

    async def pre_action(self, move, state):
        self.record = StepHealthRecord(step_id=move.plan_fragment[0]["step_id"], iteration=state.iteration + 1)
        return PreCriticVerdict(kind="PASS")

    async def post_action(self, state, observation):  # noqa: ARG002
        self.record.post_critic_verdict = "PASS"
        return PostCriticVerdict(kind="PASS")

    def override_post(self, verdict):
        self.record.post_critic_verdict = verdict.kind
        self.record.post_critic_tags = list(verdict.tags)
        self.record.post_critic_suggestion = verdict.suggestion

    async def finalize_iteration(self, state):
        state.health_records.append(self.record)
        return self.record


@pytest.mark.asyncio
async def test_a_final_output_that_misses_the_schema_is_sent_back(monkeypatch):
    import src.ai.core.agent_loop as al

    async def _no_wait(_s):
        return None

    monkeypatch.setattr(al.asyncio, "sleep", _no_wait)
    writer = _Writes(["Here is your report: Tides", '```json\n{"title": "Tides", "pages": 3}\n```'])
    original = EXECUTOR_REGISTRY.get("SingleStep")
    register_executor(writer)
    try:
        run = _FakeRun()
        run.entity.io_contract = {"output_schema": SCHEMA}
        run.entity.planning = {"static_plan": {"enabled": True, "steps": [
            {"step_id": "s1", "name": "Write", "type": "ACTION"}]}, "dynamic_planning": {"enabled": False}}
        loop = AgentLoop(db=_FakeDB(run), redis=None, critic_pipeline=_Passes(), max_iterations=6,
                         feature_flags=FeatureFlags(db=None))
        await loop.run(run.id)
    finally:
        if original is not None:
            register_executor(original)

    first, retry = writer.fragments
    hint = retry[0]["directive"]["prompt_hint"]
    assert "JSON object" in hint and "'title'" in hint and "not a JSON object" in hint
    assert "directive" not in first[0]


def test_output_problems():
    from src.ai.governance.output_contract import output_problems
    entity = SimpleNamespace(io_contract={"output_schema": SCHEMA})
    assert output_problems(entity, '{"title": "x"}') == []
    assert output_problems(entity, 'Sure! {"title": "x", "pages": 2} Hope this helps.') == []
    assert output_problems(entity, '{"pages": "two"}') == ["'title' is missing", "'pages' must be integer"]
    assert output_problems(entity, "no json") == ["the output is not a JSON object"]
    # The builder's default schema has no properties: nothing to check.
    assert output_problems(SimpleNamespace(io_contract={"output_schema": {"type": "object", "properties": {}}}),
                           "plain prose") == []


def test_loop_control_is_retired_but_still_saves():
    from src.ai.schemas.entity import HierarchicalEntityCreateRequest
    from src.ai.schemas.planning import Planning
    from src.ai.schemas.strict_keys import unknown_keys
    assert "loop_control" not in Planning.model_fields
    payload = {"name": "x", "type": "AGENT", "planning": {"loop_control": {"max_iterations": 3}}}
    assert unknown_keys(HierarchicalEntityCreateRequest, payload) == []
