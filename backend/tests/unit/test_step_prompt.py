"""EP-25 — the run's request reaches every step; loop state does not.

A THOUGHT/ACTION step's prompt was its rendered ``prompt_template`` plus the
previous steps' outputs, and ``input`` is internal, so a template that did not
reference ``{{input}}`` (a description copied into the template is common) left
the model without the task. ``__agent_state__`` was not internal and was shown
to the model as a previous step's output.
"""
from __future__ import annotations

from src.ai.schemas import PlanStep, StepType
from src.ai.step_executor import compose_step_prompt

QUESTION = "What changed in India's EV subsidy policy in 2025?"


def _step(template: str | None) -> PlanStep:
    target = {"prompt_template": template} if template is not None else None
    return PlanStep(step_id="s1", name="gather", type=StepType.THOUGHT,
                    description="Gather sources on the topic.", target=target)


def _context(**extra) -> dict:
    return {"input": QUESTION,
            "__agent_state__": {"iteration": 3, "budget_pressure": 0.4}, **extra}


def test_a_template_without_input_still_gets_the_task():
    prompt = compose_step_prompt(_step("You are a research gatherer. Collect sources."),
                                 _context(), QUESTION)
    assert "## Task" in prompt and QUESTION in prompt


def test_a_template_with_input_is_not_given_it_twice():
    prompt = compose_step_prompt(_step("Research: {{input}}"), _context(), QUESTION)
    assert prompt.count(QUESTION) == 1
    assert "## Task" not in prompt


def test_the_default_template_renders_the_input():
    prompt = compose_step_prompt(_step(None), _context(), QUESTION)
    assert prompt.count(QUESTION) == 1


def test_loop_state_is_not_shown_as_a_previous_step():
    prompt = compose_step_prompt(_step("Collect sources."), _context(step_0="earlier output"), QUESTION)
    assert "__agent_state__" not in prompt
    assert "budget_pressure" not in prompt
    assert "earlier output" in prompt
