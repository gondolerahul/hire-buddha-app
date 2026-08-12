"""Phase 11 Track 5 — Promoter 6-gate tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.ai.meta.board.architect import ArchitectDraft
from src.ai.meta.board.promoter import Promoter, PromotionDecision


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeCritic:
    verdict: str = "PASS"
    concerns: list[dict] = field(default_factory=list)


@dataclass
class FakeCheck:
    name: str
    reason: str = ""


@dataclass
class FakeValidator:
    passed: bool = True
    failed: list[FakeCheck] = field(default_factory=list)


@dataclass
class FakeSuite:
    passed: bool = True
    budget_exhausted: bool = False


@dataclass
class FakeCurator:
    decision: str = "CREATE"


def _draft(**overrides) -> ArchitectDraft:
    payload = {
        "name": "X", "type": "SKILL", "goal": "g",
        "governance": {"max_cost_usd": 1.0, "timeout_ms": 60000},
    }
    payload.update(overrides)
    return ArchitectDraft(payload=payload)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_gates_pass_promotes() -> None:
    called = []

    async def flip(d):
        called.append(d)
        return "new-entity-id"

    p = Promoter(flip_callback=flip)
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(),
        curator_decision=FakeCurator(),
    )
    assert decision.outcome == "PROMOTED"
    assert decision.entity_id == "new-entity-id"
    assert called


# ---------------------------------------------------------------------------
# Individual gate failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critic_block_rejects() -> None:
    p = Promoter()
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(verdict="BLOCK"),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(),
        curator_decision=FakeCurator(),
    )
    assert decision.outcome == "REJECT"
    assert "G1_critic_clean" in decision.failed_gates


@pytest.mark.asyncio
async def test_validator_failures_block_promotion() -> None:
    p = Promoter()
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(
            passed=False,
            failed=[FakeCheck("json_shape_ok", "missing name")],
        ),
        suite_result=FakeSuite(),
        curator_decision=FakeCurator(),
    )
    assert decision.outcome == "REJECT"
    assert "G2_validator_clean" in decision.failed_gates


@pytest.mark.asyncio
async def test_test_suite_failure_rejects() -> None:
    p = Promoter()
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(passed=False),
        curator_decision=FakeCurator(),
    )
    assert "G3_test_suite_pass" in decision.failed_gates


@pytest.mark.asyncio
async def test_budget_exhausted_rejects() -> None:
    p = Promoter()
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(passed=True, budget_exhausted=True),
        curator_decision=FakeCurator(),
    )
    assert "G4_test_budget_ok" in decision.failed_gates


@pytest.mark.asyncio
async def test_missing_curator_decision_rejects() -> None:
    p = Promoter()
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(),
        curator_decision=FakeCurator(decision=""),
    )
    assert "G5_curator_recorded" in decision.failed_gates


@pytest.mark.asyncio
async def test_missing_cost_cap_rejects() -> None:
    p = Promoter()
    decision = await p.promote(
        draft=_draft(governance={}),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(),
        curator_decision=FakeCurator(),
    )
    assert "G6_runtime_cost_cap_set" in decision.failed_gates


# ---------------------------------------------------------------------------
# HITL gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hitl_path_returns_pending() -> None:
    called = []

    async def flip(d):
        called.append(d)
        return "should-not-be-called"

    p = Promoter(hitl_required=True, flip_callback=flip)
    decision = await p.promote(
        draft=_draft(),
        critic_report=FakeCritic(),
        validator_report=FakeValidator(),
        suite_result=FakeSuite(),
        curator_decision=FakeCurator(),
    )
    assert decision.outcome == "PENDING_HITL"
    assert not called
