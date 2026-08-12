"""Phase 11 Track 5 — BoardCritic revise loop tests (stubbed spec_critic)."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.ai.meta.board.architect import Architect, ArchitectDraft
from src.ai.meta.board.critic import BoardCritic


@pytest.mark.asyncio
async def test_pass_on_first_round_returns_draft(monkeypatch) -> None:
    payloads = iter(['{"verdict": "PASS", "concerns": []}'])

    async def fake_run(self, input_data: str, context: Any = None) -> str:
        return next(payloads)

    with patch(
        "src.ai.tools.meta.spec_critic.MetaSpecCriticTool.run_with_context",
        fake_run,
    ):
        critic = BoardCritic(company_id=uuid4())
        draft = ArchitectDraft(payload={"name": "x", "type": "SKILL"})
        _, report = await critic.review_with_revision(draft, Architect())
    assert report.verdict == "PASS"
    assert report.rounds == 0
    assert report.passed


@pytest.mark.asyncio
async def test_revise_then_pass(monkeypatch) -> None:
    payloads = iter([
        json.dumps({
            "verdict": "REVISE",
            "concerns": [{"severity": "low", "category": "prompt",
                          "issue": "short prompt", "fix_suggestion": "expand"}],
        }),
        json.dumps({"verdict": "PASS", "concerns": []}),
    ])

    async def fake_run(self, input_data: str, context: Any = None) -> str:
        return next(payloads)

    with patch(
        "src.ai.tools.meta.spec_critic.MetaSpecCriticTool.run_with_context",
        fake_run,
    ):
        critic = BoardCritic(company_id=uuid4())
        draft, report = await critic.review_with_revision(
            ArchitectDraft(payload={"name": "x"}),
            Architect(),
        )
    assert report.verdict == "PASS"
    assert report.rounds == 1
    revs = draft.payload["metadata_extensions"]["architect_revisions"]
    assert revs and revs[0]["issue"] == "short prompt"


@pytest.mark.asyncio
async def test_max_revise_rounds_block(monkeypatch) -> None:
    # Always returns REVISE → after MAX rounds, BoardCritic forces BLOCK.
    async def fake_run(self, input_data: str, context: Any = None) -> str:
        return json.dumps({
            "verdict": "REVISE",
            "concerns": [{"severity": "med", "category": "prompt",
                          "issue": "still bad", "fix_suggestion": ""}],
        })
    with patch(
        "src.ai.tools.meta.spec_critic.MetaSpecCriticTool.run_with_context",
        fake_run,
    ):
        critic = BoardCritic(company_id=uuid4(), max_rounds=1)
        _, report = await critic.review_with_revision(
            ArchitectDraft(payload={"name": "x"}),
            Architect(),
        )
    assert report.verdict == "BLOCK"
    assert "max revise rounds" in report.blocked_reason


@pytest.mark.asyncio
async def test_block_short_circuits_revise(monkeypatch) -> None:
    async def fake_run(self, input_data: str, context: Any = None) -> str:
        return json.dumps({
            "verdict": "BLOCK",
            "concerns": [{"severity": "critical", "category": "policy",
                          "issue": "uses banned tool",
                          "fix_suggestion": "remove",
                          "blocks_promotion": True}],
        })
    with patch(
        "src.ai.tools.meta.spec_critic.MetaSpecCriticTool.run_with_context",
        fake_run,
    ):
        critic = BoardCritic(company_id=uuid4())
        _, report = await critic.review_with_revision(
            ArchitectDraft(payload={"name": "x"}),
            Architect(),
        )
    assert report.verdict == "BLOCK"
    assert report.has_blocking_concern
