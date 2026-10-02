"""The registry keeps its promises (P6.10 — TX-I9, TL-68, TL-67).

``calculator`` advertised ``{"expression": ...}`` and parsed the whole input
string, so every model call failed (TL-68); seeds granted ``scraper``,
``batch_search`` and ``docx_generator``, which nothing registers (TL-67).
Nothing checked either. Now, over every registered tool: its schema is a
well-formed object schema; a typed tool's schema is its ``Params``; every
parameter an unconverted tool advertises is read by its code (the known
drifts are listed, each with the item that removes it, and the list may only
shrink); and every tool a seed or fixture grants is registered.
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

import src.ai.tools  # noqa: F401  (registers every tool)
from src.ai.tools.base import ToolRegistry

BACKEND = pathlib.Path(__file__).resolve().parents[2]
TOOLS = sorted(ToolRegistry._tools.items())

# Advertised parameters the code never reads — each is a defect, with the
# plan item that removes it. The list may only shrink.
KNOWN_DRIFT = {
}


@pytest.mark.parametrize("name,tool", TOOLS, ids=[n for n, _ in TOOLS])
def test_every_schema_is_a_well_formed_object_schema(name, tool):
    schema = tool.get_function_schema()
    assert schema["name"] == name and schema.get("description")
    params = schema["parameters"]
    assert params.get("type") == "object" and isinstance(params.get("properties"), dict)
    assert set(params.get("required", [])) <= set(params["properties"]), "required names an unknown property"
    for prop, spec in params["properties"].items():
        assert "type" in spec or "enum" in spec, f"{prop}: no type (a provider would guess a string)"
        if spec.get("type") == "array":
            assert isinstance(spec.get("items"), dict), f"{prop}: an array without items"


def _reads(cls: type, prop: str) -> bool:
    module = inspect.getsource(inspect.getmodule(cls))
    try:
        module = module.replace(inspect.getsource(cls.get_function_schema), "")
    except (OSError, TypeError):
        pass
    return bool(re.search(r"""['"]%s['"]""" % re.escape(prop), module)
                or re.search(r"\.%s\b" % re.escape(prop), module))


def _untyped_schemas():
    """Every hand-written schema: unconverted tools, and ``social_api``'s
    operations (their schemas are what ``describe`` shows the model)."""
    from src.ai.tools.social.social_api import operations
    for name, tool in TOOLS:
        if tool.Params is None:
            yield name, tool
    for platform, ops in operations().items():
        for verb, op in ops.items():
            yield f"social_api:{platform}.{verb}", op


def test_every_advertised_parameter_is_read():
    drift = set()
    for name, tool in _untyped_schemas():
        for prop in tool.get_function_schema()["parameters"]["properties"]:
            if prop != "input" and not _reads(type(tool), prop):
                drift.add((name, prop))
    assert drift <= set(KNOWN_DRIFT), f"advertised and never read: {sorted(drift - set(KNOWN_DRIFT))}"
    assert set(KNOWN_DRIFT) <= drift, f"fixed or deleted — remove from KNOWN_DRIFT: {sorted(set(KNOWN_DRIFT) - drift)}"


def test_every_tool_a_seed_or_fixture_grants_is_registered():
    pattern = re.compile(r"""["']tool_id["']\s*:\s*["']([A-Za-z0-9_:.-]+)["']""")
    unknown = {}
    for root in ("scripts/seeds", "tests/fixtures", "db-scripts"):
        for path in (BACKEND / root).rglob("*"):
            if path.suffix not in (".py", ".json") or "SeedDocumentFactory/scripts" in path.as_posix():
                continue
            for m in pattern.finditer(path.read_text(encoding="utf-8", errors="ignore")):
                if m.group(1) not in ToolRegistry._tools:
                    unknown.setdefault(m.group(1), []).append(path.relative_to(BACKEND).as_posix())
    assert unknown == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("args,expected", [
    ({"expression": "17*23"}, "391"),          # how a model calls it — failed before (TL-68)
    ("17*23", "391"),                          # a plan step's text
    ({"expression": "2 ** 10 / 4"}, "256"),
])
async def test_the_calculator_reads_its_advertised_expression(args, expected):
    out = await ToolRegistry._tools["calculator"].invoke(args, {})
    assert out.success and out.output == expected


@pytest.mark.asyncio
async def test_the_calculator_fails_cleanly():
    tool = ToolRegistry._tools["calculator"]
    assert (await tool.invoke({"expression": "1/0"}, {})).error == "Division by zero"
    assert (await tool.invoke({"expression": "__import__('os')"}, {})).success is False
