"""Time for triggers (tech spec §7.7, §7.10; functional spec §3.1, §3.5).

* Cron schedules run in an IANA time zone (the business's unless the trigger
  names one). A local time that does not exist (a DST gap) fires at the next
  valid minute; a local time that happens twice (a DST overlap) fires once,
  at its first occurrence. India has no DST, so IST schedules are plain.
* Missed times after a pause or outage follow the trigger's catch-up rule:
  ``skip`` none, ``once`` the latest, ``all`` each — or the latest *N* when the
  business set a "most missed times" limit.
* Agents schedule with ``{"at": iso}``, ``{"in": "3d"}`` or
  ``{"cron": "...", "timezone": "..."}``; a repeating agent schedule fires no
  more often than the business's "shortest repeat", if it set one.

Limits are the business's (decision D47, ``limits.py``); none applies by
default. The only fixed bound is technical: nothing is scheduled more than
100 years ahead.

Times are naive UTC in and out, like the rest of the code base (DM-12).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from croniter import croniter

from src.common.timezones import is_valid_timezone

CATCH_UP_POLICIES = ("skip", "once", "all")
MAX_DELAY = timedelta(days=36525)  # technical: a datetime overflows soon after
_DURATION = re.compile(r"^(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$")


class ScheduleError(ValueError):
    """A schedule that cannot be used; the message says why."""


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def validate_cron(expression: Any) -> str:
    """A standard five-field cron expression, or :class:`ScheduleError`."""
    if not isinstance(expression, str) or len(expression.split()) != 5 or not croniter.is_valid(expression):
        raise ScheduleError(f"{expression!r} is not a five-field cron expression (minute hour day month weekday)")
    return expression


def validate_timezone(name: Any) -> str:
    if not is_valid_timezone(name):
        raise ScheduleError(f"{name!r} is not an IANA time zone (e.g. Asia/Kolkata)")
    return name


def _exists(local: datetime, zone: ZoneInfo) -> bool:
    """Whether a wall-clock time happens in the zone (not inside a DST gap)."""
    aware = local.replace(tzinfo=zone)
    return aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == local


def _to_utc(local: datetime, zone: ZoneInfo) -> datetime:
    """A wall-clock time as naive UTC: a gap moves to the next valid minute; an
    overlap takes its first occurrence (fold=0)."""
    while not _exists(local, zone):
        local += timedelta(minutes=1)
    return local.replace(tzinfo=zone, fold=0).astimezone(timezone.utc).replace(tzinfo=None)


def next_fire_times(expression: str, tz_name: str, after: datetime, count: int = 10) -> List[datetime]:
    """The next ``count`` fire times strictly after ``after`` (naive UTC), as naive UTC."""
    validate_cron(expression)
    zone = ZoneInfo(validate_timezone(tz_name))
    after = _utc_naive(after)
    # Iterate wall-clock times in the zone; each appears once even across an overlap.
    local_start = after.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None) - timedelta(hours=3)
    iterator = croniter(expression, local_start)
    found: List[datetime] = []
    guard = 0
    while len(found) < count:
        guard += 1
        if guard > count * 50 + 1000:
            raise ScheduleError(f"{expression!r} yields no fire time in a reasonable window")
        moment = _to_utc(iterator.get_next(datetime), zone)
        if moment > after and (not found or moment > found[-1]):
            found.append(moment)
    return found


def next_fire_time(expression: str, tz_name: str, after: datetime) -> datetime:
    return next_fire_times(expression, tz_name, after, 1)[0]


def missed_times(expression: str, tz_name: str, since: datetime, until: datetime,
                 limit: int = 1000) -> List[datetime]:
    """Fire times in (since, until] — what a paused or down scheduler did not fire."""
    times: List[datetime] = []
    cursor = _utc_naive(since)
    until = _utc_naive(until)
    while len(times) < limit:
        moment = next_fire_time(expression, tz_name, cursor)
        if moment > until:
            break
        times.append(moment)
        cursor = moment
    return times


def catch_up(missed: List[datetime], policy: str, max_firings: Optional[int] = None) -> List[datetime]:
    """Which missed times to fire now: none, the latest, or each — the latest
    ``max_firings`` when the business set that limit."""
    if policy not in CATCH_UP_POLICIES:
        raise ScheduleError(f"catch-up must be one of {', '.join(CATCH_UP_POLICIES)}")
    if policy == "skip" or not missed:
        return []
    if policy == "once":
        return [max(missed)]
    ordered = sorted(missed)
    return ordered[-max_firings:] if max_firings is not None else ordered


def shortest_interval(expression: str, tz_name: str, after: datetime, samples: int = 300) -> timedelta:
    """The smallest gap between consecutive fire times over the next ``samples`` firings."""
    times = next_fire_times(expression, tz_name, after, samples)
    return min(b - a for a, b in zip(times, times[1:]))


def parse_duration(text: Any) -> timedelta:
    """``"3d"``, ``"2h"``, ``"90m"``, ``"1w2d"`` — weeks, days, hours, minutes."""
    match = _DURATION.match(str(text).strip().lower()) if text else None
    if not match or not any(match.groups()):
        raise ScheduleError(f"{text!r} is not a duration like 30m, 2h, 3d or 1w")
    weeks, days, hours, minutes = (int(part or 0) for part in match.groups())
    delay = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)
    if delay <= timedelta(0) or delay > MAX_DELAY:
        raise ScheduleError(f"{text!r} must be more than zero and less than 100 years")
    return delay


@dataclass(frozen=True)
class When:
    """What an agent asked for: one time (a timer) or a repeating schedule."""

    kind: str                      # "timer" | "schedule"
    run_at: Optional[datetime]     # timer: naive UTC
    cron: Optional[str]            # schedule
    timezone: Optional[str]        # schedule
    first_fire_at: datetime        # naive UTC


def parse_when(when: Any, *, now: datetime, default_timezone: str,
               min_interval: Optional[timedelta] = None) -> When:
    """An agent's ``when`` (schedule_agent): ``{"at": iso}``, ``{"in": "3d"}`` or
    ``{"cron": "0 9 * * 1-5", "timezone": "Asia/Kolkata"}``; ``min_interval`` is
    the business's shortest repeat for agent schedules, if it set one."""
    now = _utc_naive(now)
    if not isinstance(when, dict) or len([k for k in ("at", "in", "cron") if k in when]) != 1:
        raise ScheduleError('when must be exactly one of {"at": ...}, {"in": ...} or {"cron": ...}')
    if "in" in when:
        run_at = now + parse_duration(when["in"])
        return When("timer", run_at, None, None, run_at)
    if "at" in when:
        try:
            moment = datetime.fromisoformat(str(when["at"]))
        except ValueError:
            raise ScheduleError(f"{when['at']!r} is not an ISO-8601 time") from None
        if moment.tzinfo is None:  # a local time means the business's zone
            moment = moment.replace(tzinfo=ZoneInfo(validate_timezone(default_timezone)))
        run_at = _utc_naive(moment)
        if run_at <= now:
            raise ScheduleError(f"{when['at']} is in the past")
        if run_at - now > MAX_DELAY:
            raise ScheduleError(f"{when['at']} is 100 years away or more")
        return When("timer", run_at, None, None, run_at)
    expression = validate_cron(when["cron"])
    tz_name = validate_timezone(when.get("timezone") or default_timezone)
    if min_interval is not None and shortest_interval(expression, tz_name, now) < min_interval:
        minutes = int(min_interval.total_seconds() // 60)
        raise ScheduleError(f"an agent's repeating schedule may fire at most every {minutes} minutes")
    return When("schedule", None, expression, tz_name, next_fire_time(expression, tz_name, now))


def preview(trigger: Dict[str, Any], *, now: datetime, default_timezone: str, count: int = 10) -> List[datetime]:
    """The next fire times a trigger editor shows (functional spec §3.2)."""
    if trigger.get("kind") == "timer":
        run_at = trigger.get("run_at")
        return [run_at] if run_at and _utc_naive(run_at) > _utc_naive(now) else []
    if trigger.get("kind") == "schedule":
        return next_fire_times(trigger["cron"], trigger.get("timezone") or default_timezone, now, count)
    return []
