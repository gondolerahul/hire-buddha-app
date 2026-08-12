"""Phase 11 Track 6 — assembler v2 default + legacy fallback wiring."""
from __future__ import annotations

import inspect

from src.ai.memory.assembler import assemble_memory


def test_memory_pipeline_default_is_v2() -> None:
    """The hardcoded default in the assembler signature MUST be v2."""
    sig = inspect.signature(assemble_memory)
    default = sig.parameters["memory_pipeline"].default
    assert default == "v2"


def test_assembler_module_exposes_top_level_function() -> None:
    """Other call sites import ``assemble_memory`` directly — keep it."""
    from src.ai.memory import assembler
    assert callable(assembler.assemble_memory)


def test_legacy_reader_is_importable_from_canonical_path() -> None:
    """The legacy reader is now a sibling under memory/."""
    from src.ai.memory.legacy_episodic_reader import LegacyEpisodicReader
    assert callable(LegacyEpisodicReader.read)
