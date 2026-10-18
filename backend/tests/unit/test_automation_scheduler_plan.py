"""What a due trigger fires now (``scheduler.plan``, tech spec §7.7): on time,
late by the catch-up rule (the trigger's, else the business's — D47), never
past its end date or run cap, at most a batch per tick."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from src.automation import limits as limits_mod
from src.automation import scheduler

GRACE = timedelta(minutes=10)
NOW = datetime(2026, 10, 18, 9, 30, 5)


def _trigger(**fields):
    base = dict(kind="schedule", cron="* * * * *", next_fire_at=NOW.replace(second=0), catch_up=None,
                until_at=None, max_firings=None, firings=0)
    return SimpleNamespace(**{**base, **fields})


def _plan(trigger, limits=limits_mod.NO_LIMITS, now=NOW, tz="UTC"):
    return scheduler.plan(trigger, now=now, tz_name=tz, limits=limits, grace=GRACE)


def test_an_on_time_schedule_fires_its_due_time():
    plan = _plan(_trigger())
    assert plan.fire == [NOW.replace(second=0)] and plan.skipped is None and plan.after == NOW


def test_within_the_grace_period_every_due_time_fires():
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(minutes=3)))
    assert len(plan.fire) == 4 and plan.skipped is None


def test_late_with_no_rule_set_fires_every_missed_time():
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(hours=1)))
    assert len(plan.fire) == 61 and plan.skipped is None  # D47: "all" is the default


def test_late_skip_fires_nothing_and_says_what_was_missed():
    first = NOW.replace(second=0) - timedelta(hours=1)
    plan = _plan(_trigger(next_fire_at=first, catch_up="skip"))
    assert plan.fire == [] and plan.skipped == (first, NOW)


def test_late_once_fires_the_latest_and_skips_the_rest():
    first = NOW.replace(second=0) - timedelta(days=3)
    plan = _plan(_trigger(next_fire_at=first, catch_up="once"))
    assert plan.fire == [NOW.replace(second=0)]
    assert plan.skipped[0] == first


def test_the_business_rule_applies_when_the_trigger_has_none():
    limits = limits_mod.resolve({}, {"catch_up": "skip"})
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(hours=1)), limits)
    assert plan.fire == []
    # …and a trigger's own rule wins over the business's.
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(hours=1), catch_up="once"), limits)
    assert len(plan.fire) == 1


def test_the_business_caps_how_many_missed_times_fire():
    limits = limits_mod.resolve({}, {"catch_up_max": 5})
    first = NOW.replace(second=0) - timedelta(days=30)  # a month of minutes, not walked one by one
    plan = _plan(_trigger(next_fire_at=first), limits)
    assert plan.fire == [NOW.replace(second=0) - timedelta(minutes=m) for m in (4, 3, 2, 1, 0)]
    assert plan.skipped[0] == first


def test_a_long_catch_up_fires_a_batch_per_tick():
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(hours=5)))
    assert len(plan.fire) == scheduler.FIRE_BATCH
    assert plan.after == plan.fire[-1]  # the next tick continues from here


def test_nothing_fires_past_the_end_date():
    until = NOW.replace(second=0) - timedelta(minutes=2)
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(minutes=5), until_at=until))
    assert plan.fire[-1] == until and len(plan.fire) == 4


def test_nothing_fires_past_the_run_cap():
    plan = _plan(_trigger(next_fire_at=NOW.replace(second=0) - timedelta(minutes=5), max_firings=3, firings=1))
    assert len(plan.fire) == 2


def test_a_late_timer_fires_once_unless_its_rule_is_skip():
    run_at = NOW - timedelta(hours=2)
    assert _plan(_trigger(kind="timer", next_fire_at=run_at)).fire == [run_at]
    skipped = _plan(_trigger(kind="timer", next_fire_at=run_at, catch_up="skip"))
    assert skipped.fire == [] and skipped.skipped == (run_at, run_at)


def test_a_trigger_not_yet_due_fires_nothing():
    assert _plan(_trigger(next_fire_at=NOW + timedelta(minutes=1))).fire == []


def test_local_time_schedules_through_a_dst_change():
    # 02:30 every day in New York: on 8 March 2026 that time does not exist
    # (clocks jump 02:00 → 03:00), so it fires at the next valid minute, 03:00.
    first = datetime(2026, 3, 7, 7, 30)  # 02:30 EST on the 7th, in UTC
    now = datetime(2026, 3, 8, 7, 5)     # 03:05 EDT on the 8th
    plan = scheduler.plan(_trigger(cron="30 2 * * *", next_fire_at=first), now=now, tz_name="America/New_York",
                          limits=limits_mod.NO_LIMITS, grace=timedelta(days=2))
    assert plan.fire == [first, datetime(2026, 3, 8, 7, 0)]


def test_latest_times_walks_back_only_as_far_as_it_needs():
    first = datetime(2026, 1, 1)
    times = scheduler.latest_times("0 9 1 * *", "UTC", first, datetime(2026, 10, 18), 2)
    assert times == [datetime(2026, 9, 1, 9), datetime(2026, 10, 1, 9)]
