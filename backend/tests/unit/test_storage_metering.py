"""Hosting and database storage SKUs (Phase 15 T7-3, tech design §9).

What a business keeps is sampled once a day and billed as that day's share of
a month: GB × 1/days-in-month of ``*-gb-month``; each verified custom domain is
1/days-in-month of ``custom-domain-month``. A build's seconds are
``app-build-second`` usage (replacing ``APP_BUILD_COST_PER_SECOND``).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.apps import metering
from src.billing.categories import Category, category_for
from src.billing.units import Dimension


def test_a_day_is_its_months_share():
    assert metering._month_share(datetime(2026, 2, 10)) == Decimal(1) / 28
    assert metering._month_share(datetime(2026, 10, 24)) == Decimal(1) / 31


def test_every_new_sku_has_its_dimension():
    assert metering.SKU_DIMENSIONS[metering.SKU_BUILD] == Dimension.SECOND
    for sku in (metering.SKU_APP_STORAGE, metering.SKU_DB_STORAGE, metering.SKU_BACKUP):
        assert metering.SKU_DIMENSIONS[sku] == Dimension.GB_MONTH
    assert metering.SKU_DIMENSIONS[metering.SKU_DOMAIN] == Dimension.MONTH


def test_database_storage_and_backups_are_shown_under_database():
    for sku in ("tenant-db-storage-gb-month", "tenant-backup-gb-month", "tenant-db-pool-share"):
        assert category_for("hosting", sku=sku) == Category.DATABASE
    for sku in ("app-storage-gb-month", "app-build-second", "custom-domain-month"):
        assert category_for("hosting", sku=sku) == Category.HOSTING


@pytest.mark.asyncio
async def test_a_build_is_billed_by_the_second(monkeypatch):
    billed = []

    async def _bill(company_id, sku, quantity, metadata):
        billed.append((sku, quantity, metadata["build_id"]))
        return SimpleNamespace(calculated_cost=Decimal("0.0123"))

    monkeypatch.setattr(metering, "_bill", _bill)
    build = SimpleNamespace(id=uuid.uuid4(), app_id=uuid.uuid4(), duration_seconds=123, commit_sha="abc")
    cost = await metering.bill_build(uuid.uuid4(), build, "crm")
    assert billed == [("app-build-second", Decimal(123), str(build.id))]
    assert cost == Decimal("0.0123")


@pytest.mark.asyncio
async def test_a_build_that_cannot_be_billed_still_finishes(monkeypatch):
    async def _fail(*_a, **_k):
        raise RuntimeError("usage service down")

    monkeypatch.setattr(metering, "_bill", _fail)
    build = SimpleNamespace(id=uuid.uuid4(), app_id=uuid.uuid4(), duration_seconds=5, commit_sha="abc")
    assert await metering.bill_build(uuid.uuid4(), build, "crm") == Decimal(0)


@pytest.mark.asyncio
async def test_the_daily_sample_bills_each_store_once(monkeypatch):
    company = uuid.uuid4()
    billed = []

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *_a, **_k):
            _Session.calls += 1
            # first: the SKU ids; second: verified domains per company
            return _Result([(s, uuid.uuid4()) for s in (metering.SKU_APP_STORAGE, metering.SKU_DB_STORAGE,
                                                        metering.SKU_BACKUP, metering.SKU_DOMAIN)]
                           if _Session.calls == 1 else [(company, 2)])

    async def _ready():
        return [company]

    async def _find(_cid):
        return SimpleNamespace(key="acme")

    async def _sampled(*_a):
        return False

    async def _stored(prefix):
        return 2 * 1024 ** 3 if prefix.endswith("/apps/") else 1024 ** 3

    async def _db_bytes(_cid):
        return 3 * 1024 ** 3

    async def _bill(cid, sku, quantity, metadata):
        billed.append((sku, quantity))
        return SimpleNamespace()

    monkeypatch.setattr("src.common.tenancy.session.control_session", lambda: _Session())
    monkeypatch.setattr("src.common.tenancy.directory.directory.ready_company_ids", _ready)
    monkeypatch.setattr("src.common.tenancy.directory.directory.find", _find)
    monkeypatch.setattr(metering, "_sampled", _sampled)
    monkeypatch.setattr(metering, "_stored_bytes", _stored)
    monkeypatch.setattr(metering, "_database_bytes", _db_bytes)
    monkeypatch.setattr(metering, "_bill", _bill)
    out = await metering.meter_storage(datetime(2026, 10, 23))
    share = Decimal(1) / 31
    assert dict(billed) == {metering.SKU_APP_STORAGE: 2 * share, metering.SKU_DB_STORAGE: 3 * share,
                            metering.SKU_BACKUP: share, metering.SKU_DOMAIN: 2 * share}
    assert out == {"billed": 4, "skipped": 0, "errors": 0}
