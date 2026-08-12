"""Phase 11 Track 4 — PlanStyleBandit tests (in-memory persistence)."""
from __future__ import annotations

import random
from collections import Counter

import pytest

from src.ai.planning.plan_style_bandit import (
    ArmState,
    BanditTable,
    PlanStyleBandit,
    PlanStyleArm,
)


# ---------------------------------------------------------------------------
# Score ordering
# ---------------------------------------------------------------------------


def test_score_higher_winrate_wins() -> None:
    low = ArmState(pulls=10, successes=2, avg_cost_usd=0.05)
    hi = ArmState(pulls=10, successes=8, avg_cost_usd=0.05)
    assert PlanStyleBandit.score(hi) > PlanStyleBandit.score(low)


def test_score_lower_cost_wins_at_equal_winrate() -> None:
    cheap = ArmState(pulls=10, successes=5, avg_cost_usd=0.01)
    pricey = ArmState(pulls=10, successes=5, avg_cost_usd=0.20)
    assert PlanStyleBandit.score(cheap) > PlanStyleBandit.score(pricey)


def test_score_laplace_smoothing_for_fresh_arm() -> None:
    fresh = ArmState()
    # Smoothing keeps the score positive even with no pulls.
    assert PlanStyleBandit.score(fresh) > 0


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_candidate_returns_immediately() -> None:
    b = PlanStyleBandit()
    arm, exploring = await b.select_arm(
        entity_id="e", task_class="t",
        candidates=["DAG_PARALLEL"],
    )
    assert arm == "DAG_PARALLEL"
    assert exploring is False


@pytest.mark.asyncio
async def test_exploitation_picks_higher_score(monkeypatch) -> None:
    rng = random.Random(0)
    b = PlanStyleBandit(rng=rng, epsilon=0.0)
    await b.update_arm(
        entity_id="e", task_class="t", arm="A", success=True, cost_usd=0.02,
    )
    for _ in range(5):
        await b.update_arm(
            entity_id="e", task_class="t", arm="A", success=True, cost_usd=0.02,
        )
    await b.update_arm(
        entity_id="e", task_class="t", arm="B", success=False, cost_usd=0.10,
    )
    arm, exploring = await b.select_arm(
        entity_id="e", task_class="t", candidates=["A", "B"],
    )
    assert arm == "A"
    assert exploring is False


@pytest.mark.asyncio
async def test_exploration_rate_within_tolerance() -> None:
    rng = random.Random(42)
    b = PlanStyleBandit(rng=rng, epsilon=0.10)
    # Make A the obviously-best arm so non-exploration always picks A.
    for _ in range(5):
        await b.update_arm(
            entity_id="e", task_class="t", arm="A",
            success=True, cost_usd=0.02,
        )
    await b.update_arm(
        entity_id="e", task_class="t", arm="B",
        success=False, cost_usd=0.20,
    )
    picks = Counter()
    explores = 0
    for _ in range(1000):
        arm, ex = await b.select_arm(
            entity_id="e", task_class="t", candidates=["A", "B"],
        )
        picks[arm] += 1
        if ex:
            explores += 1
    # ε=0.10 → expect ~100 explorations, allow ±3σ ≈ ±28.
    assert 70 <= explores <= 140


# ---------------------------------------------------------------------------
# update_arm — EMA over avg_cost_usd
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_first_pull_sets_cost_directly() -> None:
    b = PlanStyleBandit()
    st = await b.update_arm(
        entity_id="e", task_class="t", arm="A",
        success=True, cost_usd=0.07,
    )
    assert st.pulls == 1
    assert st.successes == 1
    assert st.avg_cost_usd == pytest.approx(0.07)


@pytest.mark.asyncio
async def test_update_ema_blends_new_cost() -> None:
    b = PlanStyleBandit(ema_alpha=0.2)
    await b.update_arm(
        entity_id="e", task_class="t", arm="A",
        success=True, cost_usd=0.10,
    )
    st = await b.update_arm(
        entity_id="e", task_class="t", arm="A",
        success=False, cost_usd=0.20,
    )
    # 0.8 * 0.10 + 0.2 * 0.20 = 0.12
    assert st.pulls == 2
    assert st.successes == 1
    assert st.avg_cost_usd == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# Table serialisation
# ---------------------------------------------------------------------------


def test_bandit_table_roundtrip() -> None:
    tbl = BanditTable()
    tbl.get_or_seed("A").pulls = 3
    tbl.get_or_seed("A").successes = 2
    tbl.get_or_seed("A").avg_cost_usd = 0.04
    blob = tbl.to_json()
    back = BanditTable.from_json(blob)
    assert "A" in back.arms
    assert back.arms["A"].pulls == 3
    assert back.arms["A"].successes == 2
    assert back.arms["A"].avg_cost_usd == pytest.approx(0.04)


def test_bandit_table_handles_garbage_json() -> None:
    assert BanditTable.from_json(None).arms == {}
    assert BanditTable.from_json("not json").arms == {}
    assert BanditTable.from_json("[]").arms == {}


def test_plan_style_arm_values_stable() -> None:
    # If these change, downstream telemetry queries must change too.
    assert PlanStyleArm.DAG_PARALLEL.value == "DAG_PARALLEL"
    assert PlanStyleArm.RECURSIVE.value == "RECURSIVE"
