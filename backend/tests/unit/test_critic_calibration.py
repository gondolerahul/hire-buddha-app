"""Phase 11 Track 3 — CriticCalibrator persistence regression tests.

Guards the ``_persist_intel_rule`` path that writes calibration metrics
back as Intelligence rules. Historically the calibrator constructed
``IntelligenceTreeService(self.db)`` without the required positional
``company_id``; the resulting ``TypeError`` was swallowed by the
surrounding ``except Exception`` so calibration rules silently never
persisted. These tests pin the contract: the service is built with the
calibrator's ``company_id`` and the write actually fires.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import src.ai.memory.intelligence_tree_service as its_module
from src.ai.planning.critic_calibration import CalibrationResult, CriticCalibrator


class _RecordingService:
    """Stand-in for IntelligenceTreeService with the real ctor signature.

    Mirrors ``IntelligenceTreeService.__init__(self, db, company_id)`` so
    that constructing it without ``company_id`` raises ``TypeError`` — the
    exact failure mode this regression test exists to catch.
    """

    calls: list[dict] = []

    def __init__(self, db, company_id):
        self.db = db
        self.company_id = company_id

    async def upsert_calibration_rule(self, *, entity_id, task_class, payload):
        _RecordingService.calls.append(
            {
                "company_id": self.company_id,
                "entity_id": entity_id,
                "task_class": task_class,
                "payload": payload,
            }
        )


def _patch_service(monkeypatch):
    _RecordingService.calls = []
    monkeypatch.setattr(
        its_module, "IntelligenceTreeService", _RecordingService
    )


def test_persist_intel_rule_uses_company_id(monkeypatch):
    """The persist path must construct the service with the company_id
    and call through to the write method (regression: TypeError that was
    silently swallowed, so nothing ever persisted)."""
    _patch_service(monkeypatch)

    company_id = uuid4()
    entity_id = uuid4()
    calibrator = CriticCalibrator(db=object(), company_id=company_id)
    res = CalibrationResult(
        entity_id=entity_id,
        task_class="entity_type:skill",
        samples=42,
        false_pass_rate=0.1,
        false_fail_rate=0.2,
    )

    asyncio.run(calibrator._persist_intel_rule(res))

    assert len(_RecordingService.calls) == 1, (
        "calibration rule was never persisted — the persist path failed "
        "silently (the original TypeError-swallowing bug)"
    )
    call = _RecordingService.calls[0]
    assert call["company_id"] == company_id
    assert call["entity_id"] == entity_id
    assert call["task_class"] == "entity_type:skill"
    assert call["payload"]["type"] == "critic_calibration"
    assert call["payload"]["samples"] == 42


def test_persist_intel_rule_swallows_write_errors(monkeypatch):
    """A failure inside the write must not propagate (best-effort job)."""

    class _BoomService:
        def __init__(self, db, company_id):
            pass

        async def upsert_calibration_rule(self, **_kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(its_module, "IntelligenceTreeService", _BoomService)

    calibrator = CriticCalibrator(db=object(), company_id=uuid4())
    res = CalibrationResult(entity_id=uuid4(), task_class="x", samples=30)

    # Must not raise.
    asyncio.run(calibrator._persist_intel_rule(res))
