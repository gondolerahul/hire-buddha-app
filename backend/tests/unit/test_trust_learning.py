"""Provenance trust-score learning — Phase 12 `07` §3.

Hermetic: the DB session is a tiny fake so the posterior math + upsert logic are
exercised without Postgres. Locks in: source-key canonicalisation, the static
prior fallback, convergence toward the observed success rate, and that a fresh
source starts at its prior.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.ai.memory.trust_learning import TrustLearner, prior_for, source_key


def test_source_key_canonicalises() -> None:
    assert source_key("tool", tool_id="web_search") == "tool:web_search"
    assert source_key("external_link", url="https://example.com/a/b") == "external_link:example.com"
    assert source_key("USER_UPLOAD") == "user_upload"


def test_prior_for_uses_cortex_defaults() -> None:
    assert prior_for("user_upload") == 1.0
    assert prior_for("external_link") == 0.4
    assert prior_for("nonsense") == 0.5


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDB:
    """Single-key in-memory stand-in for an AsyncSession."""

    def __init__(self):
        self.rows = {}
        self.commits = 0

    async def execute(self, stmt):  # noqa: ANN001
        # The learner only ever filters by (company_id, source_key); return the
        # most recently added row (tests use one key at a time).
        row = next(iter(self.rows.values()), None)
        return _Result(row)

    def add(self, row):  # noqa: ANN001
        self.rows[row.source_key] = row

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_fresh_source_returns_prior() -> None:
    learner = TrustLearner(_FakeDB())
    t = await learner.effective_trust(uuid4(), "external_link", url="https://x.com")
    assert t == 0.4


@pytest.mark.asyncio
async def test_positive_outcomes_raise_trust_above_prior() -> None:
    db = _FakeDB()
    learner = TrustLearner(db)
    cid = uuid4()
    last = 0.4
    for _ in range(20):
        last = await learner.record_outcome(cid, "external_link", positive=True,
                                            url="https://good.com")
    assert last > 0.4  # learned upward from the 0.4 prior
    assert db.commits == 20


@pytest.mark.asyncio
async def test_negative_outcomes_lower_trust_below_prior() -> None:
    db = _FakeDB()
    learner = TrustLearner(db)
    cid = uuid4()
    last = 0.7
    for _ in range(30):
        last = await learner.record_outcome(cid, "tool", positive=False,
                                            tool_id="flaky_tool")
    assert last < 0.7  # tool prior is 0.7; failures drag it down


@pytest.mark.asyncio
async def test_converges_toward_success_rate() -> None:
    db = _FakeDB()
    learner = TrustLearner(db)
    cid = uuid4()
    # ~50% success over many observations should pull a 0.4 prior up toward 0.5.
    for i in range(200):
        await learner.record_outcome(cid, "external_link", positive=(i % 2 == 0),
                                     url="https://h.com")
    final = await learner.effective_trust(cid, "external_link", url="https://h.com")
    assert 0.45 < final < 0.55
