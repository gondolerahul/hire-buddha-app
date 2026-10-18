"""Phase 14 WS1 1.10: the business's time zone replaces the hard-coded India time.

A company has an IANA time zone (Asia/Kolkata unless changed); the agent's
date tool and the mobile analytics' days use it. The mobile dialer's calling
window stays on India time on purpose (a TRAI rule, not a business setting).
"""
import json
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from src.auth.schemas import CompanyResponse, CompanyUpdate
from src.common import timezones
from src.mobile import analytics


@pytest.mark.parametrize("name, ok", [
    ("Asia/Kolkata", True), ("Europe/London", True), ("America/New_York", True), ("UTC", True),
    ("IST", False), ("Asia/Bombay ", False), ("", False), (None, False), ("Mars/Olympus", False),
])
def test_valid_time_zones(name, ok):
    assert timezones.is_valid_timezone(name) is ok


def test_an_unknown_zone_falls_back_to_the_default():
    assert timezones.zone("Mars/Olympus").key == timezones.DEFAULT_TIMEZONE
    assert timezones.zone(None).key == "Asia/Kolkata"


def test_the_api_accepts_only_iana_zones():
    assert CompanyUpdate(timezone="Europe/Berlin").timezone == "Europe/Berlin"
    with pytest.raises(ValidationError, match="IANA"):
        CompanyUpdate(timezone="GMT+5:30")
    assert CompanyResponse(id="0b3c1c9e-1111-4000-8000-000000000001", name="n", type="TENANT").timezone \
        == "Asia/Kolkata"


def test_india_days_are_what_they_were():
    start, end = analytics.parse_range(date(2026, 10, 1), date(2026, 10, 7), tz_name="Asia/Kolkata")
    assert start == datetime(2026, 9, 30, 18, 30) and end == datetime(2026, 10, 7, 18, 30)


def test_days_follow_the_business_zone_through_dst():
    # New York: EDT (UTC-4) on 1 Nov, EST (UTC-5) after the change on 2 Nov 2026.
    start, end = analytics.parse_range(date(2026, 11, 1), date(2026, 11, 2), tz_name="America/New_York")
    assert start == datetime(2026, 11, 1, 4, 0) and end == datetime(2026, 11, 3, 5, 0)


async def test_the_date_tool_answers_in_the_business_zone(monkeypatch):
    from src.ai.tools.crm import crm_tools

    async def london(company_id, db=None):
        assert company_id == "c-1"
        return timezones.zone("Europe/London")

    monkeypatch.setattr(timezones, "company_timezone", london)
    out = await crm_tools.GetCurrentDateTimeTool().invoke({}, {"company_id": "c-1"})
    assert out.success
    assert out.output["timezone"] == "Europe/London"
    assert out.output["datetime"].endswith(("GMT", "BST"))
    assert datetime.fromisoformat(out.output["iso"]).utcoffset() is not None
    json.dumps(out.output)


async def test_the_zone_is_cached_and_forgotten(monkeypatch):
    calls = []

    class _Result:
        def scalar(self):
            return "Europe/Paris"

    class _Session:
        async def execute(self, statement):
            calls.append(statement)
            return _Result()

    timezones.forget_company_timezone()
    company = "0b3c1c9e-1111-4000-8000-000000000001"
    assert await timezones.company_timezone_name(company, _Session()) == "Europe/Paris"
    assert await timezones.company_timezone_name(company, _Session()) == "Europe/Paris"
    assert len(calls) == 1
    timezones.forget_company_timezone(company)
    await timezones.company_timezone_name(company, _Session())
    assert len(calls) == 2
    timezones.forget_company_timezone()


def test_the_calling_window_stays_on_india_time():
    from src.mobile import service

    assert service.IST.utcoffset(None).total_seconds() == 5.5 * 3600
