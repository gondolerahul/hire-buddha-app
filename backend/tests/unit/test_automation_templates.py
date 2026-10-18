"""Phase 14 WS3 (tech spec §7.8): a trigger's input template, rendered safely.

The template sees plain JSON copies of the event and the trigger only;
the sandbox refuses reaching into Python; missing values render empty.
"""
import pytest

from src.automation.templates import MAX_TEMPLATE_CHARS, TemplateError, render, validate

EVENT = {"type": "social.comment.created", "data": {"text": "Do you ship to Pune?", "author": {"name": "Priya"}}}


def test_the_functional_spec_example():
    template = {"input": "Reply politely to: {{event.data.text}}"}
    assert render(validate(template), EVENT) == {"input": "Reply politely to: Do you ship to Pune?"}


def test_nested_values_lists_and_defaults():
    template = {"input": "Lead {{ event.data.author.name }}",
                "context": ["{{ event.type }}", 7, True],
                "who": "{{ event.data.author.email | default('unknown') }}",
                "trigger": "{{ trigger.name }}"}
    out = render(template, EVENT, {"name": "Reply to Instagram comments"})
    assert out == {"input": "Lead Priya", "context": ["social.comment.created", 7, True],
                   "who": "unknown", "trigger": "Reply to Instagram comments"}


def test_a_missing_value_renders_empty():
    assert render({"input": "[{{ event.data.order.id }}]"}, EVENT) == {"input": "[]"}


@pytest.mark.parametrize("attack", [
    "{{ event.__class__.__mro__ }}",
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    "{{ cycler.__init__.__globals__.os }}",
    "{{ lipsum.__globals__['os'].popen('id').read() }}",
    "{% for x in range(10**9) %}{% endfor %}",
])
def test_the_sandbox_refuses_python(attack):
    try:
        out = render({"input": attack}, EVENT)
    except TemplateError:
        return
    # Rendering without an error must not have reached anything.
    assert "subprocess" not in out["input"] and "uid=" not in out["input"] and "<class" not in out["input"]


def test_bad_syntax_is_refused_when_the_trigger_is_saved():
    with pytest.raises(TemplateError, match=r"input\.input"):
        validate({"input": "{{ event.data.text "})


def test_size_limits():
    with pytest.raises(TemplateError, match="limit"):
        validate({"input": "x" * (MAX_TEMPLATE_CHARS + 1)})
    with pytest.raises(TemplateError, match="exceeds"):
        render({"input": "{{ 'x' * 200000 }}"}, EVENT)


def test_python_objects_in_the_event_become_text():
    from datetime import datetime

    out = render({"input": "{{ event.data.at }}"}, {"data": {"at": datetime(2026, 10, 18, 9, 0)}})
    assert out == {"input": "2026-10-18 09:00:00"}


def test_text_someone_else_wrote_stays_literal():
    from src.automation.templates import literal, render, validate

    written = {"input": "Ask about {{ the visit }} and {% if x %}", "note": "a {% endraw %} b {#c#}",
               "plain": "no braces", "list": ["{{ event.data.secret }}"], "n": 3}
    template = literal(written)
    validate(template)
    assert render(template, {"data": {"secret": "leaked"}}) == written
