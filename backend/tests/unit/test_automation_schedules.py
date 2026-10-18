"""Phase 14 WS3 (tech spec §7.7, §7.10): schedules in the business's time zone.

The plan's test list: cron in IST (no DST) and in a DST zone — a time in the
spring gap fires at the next valid minute, a time in the autumn overlap fires
once — catch-up rules, and the agent tool's ``when``. Limits (most missed
times, shortest agent repeat) apply only when the business set them (D47).
Times are naive UTC.
"""
from datetime import datetime, timedelta

import pytest

from src.automation.schedules import (
    ScheduleError,
    catch_up,
    missed_times,
    next_fire_times,
    parse_duration,
    parse_when,
    preview,
    shortest_interval,
)


def test_every_weekday_at_nine_in_india():
    # Friday 16 Oct 2026, 10:00 IST = 04:30 UTC: next are Mon 19, Tue 20, Wed 21 at 09:00 IST (03:30 UTC).
    times = next_fire_times("0 9 * * 1-5", "Asia/Kolkata", datetime(2026, 10, 16, 4, 30), 3)
    assert times == [datetime(2026, 10, 19, 3, 30), datetime(2026, 10, 20, 3, 30), datetime(2026, 10, 21, 3, 30)]


def test_ten_previews_are_strictly_after_now():
    now = datetime(2026, 10, 18, 3, 30)  # exactly 09:00 IST on a Sunday
    times = next_fire_times("0 9 * * *", "Asia/Kolkata", now, 10)
    assert len(times) == 10 and times[0] == datetime(2026, 10, 19, 3, 30)
    assert all(b - a == timedelta(days=1) for a, b in zip(times, times[1:]))


def test_a_time_in_the_spring_gap_fires_at_the_next_valid_minute():
    # New York, 8 Mar 2026: 02:00 EST jumps to 03:00 EDT; 02:30 does not exist that day.
    times = next_fire_times("30 2 * * *", "America/New_York", datetime(2026, 3, 7, 12, 0), 2)
    assert times == [datetime(2026, 3, 8, 7, 0),     # 03:00 EDT, the next valid minute
                     datetime(2026, 3, 9, 6, 30)]    # 02:30 EDT again the day after


def test_a_time_in_the_autumn_overlap_fires_once():
    # New York, 1 Nov 2026: 01:30 happens twice (EDT, then EST); the first counts.
    times = next_fire_times("30 1 * * *", "America/New_York", datetime(2026, 10, 31, 12, 0), 3)
    assert times == [datetime(2026, 11, 1, 5, 30), datetime(2026, 11, 2, 6, 30), datetime(2026, 11, 3, 6, 30)]


def test_every_fifteen_minutes_across_the_gap_has_no_duplicates():
    times = next_fire_times("*/15 * * * *", "America/New_York", datetime(2026, 3, 8, 6, 30), 6)
    assert times == sorted(set(times))
    assert times[:2] == [datetime(2026, 3, 8, 6, 45), datetime(2026, 3, 8, 7, 0)]


def test_missed_times_and_catch_up():
    missed = missed_times("0 * * * *", "Asia/Kolkata", datetime(2026, 10, 18, 0, 10), datetime(2026, 10, 18, 4, 40))
    # IST's minute 0 is :30 UTC: 00:30 … 04:30 fall inside (00:10, 04:40].
    assert missed == [datetime(2026, 10, 18, h, 30) for h in range(0, 5)]
    assert catch_up(missed, "skip") == []
    assert catch_up(missed, "once") == [datetime(2026, 10, 18, 4, 30)]
    assert catch_up(missed, "all") == missed
    day = missed_times("*/30 * * * *", "UTC", datetime(2026, 10, 17), datetime(2026, 10, 18))
    assert catch_up(day, "all") == day and len(day) == 48           # no limit unless the business sets one
    capped = catch_up(day, "all", max_firings=24)
    assert len(capped) == 24 and capped[-1] == datetime(2026, 10, 18)
    with pytest.raises(ScheduleError):
        catch_up(missed, "replay")


@pytest.mark.parametrize("expression", ["", "0 9 * *", "0 9 * * * *", "61 9 * * *", "every day", None])
def test_invalid_cron_is_refused(expression):
    with pytest.raises(ScheduleError):
        next_fire_times(expression, "Asia/Kolkata", datetime(2026, 10, 18), 1)


def test_an_unknown_zone_is_refused():
    with pytest.raises(ScheduleError, match="IANA"):
        next_fire_times("0 9 * * *", "IST", datetime(2026, 10, 18), 1)


@pytest.mark.parametrize("text, expected", [
    ("30m", timedelta(minutes=30)), ("2h", timedelta(hours=2)), ("3d", timedelta(days=3)),
    ("1w2d", timedelta(days=9)), ("1d12h", timedelta(hours=36)),
])
def test_durations(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "0m", "3 days", "2y", "-1d", "6000w"])
def test_bad_durations(text):
    with pytest.raises(ScheduleError):
        parse_duration(text)


NOW = datetime(2026, 10, 18, 6, 0)  # 11:30 IST


def test_an_agent_follow_up_in_three_days():
    when = parse_when({"in": "3d"}, now=NOW, default_timezone="Asia/Kolkata")
    assert when.kind == "timer" and when.run_at == NOW + timedelta(days=3)


def test_an_agent_follow_up_at_a_local_time_means_the_business_zone():
    when = parse_when({"at": "2026-10-20T15:00"}, now=NOW, default_timezone="Asia/Kolkata")
    assert when.run_at == datetime(2026, 10, 20, 9, 30)
    explicit = parse_when({"at": "2026-10-20T15:00+00:00"}, now=NOW, default_timezone="Asia/Kolkata")
    assert explicit.run_at == datetime(2026, 10, 20, 15, 0)


def test_an_agent_repeating_schedule():
    when = parse_when({"cron": "0 9 * * 1-5"}, now=NOW, default_timezone="Asia/Kolkata")
    assert (when.kind, when.cron, when.timezone) == ("schedule", "0 9 * * 1-5", "Asia/Kolkata")
    assert when.first_fire_at == datetime(2026, 10, 19, 3, 30)


@pytest.mark.parametrize("when, message", [
    ({"at": "2026-10-01T09:00"}, "in the past"),
    ({"at": "2200-10-01T09:00"}, "100 years"),
    ({"at": "tomorrow"}, "ISO-8601"),
    ({"in": "3d", "at": "2026-10-20T09:00"}, "exactly one"),
    ("in 3 days", "exactly one"),
])
def test_agent_when_is_checked(when, message):
    with pytest.raises(ScheduleError, match=message):
        parse_when(when, now=NOW, default_timezone="Asia/Kolkata")


def test_no_repeat_floor_unless_the_business_set_one():
    assert parse_when({"cron": "*/5 * * * *"}, now=NOW, default_timezone="Asia/Kolkata").kind == "schedule"
    floor = timedelta(minutes=15)
    assert parse_when({"cron": "*/15 * * * *"}, now=NOW, default_timezone="Asia/Kolkata", min_interval=floor)
    for too_often in ("*/5 * * * *", "0,10 * * * *"):
        with pytest.raises(ScheduleError, match="every 15 minutes"):
            parse_when({"cron": too_often}, now=NOW, default_timezone="Asia/Kolkata", min_interval=floor)
    assert shortest_interval("*/15 * * * *", "Asia/Kolkata", NOW) == timedelta(minutes=15)


def test_a_far_away_follow_up_is_fine_without_limits():
    when = parse_when({"in": "104w"}, now=NOW, default_timezone="Asia/Kolkata")
    assert when.run_at == NOW + timedelta(weeks=104)


def test_the_editor_preview():
    schedule = {"kind": "schedule", "cron": "0 9 * * 1-5", "timezone": None}
    assert len(preview(schedule, now=NOW, default_timezone="Asia/Kolkata")) == 10
    timer = {"kind": "timer", "run_at": datetime(2026, 10, 20, 9, 30)}
    assert preview(timer, now=NOW, default_timezone="Asia/Kolkata") == [datetime(2026, 10, 20, 9, 30)]
    assert preview({**timer, "run_at": datetime(2026, 10, 1)}, now=NOW, default_timezone="Asia/Kolkata") == []
    assert preview({"kind": "event"}, now=NOW, default_timezone="Asia/Kolkata") == []
