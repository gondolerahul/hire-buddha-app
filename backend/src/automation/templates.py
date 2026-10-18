"""Trigger input templates (tech spec §7.8): an event turned into a run's input.

A trigger's ``input_template`` is JSON whose text values may hold Jinja
expressions over the event:

    {"input": "Reply politely to: {{ event.data.text }}",
     "lead": "{{ event.data.author.name | default('a visitor') }}"}

Rendering is sandboxed (``ImmutableSandboxedEnvironment``) and the template
sees plain JSON copies only — the event and the trigger's own fields — never
a Python object, so there is no attribute to reach through. A missing value
renders as empty text. Templates and their output are size-limited.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from jinja2 import ChainableUndefined, TemplateError as JinjaTemplateError
from jinja2.sandbox import ImmutableSandboxedEnvironment

MAX_TEMPLATE_CHARS = 20_000
MAX_OUTPUT_CHARS = 100_000


class TemplateError(ValueError):
    """A template that does not parse, or failed to render; the message says where."""


_environment = ImmutableSandboxedEnvironment(
    undefined=ChainableUndefined,  # {{ event.data.missing.deeper }} renders as ""
    autoescape=False,
    keep_trailing_newline=True,
)


def _json_copy(value: Any) -> Any:
    """Only JSON reaches a template: no Python object, no method, no attribute."""
    return json.loads(json.dumps(value, default=str))


def _strings(node: Any, where: str = "input"):
    if isinstance(node, str):
        yield where, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{where}[{index}]")


_MARKERS = ("{{", "{%", "{#")
_ENDRAW = re.compile(r"\{%-?\s*endraw\s*-?%\}")


def literal(value: Any) -> Any:
    """A template that renders to ``value`` exactly.

    Text someone else wrote — an agent's input for the run it schedules — is
    data, not a template: braces in it stay braces.
    """
    if isinstance(value, str):
        if not any(marker in value for marker in _MARKERS):
            return value
        out, start = [], 0
        for match in _ENDRAW.finditer(value):
            out.append("{% raw %}" + value[start:match.start()] + "{% endraw %}")
            out.append("{{ '" + match.group(0) + "' }}")
            start = match.end()
        out.append("{% raw %}" + value[start:] + "{% endraw %}")
        return "".join(out)
    if isinstance(value, list):
        return [literal(v) for v in value]
    if isinstance(value, dict):
        return {k: literal(v) for k, v in value.items()}
    return value


def validate(template: Any) -> Any:
    """The template itself if every text in it parses, else :class:`TemplateError`."""
    size = len(json.dumps(template, default=str))
    if size > MAX_TEMPLATE_CHARS:
        raise TemplateError(f"template is {size} characters; the limit is {MAX_TEMPLATE_CHARS}")
    for where, text in _strings(template):
        try:
            _environment.parse(text)
        except JinjaTemplateError as error:
            raise TemplateError(f"{where}: {error}") from None
    return template


def render(template: Any, event: Dict[str, Any], trigger: Optional[Dict[str, Any]] = None) -> Any:
    """The template with every text rendered against ``event`` (and ``trigger``)."""
    context = {"event": _json_copy(event), "trigger": _json_copy(trigger or {})}
    produced = [0]

    def walk(node: Any, where: str) -> Any:
        if isinstance(node, str):
            if "{" not in node:
                return node
            try:
                text = _environment.from_string(node).render(context)
            except JinjaTemplateError as error:
                raise TemplateError(f"{where}: {error}") from None
            except Exception as error:  # the sandbox refused something, or a filter failed
                raise TemplateError(f"{where}: {type(error).__name__}: {error}") from None
            produced[0] += len(text)
            if produced[0] > MAX_OUTPUT_CHARS:
                raise TemplateError(f"rendered input exceeds {MAX_OUTPUT_CHARS} characters")
            return text
        if isinstance(node, dict):
            return {key: walk(value, f"{where}.{key}") for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value, f"{where}[{index}]") for index, value in enumerate(node)]
        return node

    return walk(_json_copy(template), "input")
