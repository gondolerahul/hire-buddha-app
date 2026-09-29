"""A HITL checkpoint must wait for a decision, and fail closed (GH-22, GH-01).

The wait used ``self.redis.client.pubsub()``. On the worker's
``redis.asyncio.Redis`` ``client`` is a method, so every checkpoint raised,
the error was swallowed, and the step went ahead unapproved. The wait now
subscribes with ``self.redis.pubsub()`` and also re-reads the approval row, so
a Redis failure slows it down but never skips it.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.sql.dml import Update

from src.ai.governance.governance_service import GovernanceService
from src.ai.schemas import PlanStep


class _RowDB:
    """Stands in for the worker session: holds one approval row's status."""

    def __init__(self, statuses=("PENDING",), timeout_rowcount=1):
        self.added = []
        self.updates = []
        self._statuses = list(statuses)  # successive reads; the last one repeats
        self._timeout_rowcount = timeout_rowcount

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = obj.id or uuid.uuid4()

    async def execute(self, stmt):
        if isinstance(stmt, Update):
            self.updates.append(stmt.compile().params)
            return SimpleNamespace(rowcount=self._timeout_rowcount)
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return SimpleNamespace(scalar_one_or_none=lambda: status)


class _DeadRedis:
    """Redis is down: every call fails."""

    def pubsub(self):
        raise ConnectionError("redis unreachable")

    async def publish(self, *_):
        raise ConnectionError("redis unreachable")


def _step():
    return PlanStep(step_id="s1", name="Send email", type="ACTION",
                    target={"prompt_template": "Send it"})


def _checkpoint(timeout_ms=5000, auto=False):
    return {"trigger_type": "BEFORE_STEP", "step_ref": "Send email",
            "timeout_ms": timeout_ms, "auto_approve_on_timeout": auto}


async def _evaluate(db, redis, checkpoint):
    svc = GovernanceService(db, redis)
    run = SimpleNamespace(id=uuid.uuid4(), total_cost_usd=0)
    entity = SimpleNamespace(name="e", display_name="E", governance={})
    await svc.evaluate_hitl(run, entity, _step(), {"input": "x"}, "BEFORE",
                            governance_dict={"hitl_checkpoints": [checkpoint]})


async def _real_redis():
    import redis.asyncio as redis_lib
    from src.common.config import settings
    client = redis_lib.from_url(settings.REDIS_URL)  # exactly what arq_jobs builds
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis is not reachable")
    return client


async def _decide_over_pubsub(redis, db, status: str):
    for _ in range(100):  # wait for the checkpoint to create its row
        if db.added and db.added[0].id:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)  # let it subscribe
    await redis.publish(f"hitl:{db.added[0].id}", json.dumps({"status": status}))


@pytest.mark.asyncio
async def test_rejection_over_real_pubsub_blocks_the_step():
    redis = await _real_redis()
    db = _RowDB()  # the row stays PENDING: only pub/sub can deliver the decision
    try:
        with pytest.raises(Exception, match="Execution blocked by human reviewer"):
            await asyncio.gather(_evaluate(db, redis, _checkpoint()),
                                 _decide_over_pubsub(redis, db, "REJECTED"))
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_approval_over_real_pubsub_lets_the_step_run():
    redis = await _real_redis()
    db = _RowDB()
    try:
        loop = asyncio.get_running_loop()
        started = loop.time()
        finished = []
        evaluation = asyncio.ensure_future(_evaluate(db, redis, _checkpoint()))
        evaluation.add_done_callback(lambda _: finished.append(loop.time()))
        await _decide_over_pubsub(redis, db, "APPROVED")
        decided = loop.time()
        await evaluation
        assert finished[0] >= decided - 0.05  # it waited for the decision...
        assert finished[0] - started < 4      # ...and woke on the message, not a row poll
        assert db.updates == []  # nothing marked TIMEOUT
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_redis_down_still_waits_for_the_row():
    # A PENDING read, then the reviewer's REJECTED lands on the row.
    db = _RowDB(statuses=("PENDING", "REJECTED"))
    with pytest.raises(Exception, match="Execution blocked by human reviewer"):
        await _evaluate(db, _DeadRedis(), _checkpoint(timeout_ms=15000))


@pytest.mark.asyncio
async def test_redis_down_approval_on_the_row_proceeds():
    db = _RowDB(statuses=("PENDING", "APPROVED"))
    await _evaluate(db, _DeadRedis(), _checkpoint(timeout_ms=15000))


@pytest.mark.asyncio
async def test_timeout_without_auto_approve_fails_and_records_timeout():
    db = _RowDB()
    with pytest.raises(Exception, match="timed out"):
        await _evaluate(db, _DeadRedis(), _checkpoint(timeout_ms=200))
    assert [u["status"] for u in db.updates] == ["TIMEOUT"]


@pytest.mark.asyncio
async def test_timeout_with_auto_approve_proceeds():
    db = _RowDB()
    await _evaluate(db, _DeadRedis(), _checkpoint(timeout_ms=200, auto=True))
    assert [u["status"] for u in db.updates] == ["APPROVED"]


@pytest.mark.asyncio
async def test_a_decision_at_the_deadline_wins_over_timeout():
    # The conditional TIMEOUT update finds the row no longer PENDING.
    db = _RowDB(statuses=("PENDING", "APPROVED"), timeout_rowcount=0)
    await _evaluate(db, _DeadRedis(), _checkpoint(timeout_ms=200))
