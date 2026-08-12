"""Phase 11 Track 5 — SkillLibrary chain detector (pure-function path)."""
from __future__ import annotations

from src.ai.meta.skill_library import SkillLibrary


def test_repeated_chain_above_threshold_detected() -> None:
    lib = SkillLibrary(db=None, min_repeats=3, min_chain_len=2, max_chain_len=3)
    runs = [
        ["search", "scrape", "summarise"],
        ["search", "scrape", "summarise"],
        ["search", "scrape", "summarise"],
        ["unrelated_tool"],
    ]
    candidates = lib.detect_chains(runs)
    chains = {c.chain for c in candidates}
    assert ("search", "scrape") in chains
    assert ("scrape", "summarise") in chains
    assert ("search", "scrape", "summarise") in chains


def test_below_threshold_no_candidates() -> None:
    lib = SkillLibrary(db=None, min_repeats=5, min_chain_len=2, max_chain_len=4)
    runs = [["a", "b"], ["a", "b"]]
    assert lib.detect_chains(runs) == []


def test_self_loops_excluded() -> None:
    lib = SkillLibrary(db=None, min_repeats=2, min_chain_len=2, max_chain_len=2)
    runs = [
        ["search", "search"],
        ["search", "search"],
        ["search", "search"],
    ]
    # ("search","search") is a degenerate self-loop → not surfaced.
    assert lib.detect_chains(runs) == []


def test_short_sequence_no_chains() -> None:
    lib = SkillLibrary(db=None, min_repeats=2, min_chain_len=3, max_chain_len=5)
    runs = [["a", "b"]]   # too short to window length 3
    assert lib.detect_chains(runs) == []


def test_top_candidate_metadata_carries_frequency() -> None:
    lib = SkillLibrary(db=None, min_repeats=2, min_chain_len=2, max_chain_len=2)
    runs = [["a", "b"], ["a", "b"], ["c", "d"]]
    cands = lib.detect_chains(runs)
    top = cands[0]
    assert top.frequency >= 2
    assert top.chain == ("a", "b")
