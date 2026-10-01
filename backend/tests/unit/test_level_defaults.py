"""Whatever varies with the kind of entity is derived from its level (R1).

The manifest the Meta-Agent reads, the meta-cognition defaults, the credit floor
to start a run, and the meta-layer validators each listed four types; LOOP and
GRAPH were unknown to all of them.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.ai.meta.platform_schema_compiler import PlatformSchemaCompiler
from src.ai.schemas.enums import EntityType

SIX = [t.value for t in EntityType]


def test_the_manifest_lists_the_six_levels_and_what_each_may_compose() -> None:
    types = PlatformSchemaCompiler()._compile_entity_types()
    assert [t["type"] for t in types] == SIX
    assert [t["level"] for t in types] == [1, 2, 3, 4, 5, 6]
    by_type = {t["type"]: t for t in types}
    assert by_type["ACTION"]["may_compose"] == ["ACTION"]
    assert by_type["AGENT"]["may_compose"] == ["ACTION", "SKILL", "AGENT"]
    assert by_type["GRAPH"]["may_compose"] == SIX


@pytest.mark.asyncio
async def test_the_manifest_summary_teaches_the_composition_rule() -> None:
    compiler = PlatformSchemaCompiler()
    compiler._cached_schema = {
        "entity_types": compiler._compile_entity_types(),
        "composition_rules": compiler._compile_composition_rules(),
    }
    summary = await compiler.compile_summary()
    assert "**LOOP** (level 5)" in summary and "**GRAPH** (level 6)" in summary
    assert "at its parent's level or below" in summary


@pytest.mark.parametrize("level, floor", [
    ("ACTION", "0.01"), ("SKILL", "0.02"), ("AGENT", "0.05"),
    ("PROCESS", "0.50"), ("LOOP", "1.00"), ("GRAPH", "2.00"),
])
def test_each_level_has_a_credit_floor(level, floor) -> None:
    from src.billing.credit_service import minimum_threshold

    assert minimum_threshold(level) == Decimal(floor)


@pytest.mark.asyncio
@pytest.mark.parametrize("level", SIX)
async def test_the_board_validator_accepts_every_level(level) -> None:
    from src.ai.meta.board.validator import ValidatorRole

    report = await ValidatorRole().check({"name": "x", "type": level})
    assert next(c for c in report.checks if c.name == "entity_type_valid").passed


def test_registry_search_offers_every_level() -> None:
    from src.ai.tools.meta.registry_search import MetaRegistrySearchTool

    schema = MetaRegistrySearchTool().get_function_schema()
    assert schema["parameters"]["properties"]["preferred_type"]["enum"] == SIX


def test_a_wide_spec_is_high_stakes_at_any_level() -> None:
    from src.ai.meta.spec_tiebreak import is_high_stakes

    for level in ("AGENT", "LOOP", "GRAPH"):
        assert is_high_stakes({"type": level, "children": list(range(6))}, governance_ceiling_usd=10.0)
    assert not is_high_stakes({"type": "LOOP", "children": [1, 2]}, governance_ceiling_usd=10.0)
